"""Continuous YOLO detection with terminal output.

Runs the camera + detector in an infinite loop and prints what the
model saw on each frame. No GUI, so it runs happily over SSH — you
just watch the terminal.

Prints per-frame:
    [frame N] (XXX ms) K objects: cls1 0.87, cls2 0.72, ...

And every 10 frames, a rolling-stats line:
    [stats @ N] avg XXX ms/frame, X.X FPS, unique classes seen: N

Ctrl-C to stop and see the final summary.

Run from repo root:
    python -m indepensense.vision.tests.manual.continuous_detect_test
"""
import time
from collections import Counter

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL_PATH,
)
from indepensense.vision.detector import YOLOv8Detector
from indepensense.vision.picamera import PiCamera


_STATS_EVERY_N_FRAMES = 10


def main():
    print(f"Loading YOLOv8 model from {YOLO_MODEL_PATH}...")
    detector = YOLOv8Detector(
        model_path=YOLO_MODEL_PATH,
        confidence_threshold=YOLO_CONFIDENCE_THRESHOLD,
    )
    print(f"Opening camera at {CAMERA_WIDTH}x{CAMERA_HEIGHT}...")
    camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)

    print(f"Continuous detection running (confidence threshold "
          f"{YOLO_CONFIDENCE_THRESHOLD}). Ctrl-C to stop.\n")

    frame_count = 0
    total_inference_s = 0.0
    total_objects = 0
    class_counter: Counter[str] = Counter()

    try:
        while True:
            frame = camera.capture()

            t0 = time.time()
            detections = detector.detect(frame)
            inference_ms = (time.time() - t0) * 1000

            frame_count += 1
            total_inference_s += inference_ms / 1000.0
            total_objects += len(detections)
            for det in detections:
                class_counter[det.class_name] += 1

            # Per-frame summary
            if detections:
                summary = ", ".join(
                    f"{d.class_name} {d.confidence:.2f}"
                    for d in detections
                )
                print(f"[frame {frame_count:4d}] ({inference_ms:4.0f} ms) "
                      f"{len(detections)} objects: {summary}")
            else:
                print(f"[frame {frame_count:4d}] ({inference_ms:4.0f} ms) no objects")

            # Rolling stats every N frames
            if frame_count % _STATS_EVERY_N_FRAMES == 0:
                avg_ms = (total_inference_s / frame_count) * 1000
                fps = 1000 / avg_ms if avg_ms > 0 else 0
                print(f"[stats @ {frame_count}] avg {avg_ms:4.0f} ms/frame, "
                      f"{fps:.1f} FPS, unique classes seen: {len(class_counter)}\n")
    except KeyboardInterrupt:
        print()   # newline after ^C
    finally:
        camera.close()

    # Final summary
    print()
    print("=" * 60)
    print(f"Final summary after {frame_count} frames:")
    if frame_count > 0:
        avg_ms = (total_inference_s / frame_count) * 1000
        fps = 1000 / avg_ms if avg_ms > 0 else 0
        print(f"  Avg inference:  {avg_ms:.0f} ms/frame ({fps:.2f} FPS)")
        print(f"  Total objects:  {total_objects} ({total_objects / frame_count:.1f} per frame avg)")
        print(f"  Unique classes: {len(class_counter)}")
        if class_counter:
            print()
            print("  Top classes by count:")
            for name, count in class_counter.most_common(15):
                print(f"    {name:30s}  {count}")


if __name__ == "__main__":
    main()
