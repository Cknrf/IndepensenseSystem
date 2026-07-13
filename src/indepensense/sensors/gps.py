"""NMEA-0183 parser and SIM7600G-H GPS driver.

The SIM7600G-H streams NMEA sentences on its dedicated GPS serial port
(`/dev/ttyUSB1` on a Pi 5) at 115200 baud, once GPS has been enabled with
`AT+CGPS=1` via one of the AT command ports. This module handles two
sentence types:

- `$GxRMC` — Recommended Minimum data: fix status, position, speed, course
- `$GxGGA` — GPS fix data: position, fix quality, satellite count, altitude

The `Gx` prefix varies by constellation: `$GP` for GPS-only receivers,
`$GN` for multi-constellation receivers (GPS + GLONASS + BeiDou + Galileo)
— the SIM7600G-H emits `$GN` sentences.
"""
import time
from dataclasses import dataclass

from indepensense.sensors.base import GPSFix


@dataclass(frozen=True)
class RMCData:
    """Parsed $GxRMC — Recommended Minimum data."""
    active: bool
    lat: float | None
    lon: float | None
    speed_knots: float | None
    course_deg: float | None
    utc_time: str | None


@dataclass(frozen=True)
class GGAData:
    """Parsed $GxGGA — GPS fix data."""
    lat: float | None
    lon: float | None
    fix_quality: int
    satellites: int
    hdop: float | None
    altitude_m: float | None
    utc_time: str | None


def validate_nmea_checksum(sentence: str) -> bool:
    """Verify the two-hex-digit checksum after '*' matches the XOR of the body.

    NMEA-0183: the checksum is the XOR of every character between '$' (exclusive)
    and '*' (exclusive), expressed as two uppercase hex digits.
    """
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, tail = sentence[1:].partition("*")
    tail = tail.strip()
    if len(tail) < 2:
        return False
    expected = tail[:2].upper()
    calculated = 0
    for ch in body:
        calculated ^= ord(ch)
    return f"{calculated:02X}" == expected


def parse_nmea_coordinate(field: str, hemisphere: str) -> float | None:
    """Convert an NMEA lat/lon field to signed decimal degrees.

    NMEA encodes coordinates as DDMM.MMMM (latitude, 2-digit degrees) or
    DDDMM.MMMM (longitude, 3-digit degrees). The last two digits before the
    decimal point are always the whole-minutes portion, regardless of whether
    the value is lat or lon — so we split at "dot minus 2" rather than at a
    fixed offset.
    """
    if not field or hemisphere not in ("N", "S", "E", "W"):
        return None
    try:
        dot_index = field.index(".")
    except ValueError:
        return None
    if dot_index < 3:
        return None
    try:
        degrees = int(field[: dot_index - 2])
        minutes = float(field[dot_index - 2 :])
    except ValueError:
        return None
    decimal = degrees + minutes / 60.0
    if hemisphere in ("S", "W"):
        decimal = -decimal
    return decimal


def _try_float(field: str) -> float | None:
    if not field:
        return None
    try:
        return float(field)
    except ValueError:
        return None


def _try_int(field: str, default: int = 0) -> int:
    if not field:
        return default
    try:
        return int(field)
    except ValueError:
        return default


def parse_nmea_rmc(sentence: str) -> RMCData | None:
    """Parse a $GxRMC sentence. Returns None on invalid input or bad checksum."""
    if not validate_nmea_checksum(sentence):
        return None
    fields = sentence[1:].split("*")[0].split(",")
    # Expected: type, time, status, lat, latH, lon, lonH, speed, course, date, ...
    if len(fields) < 10 or not fields[0].endswith("RMC"):
        return None
    lat = parse_nmea_coordinate(fields[3], fields[4]) if fields[3] and fields[4] else None
    lon = parse_nmea_coordinate(fields[5], fields[6]) if fields[5] and fields[6] else None
    return RMCData(
        active=(fields[2] == "A"),
        lat=lat,
        lon=lon,
        speed_knots=_try_float(fields[7]),
        course_deg=_try_float(fields[8]),
        utc_time=fields[1] or None,
    )


def parse_nmea_gga(sentence: str) -> GGAData | None:
    """Parse a $GxGGA sentence. Returns None on invalid input or bad checksum."""
    if not validate_nmea_checksum(sentence):
        return None
    fields = sentence[1:].split("*")[0].split(",")
    # Expected: type, time, lat, latH, lon, lonH, quality, sats, hdop, alt, altU, ...
    if len(fields) < 10 or not fields[0].endswith("GGA"):
        return None
    lat = parse_nmea_coordinate(fields[2], fields[3]) if fields[2] and fields[3] else None
    lon = parse_nmea_coordinate(fields[4], fields[5]) if fields[4] and fields[5] else None
    return GGAData(
        lat=lat,
        lon=lon,
        fix_quality=_try_int(fields[6], default=0),
        satellites=_try_int(fields[7], default=0),
        hdop=_try_float(fields[8]),
        altitude_m=_try_float(fields[9]),
        utc_time=fields[1] or None,
    )


class SIM7600GPS:
    """GPS driver for the SIM7600G-H over its dedicated NMEA serial port.

    Assumes GPS has already been enabled on the modem with `AT+CGPS=1`
    (typically issued once per boot on `/dev/ttyUSB2` or `/dev/ttyUSB3`).
    The driver reads all pending lines on each `read()` call, updates the
    last-seen RMC and GGA state, and returns a merged `GPSFix` if a
    position is known — otherwise `None`.
    """

    def __init__(
        self,
        port: str = "/dev/ttyUSB1",
        baudrate: int = 115200,
        timeout_s: float = 0.5,
    ):
        import serial  # lazy: only resolvable on the Pi

        self._ser = serial.Serial(port, baudrate=baudrate, timeout=timeout_s)
        self._ser.reset_input_buffer()
        self._last_rmc: RMCData | None = None
        self._last_gga: GGAData | None = None

    def read(self) -> GPSFix | None:
        # Drain everything currently in the buffer, keeping the most recent
        # RMC and GGA. If neither has arrived yet, we have no fix.
        while self._ser.in_waiting > 0:
            raw = self._ser.readline()
            if not raw:
                break
            line = raw.decode("ascii", errors="ignore").strip()
            if not line:
                continue
            if "RMC" in line[:6]:
                rmc = parse_nmea_rmc(line)
                if rmc is not None:
                    self._last_rmc = rmc
            elif "GGA" in line[:6]:
                gga = parse_nmea_gga(line)
                if gga is not None:
                    self._last_gga = gga

        gga = self._last_gga
        rmc = self._last_rmc

        # Prefer GGA's coordinates (it also carries fix quality); fall back to
        # RMC if GGA hasn't given us a fix yet but RMC has an active one.
        if gga is not None and gga.lat is not None and gga.lon is not None:
            lat, lon = gga.lat, gga.lon
        elif rmc is not None and rmc.active and rmc.lat is not None and rmc.lon is not None:
            lat, lon = rmc.lat, rmc.lon
        else:
            return None

        return GPSFix(
            lat=lat,
            lon=lon,
            altitude_m=gga.altitude_m if gga else None,
            speed_knots=rmc.speed_knots if rmc else None,
            course_deg=rmc.course_deg if rmc else None,
            satellites=gga.satellites if gga else None,
            hdop=gga.hdop if gga else None,
            fix_quality=gga.fix_quality if gga else 0,
            utc_time=(gga.utc_time if gga else None) or (rmc.utc_time if rmc else None),
            timestamp=time.time(),
        )

    def close(self) -> None:
        self._ser.close()
