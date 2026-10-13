import pytest

from indepensense.sensors.gps import (
    parse_nmea_coordinate,
    parse_nmea_gga,
    parse_nmea_rmc,
    validate_nmea_checksum,
)


# Canonical NMEA test sentences (well-known checksums, widely published).
# Position: 48°07.038' N, 011°31.000' E == 48.1173, 11.51667 (Munich area).
_VALID_GGA = "$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,*47"
_VALID_RMC = "$GPRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,003.1,W*6A"

# Multi-constellation variant emitted by the SIM7600G-H.
_VALID_GNRMC = "$GNRMC,123519,A,4807.038,N,01131.000,E,022.4,084.4,230394,,,A*62"


# --- validate_nmea_checksum --------------------------------------------------

def test_validates_correct_checksum():
    assert validate_nmea_checksum(_VALID_GGA) is True
    assert validate_nmea_checksum(_VALID_RMC) is True


def test_rejects_wrong_checksum():
    # Flip the last hex digit
    corrupt = _VALID_GGA[:-1] + "0"
    assert validate_nmea_checksum(corrupt) is False


def test_rejects_missing_dollar_prefix():
    assert validate_nmea_checksum("GPGGA,123519,...*47") is False


def test_rejects_missing_asterisk():
    assert validate_nmea_checksum("$GPGGA,123519,4807.038,N") is False


def test_handles_trailing_crlf():
    # NMEA sentences from a serial port typically arrive with \r\n
    assert validate_nmea_checksum(_VALID_GGA + "\r\n") is True


# --- parse_nmea_coordinate ---------------------------------------------------

def test_parses_latitude_northern_hemisphere():
    # 4807.038 N -> 48 + 7.038/60 = 48.1173
    result = parse_nmea_coordinate("4807.038", "N")
    assert result == pytest.approx(48.1173, abs=1e-4)


def test_parses_longitude_eastern_hemisphere():
    # 01131.000 E -> 11 + 31.000/60 = 11.51667
    result = parse_nmea_coordinate("01131.000", "E")
    assert result == pytest.approx(11.51667, abs=1e-4)


def test_southern_hemisphere_is_negative():
    result = parse_nmea_coordinate("4807.038", "S")
    assert result == pytest.approx(-48.1173, abs=1e-4)


def test_western_hemisphere_is_negative():
    result = parse_nmea_coordinate("01131.000", "W")
    assert result == pytest.approx(-11.51667, abs=1e-4)


def test_rejects_invalid_hemisphere():
    assert parse_nmea_coordinate("4807.038", "X") is None


def test_rejects_empty_field():
    assert parse_nmea_coordinate("", "N") is None


# --- parse_nmea_gga ----------------------------------------------------------

def test_parses_valid_gga():
    result = parse_nmea_gga(_VALID_GGA)
    assert result is not None
    assert result.lat == pytest.approx(48.1173, abs=1e-4)
    assert result.lon == pytest.approx(11.51667, abs=1e-4)
    assert result.fix_quality == 1
    assert result.satellites == 8
    assert result.hdop == pytest.approx(0.9)
    assert result.altitude_m == pytest.approx(545.4)
    assert result.utc_time == "123519"


def test_gga_rejects_wrong_sentence_type():
    # Same shape but claims to be RMC — should be rejected by GGA parser
    assert parse_nmea_gga(_VALID_RMC) is None


def test_gga_rejects_bad_checksum():
    corrupt = _VALID_GGA[:-1] + "0"
    assert parse_nmea_gga(corrupt) is None


# --- parse_nmea_rmc ----------------------------------------------------------

def test_parses_valid_rmc():
    result = parse_nmea_rmc(_VALID_RMC)
    assert result is not None
    assert result.active is True
    assert result.lat == pytest.approx(48.1173, abs=1e-4)
    assert result.lon == pytest.approx(11.51667, abs=1e-4)
    assert result.speed_knots == pytest.approx(22.4)
    assert result.course_deg == pytest.approx(84.4)
    assert result.utc_time == "123519"


