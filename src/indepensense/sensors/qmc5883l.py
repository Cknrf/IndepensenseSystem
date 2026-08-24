"""QMC5883L 3-axis magnetometer driver over I²C.

A standalone compass chip (QST Corp), not part of any IMU package. It sits
on its own I²C address and needs no host help to be visible — unlike the
AK8963 this replaces, which was a second die inside the MPU9250 and only
appeared on the bus after the MPU9250's bypass bit was set. The MPU9250
module turned out to be a relabelled MPU6500 with no magnetometer at all,
so heading now comes from this dedicated part.

Beware the naming: modules sold as "HMC5883L" or "GY-271" almost always
carry a QMC5883L instead. They are NOT register-compatible. Honeywell's
HMC5883L answers at `0x1E` with big-endian data at `0x03`; the QMC5883L
answers at `0x0D` with little-endian data at `0x00`. The chip-ID check in
`__init__` exists to catch exactly that mix-up at startup rather than
letting it surface as a heading that never moves.

Register map (QMC5883L datasheet rev 1.0, §1.5)
    0x00  DATA_X_LSB   first byte of a 7-byte block:
                       6 bytes X,Y,Z (little-endian 16-bit signed)
                       + 1 byte STATUS
    0x06  STATUS       bit0 DRDY (new data), bit1 OVL (overflow),
                       bit2 DOR (data skipped — we read slower than the ODR,
                       so this is expected and ignored)
    0x09  CONTROL_1    OSR[7:6] | RNG[5:4] | ODR[3:2] | MODE[1:0]
    0x0A  CONTROL_2    bit7 SOFT_RST, bit6 ROL_PNT, bit0 INT_ENB
    0x0B  SET_RESET    period register; datasheet mandates the value 0x01
    0x0D  CHIP_ID      reads 0xFF on a genuine QMC5883L

Temperature (0x07/0x08) is deliberately not read. Its offset is
uncalibrated per the datasheet — only *changes* are meaningful — and no
consumer wants it. Skipping it keeps the burst read at 7 bytes.

Configuration choice: continuous mode, ±8 G range, 10 Hz ODR, 512×
oversampling (CONTROL_1 = 0x11).

  * ±8 G rather than ±2 G. At ±8 G one count is 0.033 μT, so Earth's
    ~50 μT field still spans ~1500 counts — far finer than the ~1° of
    heading accuracy an uncompensated compass can honestly claim. The
    headroom is what matters: the wearable carries vibration motors and
    a 4S battery pack, and at ±2 G a nearby magnet can push the sensor
    into overflow, which blanks the heading entirely (STATUS.OVL).
  * 10 Hz ODR, the slowest available, because `app.py` samples heading at
    2 Hz. Anything faster would only add power draw and noise.
  * 512× oversampling, the highest available, for the lowest noise floor.
    At 10 Hz there is ample time budget for it.

Calibration
-----------

Raw readings carry two distortions from the wearable itself:

  * Hard-iron — a constant additive bias from permanent magnets and
    ferrous mass (motor magnets, battery pack, Pi). Corrected by
    subtracting a per-axis offset.
  * Soft-iron — a multiplicative distortion that stretches the field
    sphere into an ellipsoid, so the same rotation reads as a different
    number of degrees depending on which way you are facing. Corrected
    by a per-axis scale factor.

Both come from one 30 s rotation sweep:
`python -m indepensense.sensors.tests.manual.magnetometer_calibrate`.
Paste the printed `MAG_OFFSET_*` and `MAG_SCALE_*` into `config.py`. The
calibration is specific to one assembled wearable — re-run it whenever
the physical layout changes.

Coordinate assumption
---------------------

Heading is `atan2(y, x)`, which assumes the sensor's X-axis points toward
the FRONT of the cane with Z vertical. See `heading_from_field` in
`sensors/base.py` for the convention. No tilt compensation and no
magnetic declination: this is magnetic north, and it degrades when the
cane is held well off-vertical.
"""
import time

from indepensense.sensors.base import MagnetometerReading, heading_from_field

QMC5883L_DEFAULT_ADDRESS = 0x0D

_DATA_X_LSB = 0x00
_CONTROL_1 = 0x09
_CONTROL_2 = 0x0A
_SET_RESET_PERIOD = 0x0B
_CHIP_ID = 0x0D

_DATA_BLOCK_LENGTH = 7          # 6 data bytes + STATUS

# STATUS bits.
_STATUS_OVL = 0x02              # any axis saturated — the sample is garbage

# CONTROL_2 values.
_CTRL2_SOFT_RST = 0x80
# ROL_PNT rolls the register pointer back to 0x00 after 0x06, which is what
# makes a 7-byte burst read repeatable. Bit 0 (INT_ENB) is left clear; the
# DRDY pin is not wired on this build, so its state is inert.
_CTRL2_ROL_PNT = 0x40

# SET_RESET period. The datasheet gives no meaning for this register beyond
# "recommended value 0x01" — it is the internal degauss cadence, and the part
# misbehaves if it is left at reset.
_SET_RESET_VALUE = 0x01

# CONTROL_1: OSR 512 (0b00 << 6) | RNG ±8 G (0b01 << 4) | ODR 10 Hz
# (0b00 << 2) | MODE continuous (0b01). See the module docstring for why.
_CTRL1_CONTINUOUS_8G_10HZ_OSR512 = 0x11

