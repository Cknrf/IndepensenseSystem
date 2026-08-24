"""Unit tests for the QMC5883L driver's pure logic.

No hardware and no smbus2 — everything here exercises
`parse_qmc5883l_block` and `apply_calibration`, which is where all the
protocol knowledge that can be wrong actually lives: little-endian byte
order, two's complement, the ±8 G scale factor, the overflow bit, and the
order in which offset and scale are applied.

Byte-order arithmetic used below. At ±8 G one count is 100/3000 μT, so
3000 counts = 100 μT exactly. 3000 = 0x0BB8, and the QMC5883L is
LITTLE-endian, so that is low=0xB8, high=0x0B — the reverse of the
MPU6050's layout. Getting this backwards is the single most likely
transcription error in the driver, hence the explicit test.
"""
import pytest

from indepensense.sensors.qmc5883l import apply_calibration, parse_qmc5883l_block


def _block(x: int = 0, y: int = 0, z: int = 0, status: int = 0x01) -> bytes:
    """Build a 7-byte register block from signed counts. Status defaults to DRDY."""
    out = bytearray()
    for value in (x, y, z):
        raw = value & 0xFFFF
        out.append(raw & 0xFF)          # LSB first
        out.append((raw >> 8) & 0xFF)
    out.append(status)
    return bytes(out)


def test_parses_100_ut_on_x():
    x, y, z = parse_qmc5883l_block(_block(x=3000))
    assert x == pytest.approx(100.0)
    assert y == 0.0
    assert z == 0.0


def test_parses_negative_field_as_twos_complement():
    x, _y, _z = parse_qmc5883l_block(_block(x=-3000))
    assert x == pytest.approx(-100.0)


def test_byte_order_is_little_endian():
    """low=0xB8 high=0x0B is +3000. Read big-endian it would be 0xB80B
    (a large negative number), so this test fails loudly on a byte swap."""
    raw = bytes([0xB8, 0x0B, 0x00, 0x00, 0x00, 0x00, 0x01])
    x, _y, _z = parse_qmc5883l_block(raw)
    assert x == pytest.approx(100.0)


def test_axes_are_not_transposed():
    x, y, z = parse_qmc5883l_block(_block(x=3000, y=6000, z=-3000))
    assert x == pytest.approx(100.0)
    assert y == pytest.approx(200.0)
    assert z == pytest.approx(-100.0)


def test_earth_field_magnitude_is_plausible():
    """A sanity check on the scale factor itself: Earth's field is 25-65 μT,
    which at ±8 G should land around 1500 counts. If the range or the
    LSB constant is wrong this comes out 4x off (the ±2 G value) or worse."""
    x, _y, _z = parse_qmc5883l_block(_block(x=1500))
    assert 25.0 < x < 65.0


def test_overflow_bit_discards_the_sample():
    """STATUS.OVL (bit 1) means an axis saturated — direction is meaningless,
    so the frame must be dropped rather than reported."""
    assert parse_qmc5883l_block(_block(x=3000, status=0x03)) is None


def test_data_skipped_bit_is_tolerated():
    """STATUS.DOR (bit 2) is set whenever we read slower than the ODR, which
    is always true at 2 Hz against 10 Hz. It must not discard the sample."""
    result = parse_qmc5883l_block(_block(x=3000, status=0x05))
    assert result is not None
    assert result[0] == pytest.approx(100.0)


def test_rejects_short_block():
    with pytest.raises(ValueError):
        parse_qmc5883l_block(bytes(6))


def test_calibration_is_identity_by_default():
    assert apply_calibration(42.0, offset_ut=0.0, scale=1.0) == pytest.approx(42.0)


def test_calibration_subtracts_hard_iron_offset():
    assert apply_calibration(50.0, offset_ut=20.0, scale=1.0) == pytest.approx(30.0)


def test_calibration_applies_scale_after_offset():
    """Offset first, then scale. Scaling first would give (50*2)-20 = 80;
    the correct order gives (50-20)*2 = 60. This ordering is what keeps a
    soft-iron correction from re-introducing a hard-iron bias."""
    assert apply_calibration(50.0, offset_ut=20.0, scale=2.0) == pytest.approx(60.0)


def test_calibration_recentres_a_biased_axis():
    """An axis biased by +20 μT swinging between +10 and +30 should come out
    symmetric around zero once the offset is applied."""
    assert apply_calibration(10.0, offset_ut=20.0, scale=1.0) == pytest.approx(-10.0)
    assert apply_calibration(30.0, offset_ut=20.0, scale=1.0) == pytest.approx(10.0)
