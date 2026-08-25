"""Unit tests for the QMC5883P driver's pure logic.

No hardware and no smbus2 — everything here exercises
`parse_qmc5883p_block` and `apply_calibration`, which is where all the
protocol knowledge that can be wrong actually lives: little-endian byte
order, two's complement, the ±8 G scale factor, the overflow bit, and the
order in which offset and scale are applied.

Byte-order arithmetic used below. At ±8 G one count is 100/3750 μT, so
3750 counts = 100 μT exactly. 3750 = 0x0EA6, and the QMC5883P is
LITTLE-endian, so that is low=0xA6, high=0x0E — the reverse of the
MPU6050's layout. Getting this backwards is the single most likely
transcription error in the driver, hence the explicit test.

Note the scale factor differs from the QMC5883L this replaced: 3750
LSB/Gauss instead of 3000, at the same ±8 G range. A driver ported
between the two parts without changing that constant reads 25% high.
"""
import pytest

from indepensense.sensors.qmc5883p import apply_calibration, parse_qmc5883p_block

_DRDY = 0x01        # status: new data ready
_OVFL = 0x02        # status: an axis exceeded ±30000 LSB


def _block(x: int = 0, y: int = 0, z: int = 0) -> bytes:
    """Build the 6-byte data block from signed counts, LSB first per axis."""
    out = bytearray()
    for value in (x, y, z):
        raw = value & 0xFFFF
        out.append(raw & 0xFF)          # LSB first
        out.append((raw >> 8) & 0xFF)
    return bytes(out)


def test_parses_100_ut_on_x():
    x, y, z = parse_qmc5883p_block(_block(x=3750), _DRDY)
    assert x == pytest.approx(100.0)
    assert y == 0.0
    assert z == 0.0


def test_parses_negative_field_as_twos_complement():
    x, _y, _z = parse_qmc5883p_block(_block(x=-3750), _DRDY)
    assert x == pytest.approx(-100.0)


def test_byte_order_is_little_endian():
    """low=0xA6 high=0x0E is +3750. Read big-endian it would be 0xA60E
    (a large negative number), so this test fails loudly on a byte swap."""
    raw = bytes([0xA6, 0x0E, 0x00, 0x00, 0x00, 0x00])
    x, _y, _z = parse_qmc5883p_block(raw, _DRDY)
    assert x == pytest.approx(100.0)


def test_axes_are_not_transposed():
    x, y, z = parse_qmc5883p_block(_block(x=3750, y=7500, z=-3750), _DRDY)
    assert x == pytest.approx(100.0)
    assert y == pytest.approx(200.0)
    assert z == pytest.approx(-100.0)


def test_earth_field_magnitude_is_plausible():
    """A sanity check on the scale factor itself: Earth's field is 25-65 μT.
    At ±8 G and 3750 LSB/G that is ~940-2440 counts. Carrying over the
    QMC5883L's 3000 LSB/G constant would put this 25% out."""
    x, _y, _z = parse_qmc5883p_block(_block(x=1875), _DRDY)
    assert x == pytest.approx(50.0)
    assert 25.0 < x < 65.0


def test_overflow_bit_discards_the_sample():
    """STATUS.OVFL (bit 1) means an axis passed ±30000 LSB — direction is
    meaningless, so the frame must be dropped rather than reported."""
    assert parse_qmc5883p_block(_block(x=3750), _OVFL | _DRDY) is None


def test_overflow_is_checked_on_the_status_register_not_the_data():
    """The P keeps status in its own register (0x09), unlike the L which
    appended it to the data block. A port that kept reading status out of
    the data bytes would never see an overflow."""
    assert parse_qmc5883p_block(_block(x=3750), _OVFL) is None
    assert parse_qmc5883p_block(_block(x=3750), 0x00) is not None


def test_stale_data_is_still_returned_when_drdy_is_clear():
    """DRDY self-clears on read, and the data registers hold the last
    measurement until a new one lands. Requiring DRDY would drop good
    samples at our 2 Hz poll rate."""
    result = parse_qmc5883p_block(_block(x=3750), 0x00)
    assert result is not None
    assert result[0] == pytest.approx(100.0)


def test_rejects_short_block():
    with pytest.raises(ValueError):
        parse_qmc5883p_block(bytes(5), _DRDY)


def test_rejects_seven_byte_block():
    """Guards against a copy-paste from the QMC5883L driver, whose block was
    7 bytes because status was appended to it."""
    with pytest.raises(ValueError):
        parse_qmc5883p_block(bytes(7), _DRDY)


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
