"""Manual hardware test: capture frames from the Pi Camera Module 3.

Run on a Raspberry Pi 5 with the camera connected to CAM/DISP 0.
Run from repo root with:
    python -m indepensense.vision.tests.manual.capture_test
"""
import time

from indepensense.config import CAMERA_FPS, CAMERA_HEIGHT, CAMERA_WIDTH
from indepensense.vision.picamera import PiCamera

NUM_FRAMES = 10


def main():
    camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
    print(f"Capturing {NUM_FRAMES} frames at {CAMERA_WIDTH}x{CAMERA_HEIGHT} @ {CAMERA_FPS} fps")
    try:
        for i in range(NUM_FRAMES):
            frame = camera.capture()
            print(f"  frame {i:2d}: shape={frame.image.shape}, dtype={frame.image.dtype}, ts={frame.timestamp:.3f}")
            time.sleep(1.0 / CAMERA_FPS)
    finally:
        camera.close()
    print("Done.")


if __name__ == "__main__":
    main()
