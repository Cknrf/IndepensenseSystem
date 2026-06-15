from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class UltrasonicReading:
    distance_cm: float
    timestamp: float


class UltrasonicSensor(Protocol):
    def read(self) -> UltrasonicReading | None:
        """Return the latest available distance reading.

        Non-blocking. Returns None when no new frame is available, the frame
        was corrupted, or the target is out of range.
        """

    def close(self) -> None:
        ...
