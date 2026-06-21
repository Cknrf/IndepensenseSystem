"""Raspberry Pi Camera Module 3 driver, wrapping the picamera2 library.

picamera2 is the modern (Bookworm/Trixie+) Python binding for libcamera. It is
installed on the Pi via apt (`sudo apt install python3-picamera2`), NOT pip —
its libcamera dependency cannot be installed from PyPI. The venv on the Pi
must be created with `--system-site-packages` so it can see the apt-installed
package.
"""
import time

from indepensense.vision.base import Frame


class PiCamera:
    def __init__(self, width: int, height: int, fps: int):
        from picamera2 import Picamera2  # lazy: only resolvable on the Pi

        self._picam = Picamera2()
        configuration = self._picam.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"},
            controls={"FrameRate": fps},
        )
        self._picam.configure(configuration)
        self._picam.start()
        # Give the sensor a moment to settle on exposure/gain before first capture.
        time.sleep(0.5)
        self._width = width
        self._height = height
        self._encoder = None
        self._output = None

    def capture(self) -> Frame:
        image = self._picam.capture_array()
        return Frame(
            image=image,
            timestamp=time.time(),
            width=self._width,
            height=self._height,
        )

    def start_recording(self, output_path: str) -> None:
        """Begin recording video to `output_path`. Frame capture continues to work."""
        from picamera2.encoders import H264Encoder
        from picamera2.outputs import FfmpegOutput

        self._encoder = H264Encoder()
        self._output = FfmpegOutput(output_path)
        self._picam.start_encoder(self._encoder, self._output)

    def stop_recording(self) -> None:
        self._picam.stop_encoder()
        self._encoder = None
        self._output = None

    def close(self) -> None:
        self._picam.stop()
        self._picam.close()
