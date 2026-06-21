"""Manual hardware test: capture frames and run YOLOv8 object detection.

Run on a Raspberry Pi 5 with the camera connected to CAM/DISP 0. The first
run downloads the YOLOv8n weights (~6 MB) into the path configured by
`YOLO_MODEL_PATH`.

Run from repo root with:
    python -m indepensense.vision.tests.manual.detect_test
"""
import time

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL_PATH,
)
from indepensense.vision.detector import YOLOv8Detector
from indepensense.vision.picamera import PiCamera

NUM_FRAMES = 10


def main():
    print(f"Loading YOLOv8 model from {YOLO_MODEL_PATH}")
    detector = YOLOv8Detector(
        model_path=YOLO_MODEL_PATH,
        confidence_threshold=YOLO_CONFIDENCE_THRESHOLD,
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