def test_parses_multi_constellation_rmc():
    # SIM7600G-H emits $GN* (multi-constellation), not $GP*
    result = parse_nmea_rmc(_VALID_GNRMC)
    assert result is not None
    assert result.active is True
    assert result.lat == pytest.approx(48.1173, abs=1e-4)


def test_rmc_status_void_is_inactive():
    # Same as _VALID_RMC but with status field 'V' (void) and matching checksum.
    # We construct it fresh so the checksum is computed correctly.
    body = "GPRMC,123519,V,,,,,,,230394,,"
    calculated = 0
    for ch in body:
        calculated ^= ord(ch)
    void_sentence = f"${body}*{calculated:02X}"
    result = parse_nmea_rmc(void_sentence)
    assert result is not None
    assert result.active is False
    assert result.lat is None
    assert result.lon is None


# --- read(): sentences that stop arriving ------------------------------------
#
# `read()` used to answer from the last parsed sentence whatever the port
# was doing, and stamp the result with a fresh `time.time()`. A receiver
# that fell silent — GPS session dropped, `AT+CGPS` turned off underneath
# us, port open but mute — therefore had its last known position re-dated
# once a second and served indefinitely, with nothing in the value to say
# so and no exception for the cache above to count.
#
# The ordinary loss of fix does not look like this: under cover the
# receiver keeps talking and empties the position fields, which is already
# reported honestly. It was specifically silence being read as news.


class _FakeSerial:
    """A serial port whose pending lines are scripted."""

    def __init__(self, lines=()):
        self.lines = [l.encode("ascii") for l in lines]

    @property
    def in_waiting(self):
        return len(self.lines)

    def readline(self):
        return self.lines.pop(0) if self.lines else b""


def _driver(lines=(), max_sentence_age_s=5.0):
    """A driver around a fake port.

    Built without `__init__`, which opens a real serial device and imports
    `serial` — neither of which exists on the development machine. The
    parsing and staleness logic under test is all in `read()`.
    """
    from indepensense.sensors.gps import SIM7600GPS

    gps = object.__new__(SIM7600GPS)
    gps._ser = _FakeSerial(lines)
    gps._last_rmc = None
    gps._last_gga = None
    gps._max_sentence_age_s = max_sentence_age_s
    gps._last_sentence_at = None
    return gps


def test_a_fresh_sentence_is_a_fix():
    gps = _driver([_VALID_GGA + "\r\n"])

    fix = gps.read()

    assert fix is not None
    assert fix.lat == pytest.approx(48.1173, abs=1e-4)


def test_silence_is_not_a_fix(monkeypatch):
    """The whole point. The position is still in hand and still parses —
    it is simply no longer news, and serving it would be the device
    asserting the user is somewhere it has no current evidence for."""
    import indepensense.sensors.gps as gps_module

    gps = _driver([_VALID_GGA + "\r\n"])
    assert gps.read() is not None

    later = gps_module.time.monotonic() + 6.0
    monkeypatch.setattr(gps_module.time, "monotonic", lambda: later)

    assert gps.read() is None


def test_a_sentence_arriving_makes_it_a_fix_again(monkeypatch):
    """A receiver that comes back is believed again at once — the bound
    describes the last sentence, not the health of the device."""
    import indepensense.sensors.gps as gps_module

    gps = _driver([_VALID_GGA + "\r\n"])
    gps.read()

    later = gps_module.time.monotonic() + 6.0
    monkeypatch.setattr(gps_module.time, "monotonic", lambda: later)
    assert gps.read() is None

    gps._ser.lines.append((_VALID_GGA + "\r\n").encode("ascii"))

    assert gps.read() is not None


def test_a_port_that_never_speaks_is_not_a_fix():
    assert _driver().read() is None
