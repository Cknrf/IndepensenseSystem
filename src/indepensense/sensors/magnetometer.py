"""AK8963 magnetometer driver — the compass inside the MPU9250.

The MPU9250 is a package that contains an MPU6500 (accel + gyro) plus
an AK8963 (magnetometer). By default the MPU9250 acts as an I²C master
to the AK8963, which means the AK8963 is NOT directly visible on the
Pi's I²C bus. We enable "bypass mode" on the MPU9250 so the AK8963
appears at address 0x0C, then talk to it directly.

Setup sequence (once at startup):

  1. Wake the MPU9250 by writing 0x00 to PWR_MGMT_1 (register 0x6B).
  2. Set INT_PIN_CFG.BYPASS_EN by writing 0x02 to register 0x37.
     Now the AK8963 answers at 0x0C on the Pi's I²C bus.
  3. Power-cycle the AK8963 through fuse-ROM mode to read the
     factory sensitivity adjustments (ASA registers).
  4. Put the AK8963 into continuous measurement mode 2 with 16-bit
     output (write 0x16 to CNTL1).

Calibration
-----------

A raw magnetometer reading is affected by hard-iron distortions (nearby
ferrous metal, motor magnets, the Pi itself). Without calibration,
headings can be off by tens of degrees. Run the calibration helper
(`magnetometer_calibrate.py`) once per assembled wearable — rotate the
cane through all orientations while it records min/max on each axis —
then paste the resulting offsets into `config.py`.

Coordinate assumption
---------------------

Heading is computed as `atan2(magnetic_y, magnetic_x)`. This assumes
the sensor's X-axis points TOWARD THE FRONT of the cane, with Z-axis
vertical (up). If your physical mount puts a different axis forward,
either rotate the module or apply the correction in `heading_deg`
post-processing.
"""
import math
import time

from indepensense.sensors.base import MagnetometerReading


# --- MPU9250 registers we need to enable bypass -----------------------------
_MPU9250_PWR_MGMT_1 = 0x6B
_MPU9250_INT_PIN_CFG = 0x37
_MPU9250_BYPASS_EN = 0x02   # bit 1 of INT_PIN_CFG

# --- AK8963 registers -------------------------------------------------------
_AK8963_WIA = 0x00           # WHO_AM_I; should read 0x48
_AK8963_ST1 = 0x02           # data ready flag
_AK8963_HXL = 0x03           # X measurement low byte (little-endian, signed 16-bit)
_AK8963_ST2 = 0x09           # must read after HZH to release data registers
_AK8963_CNTL1 = 0x0A         # control register (mode + output resolution)
_AK8963_ASAX = 0x10          # sensitivity adjustment X (readable in fuse-ROM mode only)

# --- AK8963 control values --------------------------------------------------
_AK8963_MODE_POWER_DOWN = 0x00
_AK8963_MODE_FUSE_ROM = 0x0F
# Continuous measurement mode 2 (100 Hz) with 16-bit output (0x10 | 0x06).
_AK8963_MODE_CONT_2_16BIT = 0x16

# --- Physical constants -----------------------------------------------------
# In 16-bit mode, ±4912 μT is mapped to signed int16 (-32760..32760).
# So each raw count is 4912/32760 ≈ 0.15 μT.
_UT_PER_LSB = 4912.0 / 32760.0

_MPU9250_DEFAULT_ADDRESS = 0x68
_AK8963_DEFAULT_ADDRESS = 0x0C


