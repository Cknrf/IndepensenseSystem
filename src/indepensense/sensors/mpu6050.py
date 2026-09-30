"""MPU6050 6-axis IMU driver over I²C.

Register map (datasheet §3, §4):
    0x1C  ACCEL_CONFIG   bits 4:3 select accel full-scale range
    0x1B  GYRO_CONFIG    bits 4:3 select gyro full-scale range (default ±250 °/s)
    0x3B  ACCEL_XOUT_H   first byte of a 14-byte block:
                         6 bytes accel (X,Y,Z), 2 bytes temp, 6 bytes gyro
    0x6B  PWR_MGMT_1     bit 6 = SLEEP. Reset value is 0x40 (asleep), so the
                         device must be woken before any read.

All measurement registers are big-endian 16-bit signed (two's complement).

Accel range configured to ±8 g (AFS_SEL=2). The chip default is ±2 g, but fall
impacts routinely peak above 2 g and clip at that range. ±8 g captures accurate
peak amplitudes; the resulting resolution (~0.244 mg / LSB) is still finer than
the thresholds our fall-detection algorithm uses.
"""
import sys
import time

from indepensense.sensors.base import IMUReading

MPU6050_DEFAULT_ADDRESS = 0x68

_PWR_MGMT_1 = 0x6B
_ACCEL_CONFIG = 0x1C
_ACCEL_XOUT_H = 0x3B
_DATA_BLOCK_LENGTH = 14

# Accel full-scale range selection. AFS_SEL lives in bits 4:3 of ACCEL_CONFIG.
_ACCEL_CONFIG_8G = 0x10        # AFS_SEL = 0b10 -> ±8 g

# Full-scale sensitivities (LSB per unit) — datasheet §6.2.
_ACCEL_SENSITIVITY = 4096.0    # LSB / g    at AFS_SEL=2 (±8 g)
_GYRO_SENSITIVITY = 131.0      # LSB / dps  at FS_SEL=0  (±250 °/s)


# Minimum gap between wake-sequence retries after an all-zero block.
# Long enough that a genuinely disconnected sensor does not spam the bus
# or the journal at the loop's 100 Hz, short enough that a chip which
# browned out recovers within a stride or two of walking.
_REVIVE_INTERVAL_S = 1.0


def is_dead_block(raw) -> bool:
    """True when every byte is zero, which no live MPU6050 ever returns.

    Not a real reading, and specifically not zero acceleration. The
    temperature register is the tell: 0x0000 decodes to exactly 36.53 °C
    and the die is never exactly at its zero point, so an all-zero block
    means the chip is asleep, held in reset, or not driving the bus.

    This matters far more than a normal bad read. `|a| = 0.00 g` sits
    below `FALL_FREEFALL_THRESHOLD_G`, so a sensor that has quietly
    reset does not merely stop detecting falls — it reports **continuous
    freefall**, and a single spike of bus noise afterwards completes the
    pattern. Observed on the assembled vest: the chip reset mid-session
    and streamed zeros until the process was restarted.

    Treated as a failed read rather than raising: `IMUSensor.read`
    already returns `None` for an unreadable sensor, and every caller
    handles that.
    """
    return not any(raw)


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
        self._last_revive_s = 0.0
        # Clear the SLEEP bit so the device starts sampling.
        self._bus.write_byte_data(self._address, _PWR_MGMT_1, 0x00)
        # Widen accel range to ±8 g for fall-detection headroom.
        self._bus.write_byte_data(self._address, _ACCEL_CONFIG, _ACCEL_CONFIG_8G)
        time.sleep(0.1)

    def read(self) -> IMUReading | None:
        try:
            raw = self._bus.read_i2c_block_data(
                self._address, _ACCEL_XOUT_H, _DATA_BLOCK_LENGTH
            )
        except OSError:
            return None

        if is_dead_block(raw):
            self._revive()
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

    def _revive(self) -> None:
        """Re-run the wake sequence after an all-zero block.

        The chip resetting is the whole reason this happens, and a reset
        chip is asleep with its configuration back at defaults. Rewriting
        both registers is what actually restores it; without this the
        device reads zeros until the process restarts, which is what was
        observed on the vest.

        Rate-limited because the failure can be a loose connection rather
        than a reset, and hammering the bus at 100 Hz would not fix that
        while making the log unreadable. Failures here are swallowed: the
        caller already has its `None`, and the next read retries anyway.
        """
        now = time.monotonic()
        if now - self._last_revive_s < _REVIVE_INTERVAL_S:
            return
        self._last_revive_s = now
        print(
            "[mpu6050] all-zero block — sensor asleep or reset. "
            "Re-running wake sequence.",
            file=sys.stderr,
        )
        try:
            self._bus.write_byte_data(self._address, _PWR_MGMT_1, 0x00)
            self._bus.write_byte_data(self._address, _ACCEL_CONFIG, _ACCEL_CONFIG_8G)
        except OSError as exc:
            print(f"[mpu6050] revive failed: {exc}", file=sys.stderr)

    def close(self) -> None:
        self._bus.close()
