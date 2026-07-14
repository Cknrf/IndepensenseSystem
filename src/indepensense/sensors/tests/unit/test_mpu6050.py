import pytest

from indepensense.sensors.mpu6050 import parse_mpu6050_block


# At ±8 g range: 1 g = 4096 LSB.
# 1 g  -> 0x1000 -> high=0x10, low=0x00
# -1 g -> 0xF000 (two's complement) -> high=0xF0, low=0x00
# 4 g  -> 0x4000 -> high=0x40, low=0x00


def test_parses_at_rest_with_gravity_on_z():
    # accel_z = +1 g -> 4096 LSB = 0x1000
    raw = bytes([
        0x00, 0x00,   # ax
        0x00, 0x00,   # ay
        0x10, 0x00,   # az = +1 g at ±8 g range
        0x00, 0x00,   # temp
        0x00, 0x00,   # gx
        0x00, 0x00,   # gy
        0x00, 0x00,   # gz
    ])
    ax, ay, az, temp_c, gx, gy, gz = parse_mpu6050_block(raw)
    assert ax == 0.0
    assert ay == 0.0
    assert az == pytest.approx(1.0)
    assert temp_c == pytest.approx(36.53)
    assert gx == 0.0
    assert gy == 0.0
    assert gz == 0.0


def test_parses_negative_acceleration():
    # ax = -1 g -> -4096 = 0xF000 two's complement
    raw = bytes([0xF0, 0x00] + [0x00] * 12)
    ax, *_ = parse_mpu6050_block(raw)
    assert ax == pytest.approx(-1.0)


def test_parses_high_magnitude_impact_without_clipping():
    # At the old ±2 g range this would have clipped. At ±8 g we get a real number.
    # 4 g on accel_z -> 4 * 4096 = 16384 = 0x4000 -> high=0x40, low=0x00
    raw = bytes([0x00] * 4 + [0x40, 0x00] + [0x00] * 8)
    _ax, _ay, az, *_ = parse_mpu6050_block(raw)
    assert az == pytest.approx(4.0)


def test_parses_gyro_one_dps():
    # gx = 131 LSB = +1 °/s, located at bytes 8-9. Gyro range unaffected by
    # widening the accel range.
    raw = bytes([0x00] * 8 + [0x00, 0x83] + [0x00] * 4)
    *_, gx, _gy, _gz = parse_mpu6050_block(raw)
    assert gx == pytest.approx(1.0)


def test_rejects_short_frame():
    with pytest.raises(ValueError):
        parse_mpu6050_block(bytes(13))
