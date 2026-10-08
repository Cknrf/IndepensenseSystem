"""Detector latency, memory, and its effect on a 100 Hz loop, per model and thread count.

Answers three questions the thesis has to measure rather than estimate:
  - how long one `vision.describe` detection takes on this device
  - how much RAM the detector adds (it shares 8 GB with Ollama, Whisper,
    two TTS engines, GraphHopper and Photon)
  - whether inference starves the 100 Hz main loop — the reason
    `YOLO_NUM_THREADS` is 3 and not 4

Each configuration runs in a fresh child process, so one model's memory
never inflates the next one's numbers. While the child runs inference, this
process runs a 100 Hz sleep loop and records how late each tick is, which
is what the fall-detection loop would feel. Run it with the wearable
running too (`systemctl start indepensense`) to measure the real contention.

Run from repo root on the Pi:
    python -m indepensense.vision.tests.manual.detector_benchmark
    python -m indepensense.vision.tests.manual.detector_benchmark --threads 2 3 4
    python -m indepensense.vision.tests.manual.detector_benchmark --models DIR_A DIR_B --image street.jpg
    python -m indepensense.vision.tests.manual.detector_benchmark --camera --csv

`--baseline-pt models/yolov8m-oiv7.pt` adds an ultralytics/PyTorch row for
comparison with the previous detector (needs ultralytics installed).
"""
import argparse
import csv
import json
import os
import resource
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    PERF_LOG_DIR,
    YOLO_MODEL_DIR,
    YOLO_NUM_THREADS,
)

_LOOP_PERIOD_S = 0.01   # the main loop's 100 Hz


def _peak_rss_mb() -> float:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / 2**20 if sys.platform == "darwin" else peak / 1024   # bytes on macOS, KiB on Linux


def _load_frame(image: str | None):
    import numpy as np

    if image is None:
        # Noise exercises the same compute as a real frame; detections are
        # irrelevant here, only time and memory are measured.
        return np.random.default_rng(0).integers(0, 255, (CAMERA_HEIGHT, CAMERA_WIDTH, 3), dtype=np.uint8)
    from PIL import Image

    return np.ascontiguousarray(np.array(Image.open(image).convert("RGB"))[:, :, ::-1])


def child(kind: str, model: str, threads: int, frames: int, image: str | None) -> None:
    """Runs in the subprocess: load, warm up, time `frames` detections, print one JSON line."""
    import psutil

    from indepensense.vision.base import Frame

    proc = psutil.Process()
    frame_image = _load_frame(image)
    h, w = frame_image.shape[:2]
    frame = Frame(image=frame_image, timestamp=0.0, width=w, height=h)
    rss_start = proc.memory_info().rss / 2**20
    t0 = time.perf_counter()
    if kind == "ncnn":
        from indepensense.vision.ncnn_detector import NCNNDetector

        detector = NCNNDetector(Path(model), confidence_threshold=0.3, num_threads=threads)
        run = lambda: detector.detect(frame)
    else:
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(threads)
        yolo = YOLO(model)
        run = lambda: yolo.predict(frame_image, conf=0.3, verbose=False)
        run()   # NCNNDetector warms up in its constructor; match it
    load_ms = (time.perf_counter() - t0) * 1000
    rss_loaded = proc.memory_info().rss / 2**20
    print("READY", flush=True)
    times = []
    for _ in range(frames):
        t = time.perf_counter()
        run()
        times.append((time.perf_counter() - t) * 1000)
    times.sort()
    print(json.dumps({
        "load_ms": round(load_ms), "median_ms": round(statistics.median(times), 1),
        "p90_ms": round(times[int(0.9 * (len(times) - 1))], 1),
        "rss_added_mb": round(rss_loaded - rss_start), "peak_rss_mb": round(_peak_rss_mb()),
    }), flush=True)