_EXPECTED_CHIP_ID = 0xFF

# Sensitivity at ±8 G is 3000 LSB/Gauss (datasheet §1.4). 1 Gauss = 100 μT,
# so one count is 100/3000 μT.
_UT_PER_LSB = 100.0 / 3000.0


def _signed_16(low: int, high: int) -> int:
    """Combine two bytes (little-endian) into a signed 16-bit integer."""
    value = low | (high << 8)
    return value - 65536 if value >= 32768 else value


def parse_qmc5883l_block(raw: bytes) -> tuple[float, float, float] | None:
    """Parse the 7-byte block starting at DATA_X_LSB.

    Returns uncalibrated field strength as (x_ut, y_ut, z_ut) in microtesla,
    or None when STATUS.OVL is set — an overflowed sample carries no usable
    direction, so it must be discarded rather than clamped.

    DRDY is not checked. We poll at 2 Hz against a 10 Hz ODR, so a fresh
    sample is always waiting; the flag would only tell us something is wrong
    with the chip, which the read failing already tells us.
    """
    if len(raw) != _DATA_BLOCK_LENGTH:
        raise ValueError(f"expected {_DATA_BLOCK_LENGTH} bytes, got {len(raw)}")

    if raw[6] & _STATUS_OVL:
        return None

    x = _signed_16(raw[0], raw[1]) * _UT_PER_LSB
    y = _signed_16(raw[2], raw[3]) * _UT_PER_LSB
    z = _signed_16(raw[4], raw[5]) * _UT_PER_LSB
    return x, y, z


def apply_calibration(
    value_ut: float, offset_ut: float, scale: float,
) -> float:
    """Correct one axis: subtract the hard-iron bias, then apply soft-iron scale.

    Order matters. The scale factor describes how much that axis' *span* is
    stretched around its centre, so the centre has to be removed first —
    scaling before offsetting would move the centre by the scale factor too.
    """
    return (value_ut - offset_ut) * scale


class QMC5883L:
    """QMC5883L magnetometer driver."""

    def __init__(
        self,
        bus_number: int = 1,
        address: int = QMC5883L_DEFAULT_ADDRESS,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
        offset_z: float = 0.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        scale_z: float = 1.0,
    ):
        from smbus2 import SMBus  # lazy: only resolvable on the Pi

        self._bus = SMBus(bus_number)
        self._address = address
        self._offsets = (offset_x, offset_y, offset_z)
        self._scales = (scale_x, scale_y, scale_z)

        self._reset()
        self._verify_chip_id()
        self._configure()

    def read(self) -> MagnetometerReading | None:
        try:
            raw = self._bus.read_i2c_block_data(
                self._address, _DATA_X_LSB, _DATA_BLOCK_LENGTH
            )
        except OSError:
            return None

        parsed = parse_qmc5883l_block(bytes(raw))
        if parsed is None:
            return None

        x, y, z = (
            apply_calibration(v, off, sc)
            for v, off, sc in zip(parsed, self._offsets, self._scales)
        )

        return MagnetometerReading(
            magnetic_x=x,
            magnetic_y=y,
            magnetic_z=z,
            heading_deg=heading_from_field(x, y),
            timestamp=time.time(),
        )

    def close(self) -> None:
        # Drop to standby (MODE=00) so the chip stops sampling. Best-effort:
        # if the bus is already gone there is nothing to save.
        try:
            self._bus.write_byte_data(self._address, _CONTROL_1, 0x00)
        except OSError:
            pass
        try:
            self._bus.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- setup

    def _reset(self) -> None:
        """Soft-reset the chip so construction always starts from a known state.

        Without this, re-running a manual test would inherit whatever
        configuration the previous run left behind.
        """
        self._bus.write_byte_data(self._address, _CONTROL_2, _CTRL2_SOFT_RST)
        time.sleep(0.01)

    def _verify_chip_id(self) -> None:
        """Fail loudly if the part at this address is not a QMC5883L.

        This is the check that would have caught the fake MPU9250 on day one.
        `app.py` treats a magnetometer that fails to open as "no compass" and
        keeps running, so raising here costs nothing but a printed reason.
        """
        chip_id = self._bus.read_byte_data(self._address, _CHIP_ID)
        if chip_id != _EXPECTED_CHIP_ID:
            raise RuntimeError(
                f"chip ID at 0x{self._address:02X} is 0x{chip_id:02X}, "
                f"expected 0x{_EXPECTED_CHIP_ID:02X} — this is not a QMC5883L. "
                f"A Honeywell HMC5883L lives at 0x1E and is not register-"
                f"compatible; an AK8963 lives at 0x0C."
            )

    def _configure(self) -> None:
        """Set the degauss period, enable pointer roll-over, start sampling."""
        self._bus.write_byte_data(
            self._address, _SET_RESET_PERIOD, _SET_RESET_VALUE
        )
        self._bus.write_byte_data(self._address, _CONTROL_2, _CTRL2_ROL_PNT)
        self._bus.write_byte_data(
            self._address, _CONTROL_1, _CTRL1_CONTINUOUS_8G_10HZ_OSR512
        )
        # One ODR period (100 ms at 10 Hz) so the first read has real data.
        time.sleep(0.1)
