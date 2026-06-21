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


class Camera(Protocol):
    def capture(self) -> Frame:
        """Capture a single frame. Blocks until a frame is ready."""

    def close(self) -> None:
        ...
