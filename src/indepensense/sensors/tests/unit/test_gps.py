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
