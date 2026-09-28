"""Manual hardware test: record a short video clip from the Pi Camera Module 3.

Run on a Raspberry Pi 5 with the camera connected to CAM/DISP 0.
Run from repo root with:
    python -m indepensense.vision.tests.manual.record_test

The clip is written to the directory configured by `RECORDING_DIR` with a
filename based on the current time (e.g. `March-06-2026_14-32-05.mp4`).
"""
import time
from datetime import datetime

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    TEST_RECORDING_DIR,
)
from indepensense.vision.picamera import PiCamera

DURATION_SECONDS = 5


def main():
    TEST_RECORDING_DIR.mkdir(parents=True, exist_ok=True)

    filename = datetime.now().strftime("%B-%d-%Y_%H-%M-%S") + ".mp4"
    output_path = TEST_RECORDING_DIR / filename

    camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
    print(f"Recording {DURATION_SECONDS}s to {output_path}")
    try:
        camera.start_recording(str(output_path))
        time.sleep(DURATION_SECONDS)
        camera.stop_recording()
    finally:
        camera.close()
    print(f"Done. Saved: {output_path}")


if __name__ == "__main__":
    main()
