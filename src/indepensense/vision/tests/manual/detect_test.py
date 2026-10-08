"""Manual hardware test: capture frames and run object detection.

Run on a Raspberry Pi 5 with the camera connected to CAM/DISP 0. Uses the
committed NCNN model at `YOLO_MODEL_DIR` through the same `NCNNDetector`
the runtime uses.

Run from repo root with:
    python -m indepensense.vision.tests.manual.detect_test
"""
import time

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL_DIR,
    YOLO_NUM_THREADS,
)
from indepensense.vision.ncnn_detector import NCNNDetector
from indepensense.vision.picamera import PiCamera

NUM_FRAMES = 10


def main():
    print(f"Loading NCNN model from {YOLO_MODEL_DIR}")
    detector = NCNNDetector(
        model_dir=YOLO_MODEL_DIR,
        confidence_threshold=YOLO_CONFIDENCE_THRESHOLD,
        num_threads=YOLO_NUM_THREADS,
    )
    camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
    print(f"Running detection on {NUM_FRAMES} frames at {CAMERA_WIDTH}x{CAMERA_HEIGHT}")
    try:
        for i in range(NUM_FRAMES):
            frame = camera.capture()
            t0 = time.time()
            detections = detector.detect(frame)
            elapsed_ms = (time.time() - t0) * 1000
            if detections:
                summary = ", ".join(
                    f"{d.class_name} {d.confidence:.2f} at {d.bbox}"
                    for d in detections
                )
                print(f"frame {i:2d} ({elapsed_ms:5.0f} ms): {summary}")
            else:
                print(f"frame {i:2d} ({elapsed_ms:5.0f} ms): no detections")
    finally:
        camera.close()
    print("Done.")


if __name__ == "__main__":
    main()
