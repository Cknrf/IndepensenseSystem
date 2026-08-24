import math
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


@dataclass(frozen=True)
class GPSFix:
    """A GPS position derived by combining NMEA sentences from the receiver.

    Named "fix" rather than "reading" because that is the standard GPS term
    for a computed position — a fix is what a receiver produces when enough
    satellites are locked to solve for location. Fields sourced only from
    RMC or GGA can be None if that sentence has not been seen recently.
    """
    lat: float
    lon: float
    altitude_m: float | None
    speed_knots: float | None
    course_deg: float | None
    satellites: int | None
    hdop: float | None
    fix_quality: int              # 0=no fix, 1=GPS, 2=DGPS, ...
    utc_time: str | None          # HHMMSS.sss from the source sentence
    timestamp: float              # local time.time() when the fix was assembled


class GPSSensor(Protocol):
    def read(self) -> GPSFix | None:
        """Return the latest available fix, or None if no fix yet or bus error."""

    def close(self) -> None:
        ...


@dataclass(frozen=True)
class MagnetometerReading:
    """One sample from a 3-axis magnetometer.

    Field values are in microtesla (μT), calibrated (user hard-iron
    offsets applied). Earth's magnetic field is ~25-65 μT depending on
    location.

    `heading_deg` is the horizontal compass heading in degrees:
      0°   = magnetic north
      90°  = east
      180° = south
      270° = west

    The heading assumes the X-axis of the sensor points TOWARD the
    front of the cane. Rotate the module 90° at mount time if your
    physical layout puts a different axis forward, or apply a rotation
    offset in the config.

    No tilt compensation is applied — if the cane is significantly
    off-vertical, the heading degrades. Adding tilt compensation using
    the accelerometer is future work.
    """
    magnetic_x: float
    magnetic_y: float
    magnetic_z: float
    heading_deg: float
    timestamp: float


def heading_from_field(magnetic_x: float, magnetic_y: float) -> float:
    """Compass heading in degrees (0-360) from horizontal field components.

    Lives here, beside the `MagnetometerReading` docstring that defines the
    convention, so the driver and the mock cannot drift apart on the sign or
    the axis order — a flipped `atan2` argument produces a heading that looks
    plausible while being mirrored, which is close to invisible in testing.
    """
    return math.degrees(math.atan2(magnetic_y, magnetic_x)) % 360.0


class Magnetometer(Protocol):
    def read(self) -> MagnetometerReading | None:
        """Return one magnetometer reading with heading, or None on error."""

    def close(self) -> None:
        ...
