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

    Heading uses the two axes that end up HORIZONTAL once the sensor is
    physically mounted, which depends on the mount and is therefore
    configuration, not a constant. `MAG_FORWARD_AXIS` and
    `MAG_LEFT_AXIS` in `config.py` name them; `axis_component` below
    resolves them. A board lying flat has x/y horizontal and z vertical;
    stand the same board upright and z becomes horizontal while one of
    x/y becomes vertical.

    No tilt compensation is applied — the heading degrades as the
    mounting surface leaves horizontal, because the vertical component
    of Earth's field then leaks into the horizontal axes. Adding tilt
    compensation using the accelerometer is future work.
    """
    magnetic_x: float
    magnetic_y: float
    magnetic_z: float
    heading_deg: float
    timestamp: float


_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def axis_component(
    field: tuple[float, float, float], axis_spec: str,
) -> float:
    """Pick one signed component out of a field vector by name.

    `axis_spec` is an axis letter with an optional sign: `"x"`, `"+y"`,
    `"-z"`. The sign exists because mounting a board the other way round
    flips an axis without changing which axis it is — no amount of
    rotation converts +z into -z.

    Raises ValueError on anything else. Callers resolve axis specs once at
    construction, so a typo in `config.py` fails at startup rather than
    silently producing a mirrored heading.
    """
    sign = 1.0
    name = axis_spec
    if axis_spec[:1] in ("+", "-"):
        sign = -1.0 if axis_spec[0] == "-" else 1.0
        name = axis_spec[1:]
    # Deliberately strict: exactly one sign character at most. Stripping signs
    # loosely would quietly accept "--x" as "-x".
    if name.lower() not in _AXIS_INDEX:
        raise ValueError(
            f"axis spec {axis_spec!r} is not one of x, y, z "
            f"(optionally signed, e.g. '-z')"
        )
    return sign * field[_AXIS_INDEX[name.lower()]]


def heading_from_field(forward: float, left: float) -> float:
    """Compass heading in degrees (0-360) from two horizontal field components.

    `forward` is the field along the direction the wearer faces, `left` the
    field 90° to their left. Those two form a right-handed frame with "up",
    which is what makes 0°=north, 90°=east come out: facing east puts
    magnetic north on your left, so `left` carries the whole field and
    `atan2(left, forward)` returns +90°.

    Lives here, beside the `MagnetometerReading` docstring that defines the
    convention, so the driver and the mock cannot drift apart on the sign or
    the argument order — a flipped `atan2` produces a heading that looks
    plausible while being mirrored, which is close to invisible in testing.
    """
    return math.degrees(math.atan2(left, forward)) % 360.0


class Magnetometer(Protocol):
    def read(self) -> MagnetometerReading | None:
        """Return one magnetometer reading with heading, or None on error."""

    def close(self) -> None:
        ...