class AK8963Magnetometer:
    """AK8963 magnetometer driver, accessed via MPU9250 bypass mode."""

    def __init__(
        self,
        bus_number: int = 1,
        mpu9250_address: int = _MPU9250_DEFAULT_ADDRESS,
        magnetometer_address: int = _AK8963_DEFAULT_ADDRESS,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        offset_z: float = 0.0,
    ):
        import smbus2

        self._bus = smbus2.SMBus(bus_number)
        self._mpu_addr = mpu9250_address
        self._mag_addr = magnetometer_address
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._offset_z = offset_z

        self._enable_bypass()
        self._sens_adj = self._read_sensitivity_adjustments()
        self._enter_continuous_mode()

    def read(self) -> MagnetometerReading | None:
        try:
            # ST1 bit 0 (DRDY) indicates a new measurement is ready. If not
            # ready we still read (the AK8963 doesn't return stale data — it
            # holds the last valid measurement until a new one lands).
            data = self._bus.read_i2c_block_data(self._mag_addr, _AK8963_HXL, 7)
        except OSError:
            return None

        # data[6] is ST2. Reading it releases the data registers so the
        # next measurement can be latched in. This IS required — omitting
        # it hangs the AK8963 on the next read.
        # ST2 bit 3 (HOFL) = magnetic sensor overflow. If set, discard.
        if data[6] & 0x08:
            return None

        raw_x = _signed_16(data[0], data[1])
        raw_y = _signed_16(data[2], data[3])
        raw_z = _signed_16(data[4], data[5])

        # Apply factory sensitivity adjustment, unit conversion, then
        # user hard-iron calibration offset.
        x_ut = raw_x * _UT_PER_LSB * self._sens_adj[0] - self._offset_x
        y_ut = raw_y * _UT_PER_LSB * self._sens_adj[1] - self._offset_y
        z_ut = raw_z * _UT_PER_LSB * self._sens_adj[2] - self._offset_z

        heading = math.degrees(math.atan2(y_ut, x_ut)) % 360.0

        return MagnetometerReading(
            magnetic_x=x_ut,
            magnetic_y=y_ut,
            magnetic_z=z_ut,
            heading_deg=heading,
            timestamp=time.time(),
        )

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- setup

    def _enable_bypass(self) -> None:
        """Wake the MPU9250 and enable I²C bypass to the AK8963."""
        # Waking up clears the SLEEP bit (bit 6 of PWR_MGMT_1).
        self._bus.write_byte_data(self._mpu_addr, _MPU9250_PWR_MGMT_1, 0x00)
        time.sleep(0.01)
        self._bus.write_byte_data(
            self._mpu_addr, _MPU9250_INT_PIN_CFG, _MPU9250_BYPASS_EN,
        )
        time.sleep(0.01)

    def _read_sensitivity_adjustments(self) -> tuple[float, float, float]:
        """Read the AK8963's factory sensitivity constants from fuse ROM.

        Formula per Asahi Kasei's datasheet: `sens = (asa - 128) * 0.5 / 128 + 1`.
        Simplifies to `(asa + 128) / 256`. Applied per-axis on each read.
        """
        # Fuse ROM access mode
        self._bus.write_byte_data(self._mag_addr, _AK8963_CNTL1, _AK8963_MODE_POWER_DOWN)
        time.sleep(0.01)
        self._bus.write_byte_data(self._mag_addr, _AK8963_CNTL1, _AK8963_MODE_FUSE_ROM)
        time.sleep(0.01)
        asa = self._bus.read_i2c_block_data(self._mag_addr, _AK8963_ASAX, 3)
        # Return to power-down before switching to continuous mode.
        self._bus.write_byte_data(self._mag_addr, _AK8963_CNTL1, _AK8963_MODE_POWER_DOWN)
        time.sleep(0.01)

        adj = tuple((a + 128) / 256.0 for a in asa)
        return (adj[0], adj[1], adj[2])

    def _enter_continuous_mode(self) -> None:
        """Put the AK8963 into 100 Hz continuous 16-bit mode."""
        self._bus.write_byte_data(
            self._mag_addr, _AK8963_CNTL1, _AK8963_MODE_CONT_2_16BIT,
        )
        # The datasheet says wait ~10 ms before the first read.
        time.sleep(0.01)


class MockMagnetometer:
    """Configurable mock for Mac dev + unit tests.

    Constructor takes a heading_deg (0-360). `read()` returns a reading
    with that heading and synthesized field values that mathematically
    match the heading (so `atan2(y, x)` gives the expected value).
    """

    def __init__(self, heading_deg: float = 0.0, magnitude_ut: float = 40.0):
        self._heading_deg = heading_deg % 360.0
        self._magnitude_ut = magnitude_ut
        self.closed = False

    def set_heading(self, heading_deg: float) -> None:
        """Change the mock's reported heading. Useful during tests to
        simulate the user rotating the cane."""
        self._heading_deg = heading_deg % 360.0

    def read(self) -> MagnetometerReading | None:
        # Rebuild the field vector so atan2(y, x) matches the heading.
        rad = math.radians(self._heading_deg)
        x = self._magnitude_ut * math.cos(rad)
        y = self._magnitude_ut * math.sin(rad)
        return MagnetometerReading(
            magnetic_x=x,
            magnetic_y=y,
            magnetic_z=0.0,
            heading_deg=self._heading_deg,
            timestamp=time.time(),
        )

    def close(self) -> None:
        self.closed = True


def _signed_16(low: int, high: int) -> int:
    """Combine two bytes (little-endian) into a signed 16-bit integer."""
    value = low | (high << 8)
    if value >= 0x8000:
        value -= 0x10000
    return value
