import pytest

from indepensense.sensors.mpu6050 import parse_mpu6050_block


def test_parses_at_rest_with_gravity_on_z():
    # accel_z = +1 g -> 16384 LSB = 0x4000 (high=0x40, low=0x00)
    # temp raw 0 -> 36.53 °C
    raw = bytes([
        0x00, 0x00,   # ax
        0x00, 0x00,   # ay
        0x40, 0x00,   # az = +1 g
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
    # ax = -1 g -> -16384 = 0xC000 two's complement
    raw = bytes([0xC0, 0x00] + [0x00] * 12)
    ax, *_ = parse_mpu6050_block(raw)
    assert ax == pytest.approx(-1.0)


def test_parses_gyro_one_dps():
    # gx = 131 LSB = +1 °/s, located at bytes 8-9
    raw = bytes([0x00] * 8 + [0x00, 0x83] + [0x00] * 4)
    *_, gx, _gy, _gz = parse_mpu6050_block(raw)
    assert gx == pytest.approx(1.0)


def test_rejects_short_frame():
    with pytest.raises(ValueError):
        parse_mpu6050_block(bytes(13))
