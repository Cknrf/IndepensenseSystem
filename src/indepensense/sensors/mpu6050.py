"""MPU6050 6-axis IMU driver over I²C.

Register map (datasheet §3, §4):
    0x1C  ACCEL_CONFIG   bits 4:3 select accel full-scale range (default ±2 g)
    0x1B  GYRO_CONFIG    bits 4:3 select gyro full-scale range (default ±250 °/s)
    0x3B  ACCEL_XOUT_H   first byte of a 14-byte block:
                         6 bytes accel (X,Y,Z), 2 bytes temp, 6 bytes gyro
    0x6B  PWR_MGMT_1     bit 6 = SLEEP. Reset value is 0x40 (asleep), so the
                         device must be woken before any read.

All measurement registers are big-endian 16-bit signed (two's complement).
"""
import time

from indepensense.sensors.base import IMUReading

MPU6050_DEFAULT_ADDRESS = 0x68

_PWR_MGMT_1 = 0x6B
_ACCEL_XOUT_H = 0x3B
_DATA_BLOCK_LENGTH = 14

# Default full-scale sensitivities (LSB per unit) — see datasheet §6.2.
_ACCEL_SENSITIVITY = 16384.0   # LSB / g    at AFS_SEL=0 (±2 g)
_GYRO_SENSITIVITY = 131.0      # LSB / dps  at FS_SEL=0  (±250 °/s)


def _signed_16(high: int, low: int) -> int:
    value = (high << 8) | low
    return value - 65536 if value >= 32768 else value


def parse_mpu6050_block(raw: bytes) -> tuple[float, float, float, float, float, float, float]:
    """Parse the 14-byte data block starting at ACCEL_XOUT_H.

    Returns (accel_x_g, accel_y_g, accel_z_g, temp_c, gyro_x_dps, gyro_y_dps, gyro_z_dps).
    """
    if len(raw) != _DATA_BLOCK_LENGTH:
        raise ValueError(f"expected {_DATA_BLOCK_LENGTH} bytes, got {len(raw)}")

    ax = _signed_16(raw[0], raw[1]) / _ACCEL_SENSITIVITY
    ay = _signed_16(raw[2], raw[3]) / _ACCEL_SENSITIVITY
    az = _signed_16(raw[4], raw[5]) / _ACCEL_SENSITIVITY
    temp_c = _signed_16(raw[6], raw[7]) / 340.0 + 36.53  # datasheet §4.18
    gx = _signed_16(raw[8], raw[9]) / _GYRO_SENSITIVITY
    gy = _signed_16(raw[10], raw[11]) / _GYRO_SENSITIVITY
    gz = _signed_16(raw[12], raw[13]) / _GYRO_SENSITIVITY
    return ax, ay, az, temp_c, gx, gy, gz


class MPU6050:
    def __init__(self, bus_number: int = 1, address: int = MPU6050_DEFAULT_ADDRESS):
        from smbus2 import SMBus  # lazy: only resolvable on the Pi

        self._bus = SMBus(bus_number)
        self._address = address
        # Clear the SLEEP bit so the device starts sampling.
        self._bus.write_byte_data(self._address, _PWR_MGMT_1, 0x00)
        time.sleep(0.1)

    def read(self) -> IMUReading | None:
        try:
            raw = self._bus.read_i2c_block_data(
                self._address, _ACCEL_XOUT_H, _DATA_BLOCK_LENGTH
            )
        except OSError:
            return None
        ax, ay, az, temp_c, gx, gy, gz = parse_mpu6050_block(bytes(raw))
        return IMUReading(
            accel_x=ax,
            accel_y=ay,
            accel_z=az,
            gyro_x=gx,
            gyro_y=gy,
            gyro_z=gz,
            temperature_c=temp_c,
            timestamp=time.time(),
        )

    def close(self) -> None:
        self._bus.close()
