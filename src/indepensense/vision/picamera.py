"""Raspberry Pi Camera Module 3 driver, wrapping the picamera2 library.

picamera2 is the modern (Bookworm/Trixie+) Python binding for libcamera. It is
installed on the Pi via apt (`sudo apt install python3-picamera2`), NOT pip —
its libcamera dependency cannot be installed from PyPI. The venv on the Pi
must be created with `--system-site-packages` so it can see the apt-installed
package.

Output size and sensor mode are separate settings
-------------------------------------------------

`main` is the image you get out. `raw` is how much of the sensor is read to
produce it, and that is what determines field of view. They are easy to
conflate because both are expressed in pixels, but raising the output size
buys detail while raising the sensor mode buys *view*.

The distinction is not academic here. Left to choose, picamera2 takes the
smallest sensor mode that can satisfy the output, and on the imx708_wide the
smallest mode reads a centred 3072×1728 window of the 4608×2592 array. Asking
for 1280×720 therefore cost about a third of the frame in each dimension —
invisibly, because a cropped image looks like a perfectly good image. The
driver takes the mode as an explicit parameter so that choice is recorded in
`config.py` rather than made by inference. `sensor_crop()` is how you check
which one you actually got.
"""
import time

from indepensense.vision.base import Frame


class PiCamera:
    def __init__(
        self,
        width: int,
        height: int,
        fps: int,
        sensor_mode_width: int | None = None,
        sensor_mode_height: int | None = None,
    ):
        from picamera2 import Picamera2  # lazy: only resolvable on the Pi

        self._picam = Picamera2()
        # Only pin the sensor mode when both dimensions are given; picamera2
        # matches `raw` against the modes the sensor advertises, so a partial
        # spec is meaningless rather than merely imprecise.
        raw = None
        if sensor_mode_width is not None and sensor_mode_height is not None:
            raw = {"size": (sensor_mode_width, sensor_mode_height)}
        configuration = self._picam.create_video_configuration(
            main={"size": (width, height), "format": "RGB888"},
            raw=raw,
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

    def sensor_crop(self) -> tuple[int, int, int, int] | None:
        """The sensor rectangle currently feeding the image, as (x, y, w, h).

        Reported by the ISP per frame as `ScalerCrop`, so this is what the
        hardware is really doing rather than what was asked for. On the
        imx708_wide, (0, 0, 4608, 2592) is the full lens; anything smaller is
        a crop and a narrower field of view. Manual tests print it because a
        cropped frame is indistinguishable from a full one by eye.

        Returns None if the metadata has no crop — some sensors omit it.
        """
        crop = self._picam.capture_metadata().get("ScalerCrop")
        return tuple(crop) if crop is not None else None

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
