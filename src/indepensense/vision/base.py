from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class Frame:
    """A single camera frame.

    `image` is a numpy ndarray with shape (H, W, 3), dtype uint8. The channel
    order depends on the driver — picamera2 with `format="RGB888"` actually
    returns BGR-ordered numpy data (libcamera convention), which happens to
    match what OpenCV and YOLOv8 expect natively.

    Typed as Any so this module imports cleanly without numpy installed.
    """
    image: Any
    timestamp: float
    width: int
    height: int


@dataclass(frozen=True)
class Detection:
    """A single object detected in a frame.

    `bbox` is in pixel coordinates of the source frame as
    (x_min, y_min, x_max, y_max).
    """
    class_name: str
    confidence: float
    bbox: tuple[int, int, int, int]


class Camera(Protocol):
    def capture(self) -> Frame:
        """Capture a single frame. Blocks until a frame is ready."""

    def close(self) -> None:
        ...


class Detector(Protocol):
    def detect(self, frame: Frame) -> list[Detection]:
        """Run inference on the frame and return detected objects."""