def _tick_lateness(stop: threading.Event, out: list[float]) -> None:
    """A 100 Hz loop like `App.run`'s, recording how late each tick wakes (ms)."""
    deadline = time.perf_counter() + _LOOP_PERIOD_S
    while not stop.is_set():
        time.sleep(max(0.0, deadline - time.perf_counter()))
        now = time.perf_counter()
        out.append((now - deadline) * 1000)
        deadline = max(deadline + _LOOP_PERIOD_S, now)


def measure(kind: str, model: str, threads: int, frames: int, image: str | None) -> dict:
    cmd = [sys.executable, "-m", "indepensense.vision.tests.manual.detector_benchmark",
           "--child", kind, model, str(threads), str(frames), image or ""]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, text=True)
    lateness, stop = [], threading.Event()
    for line in proc.stdout:
        if line.startswith("READY"):
            break
    ticker = threading.Thread(target=_tick_lateness, args=(stop, lateness), daemon=True)
    ticker.start()
    result_line = proc.stdout.readline()
    stop.set()
    ticker.join()
    proc.wait()
    result = json.loads(result_line)
    lateness.sort()
    result.update({
        "kind": kind, "model": Path(model).name, "threads": threads,
        "loop_p99_late_ms": round(lateness[int(0.99 * (len(lateness) - 1))], 1) if lateness else None,
        "loop_max_late_ms": round(lateness[-1], 1) if lateness else None,
    })
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--models", nargs="+", default=[str(YOLO_MODEL_DIR)], help="NCNN model directories")
    parser.add_argument("--threads", nargs="+", type=int, default=[YOLO_NUM_THREADS])
    parser.add_argument("--frames", type=int, default=30)
    parser.add_argument("--image", help="image to run on (default: noise at camera resolution)")
    parser.add_argument("--camera", action="store_true", help="capture one frame from the Pi camera and use it")
    parser.add_argument("--baseline-pt", help="also time an ultralytics .pt model (e.g. the old yolov8m-oiv7)")
    parser.add_argument("--csv", action="store_true", help=f"also write results under {PERF_LOG_DIR}")
    parser.add_argument("--child", nargs=5, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.child:
        kind, model, threads, frames, image = args.child
        child(kind, model, int(threads), int(frames), image or None)
        return

    image = args.image
    if args.camera:
        from PIL import Image

        from indepensense.vision.picamera import PiCamera

        camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
        try:
            bgr = camera.capture().image
        finally:
            camera.close()
        image = str(PERF_LOG_DIR / "benchmark_frame.jpg")
        PERF_LOG_DIR.mkdir(parents=True, exist_ok=True)
        Image.fromarray(bgr[:, :, ::-1]).save(image)

    import psutil

    mem = psutil.virtual_memory()
    print(f"system: load {os.getloadavg()[0]:.2f}, {mem.available / 2**30:.2f} GB available of {mem.total / 2**30:.2f} GB")
    runs = [("ncnn", m, t) for m in args.models for t in args.threads]
    if args.baseline_pt:
        runs += [("ultralytics", args.baseline_pt, t) for t in args.threads]
    rows = []
    print(f"{'model':38s} {'thr':>3s} {'load':>6s} {'median':>7s} {'p90':>7s} {'+RSS':>6s} {'peak':>6s} {'loop p99 late':>14s} {'max':>6s}")
    for kind, model, threads in runs:
        r = measure(kind, model, threads, args.frames, image)
        rows.append(r)
        print(f"{r['model'][:38]:38s} {threads:3d} {r['load_ms']:5d}ms {r['median_ms']:6.1f}ms {r['p90_ms']:6.1f}ms "
              f"{r['rss_added_mb']:4d}MB {r['peak_rss_mb']:4d}MB {r['loop_p99_late_ms']:12.1f}ms {r['loop_max_late_ms']:5.1f}ms")
    if args.csv:
        PERF_LOG_DIR.mkdir(parents=True, exist_ok=True)
        path = PERF_LOG_DIR / f"{datetime.now():%B-%d-%Y_%H-%M-%S}_detector_benchmark.csv"
        with open(path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"CSV saved: {path}")


if __name__ == "__main__":
    main()
