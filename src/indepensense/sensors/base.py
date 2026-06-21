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


@dataclass(frozen=True)
class IMUReading:
    """One sample from a 6-axis IMU.

    Linear acceleration in `g` (1 g ≈ 9.81 m/s²); angular velocity in
    degrees/second; temperature in °C.
    """
    accel_x: float
    accel_y: float
    accel_z: float
    gyro_x: float
    gyro_y: float
    gyro_z: float
    temperature_c: float
    timestamp: float


class IMUSensor(Protocol):
    def read(self) -> IMUReading | None:
        """Return one accelerometer + gyroscope sample.

        Returns None on I²C bus error.
        """

    def close(self) -> None:
        ...
