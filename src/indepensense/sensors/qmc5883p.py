"""QMC5883P 3-axis magnetometer driver over I²C.

A standalone compass chip (QST Corp), independent of the IMU — it shares
only the SDA/SCL wires and needs no host-side setup to appear on the bus.

Beware the family naming, which has now bitten this project twice. The
part fitted to boards sold as "QMC5883L", "HMC5883L", "GY-271" or
"GY-273" is whatever QST is shipping that month, and the three candidates
are mutually incompatible:

    Part        Addr   Chip ID          Data      Status
    QMC5883P    0x2C   0x00 -> 0x80     0x01-0x06  0x09
    QMC5883L    0x0D   0x0D -> 0xFF     0x00-0x05  0x06
    HMC5883L    0x1E   0x0A -> 'H48'    0x03-0x08  0x09

This driver is for the **P**. Confirm with `i2cdetect -y 1` before
assuming: the address alone identifies the part.

Register map (QMC5883P datasheet Rev C, §9)
    0x00  CHIPID       reads 0x80
    0x01  XOUT_LSB     first byte of a 6-byte block: X,Y,Z as
                       little-endian 16-bit two's complement
    0x09  STATUS       bit1 OVFL (any axis beyond ±30000 LSB),
                       bit0 DRDY (new data). Both clear on read.
    0x0A  CONTROL_1    OSR2[7:6] | OSR1[5:4] | ODR[3:2] | MODE[1:0]
    0x0B  CONTROL_2    SOFT_RST[7] | SELF_TEST[6] | -- | RNG[3:2]
                       | SET/RESET_MODE[1:0]
    0x29  (undocumented) axis sign definition — see `_configure`

There is no temperature register on this part (the QMC5883L had one).
Nothing consumed it anyway.

Configuration choice: normal mode, ±8 G, 10 Hz ODR, OSR1=8, OSR2=1
(CONTROL_1 = 0x01, CONTROL_2 = 0x08).

  * **Normal mode, not continuous.** Both sample periodically; continuous
    never sleeps, which is how the part reaches its 1500 Hz maximum ODR
    at 2200 μA. Normal mode at 10 Hz draws 78 μA — a ~28× saving on a
    battery-powered wearable, for a compass that `app.py` reads twice a
    second.
  * **±8 G rather than ±2 G.** At ±8 G one count is 0.027 μT (3750 LSB/G),
    so Earth's ~50 μT field still spans ~1900 counts — far finer than the
    1-2° heading accuracy this part is specified for. The headroom is
    what matters: the wearable carries vibration motors and a 4S battery
    pack, and at ±2 G a nearby magnet saturates the sensor, which sets
    OVFL and blanks the heading. ±12 G and ±30 G exist but spend
    resolution on field strengths nothing on a white cane produces.
  * **OSR1=8 but OSR2=1.** OSR1 is an oversampling ratio — it averages
    within a measurement, costing power but not freshness, so we take
    the maximum for the lowest noise floor. OSR2 is a *down-sampling*
    rate, and at its maximum of 8 it divides the 10 Hz output down to
    ~1.25 Hz. That was measured on the bench: consecutive reads returned
    byte-identical values because the chip had nothing new, leaving the
    heading up to 800 ms stale and starving the calibration sweep of
    distinct samples. OSR2=1 restores a true 10 Hz. The datasheet's §7.1
    example uses OSR2=8, which is fine for its 200 Hz ODR and wrong for
    ours.
  * **SET/RESET mode = set and reset on.** The other options skip the
    internal degauss cycle, which is what removes the sensor's own offset
    drift between samples. Skipping it saves power we don't need to save.

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

QMC5883P_DEFAULT_ADDRESS = 0x2C

_CHIP_ID = 0x00
_XOUT_LSB = 0x01
_STATUS = 0x09
_CONTROL_1 = 0x0A
_CONTROL_2 = 0x0B
_AXIS_SIGN = 0x29

_DATA_BLOCK_LENGTH = 6          # X, Y, Z — status lives in its own register

_EXPECTED_CHIP_ID = 0x80

# STATUS bits.
_STATUS_OVFL = 0x02             # an axis exceeded ±30000 LSB — sample unusable

# CONTROL_2: SOFT_RST[7] | SELF_TEST[6] | -- | RNG[3:2] | SET/RESET[1:0].
_CTRL2_SOFT_RST = 0x80
# RNG=0b10 (±8 G) | SET/RESET=0b00 (set and reset on).
_CTRL2_8G_SET_RESET_ON = 0x08

# CONTROL_1: OSR2=0b00 (down-sample 1) | OSR1=0b00 (oversample 8)
# | ODR=0b00 (10 Hz) | MODE=0b01 (normal). See the module docstring.
_CTRL1_NORMAL_10HZ_OVERSAMPLE_8 = 0x01

# Register 0x29 does not appear in the datasheet's register map (§9.1), but
# every setup example in §7 opens by writing 0x06 to it, described only as
# "define the sign for X Y and Z axis". Undocumented and unexplained, yet
# omitting it is a known cause of axes reading inverted or stuck. Written
# blind, exactly as the vendor specifies.
_AXIS_SIGN_VALUE = 0x06

# How many times to re-write the control-register pair before giving up. Two
# passes is what the bench needed; five leaves margin without hanging startup.
_CONFIG_ATTEMPTS = 5

# Sensitivity at ±8 G is 3750 LSB/Gauss (datasheet §2.1). 1 Gauss = 100 μT,
# so one count is 100/3750 μT.
_UT_PER_LSB = 100.0 / 3750.0


def _signed_16(low: int, high: int) -> int:
    """Combine two bytes (little-endian) into a signed 16-bit integer."""
    value = low | (high << 8)
    return value - 65536 if value >= 32768 else value


def parse_qmc5883p_block(raw: bytes, status: int) -> tuple[float, float, float] | None:
    """Parse the 6-byte data block at XOUT_LSB against the STATUS byte.

    Returns uncalibrated field strength as (x_ut, y_ut, z_ut) in microtesla,
    or None when STATUS.OVFL is set — an overflowed sample carries no usable
    direction, so it must be discarded rather than clamped.

    STATUS.DRDY is not checked. We poll at 2 Hz against a 10 Hz ODR, and the
    data registers hold the last measurement until a new one replaces it
    (datasheet §9.2.1), so there is always a recent sample to read. Requiring
    DRDY would also fight the fact that the bit self-clears on read.
    """
    if len(raw) != _DATA_BLOCK_LENGTH:
        raise ValueError(f"expected {_DATA_BLOCK_LENGTH} bytes, got {len(raw)}")

    if status & _STATUS_OVFL:
        return None

    x = _signed_16(raw[0], raw[1]) * _UT_PER_LSB
    y = _signed_16(raw[2], raw[3]) * _UT_PER_LSB
    z = _signed_16(raw[4], raw[5]) * _UT_PER_LSB
    return x, y, z


def apply_calibration(value_ut: float, offset_ut: float, scale: float) -> float:
    """Correct one axis: subtract the hard-iron bias, then apply soft-iron scale.

    Order matters. The scale factor describes how much that axis' *span* is
    stretched around its centre, so the centre has to be removed first —
    scaling before offsetting would move the centre by the scale factor too.
    """
    return (value_ut - offset_ut) * scale


class QMC5883P:
    """QMC5883P magnetometer driver."""

    def __init__(
        self,
        bus_number: int = 1,
        address: int = QMC5883P_DEFAULT_ADDRESS,
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

        # Failure tallies, split by cause because they mean opposite things.
        # `read()` returns None either way — the Magnetometer protocol has no
        # channel for a reason — but a bring-up test needs to tell them apart:
        # bus errors point at wiring (loose jumper, marginal pull-ups), while
        # overflows point at a magnet close enough to saturate ±8 G, i.e. a
        # mounting problem. Plain public ints; nothing acts on them.
        self.bus_errors = 0
        self.overflows = 0

        self._reset()
        self._verify_chip_id()
        self._configure()
        self._verify_configuration()

    def read(self) -> MagnetometerReading | None:
        # Datasheet §7.5 measurement sequence: status first, then data.
        try:
            status = self._bus.read_byte_data(self._address, _STATUS)
            raw = self._bus.read_i2c_block_data(
                self._address, _XOUT_LSB, _DATA_BLOCK_LENGTH
            )
        except OSError:
            self.bus_errors += 1
            return None

        parsed = parse_qmc5883p_block(bytes(raw), status)
        if parsed is None:
            self.overflows += 1
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
        # Back to suspend mode (MODE=00) so the chip stops sampling and drops
        # to 22 μA. Best-effort: if the bus is already gone, nothing to save.
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

        Restores every register to its default and lands in suspend mode
        (datasheet §7.6, §6.2.4). Without this, re-running a manual test would
        inherit whatever configuration the previous run left behind.

        The datasheet gives no reset duration, so the 50 ms wait is empirical
        and deliberately generous. It matters: a reset still in flight when
        `_configure` writes CONTROL_2 silently reverts the field range to its
        ±30 G default while the later CONTROL_1 write survives, which yields
        correct-looking headings scaled 3.75× too small. `_verify_configuration`
        is what catches that if this wait ever proves too short again.
        """
        self._bus.write_byte_data(self._address, _CONTROL_2, _CTRL2_SOFT_RST)
        time.sleep(0.05)

    def _verify_chip_id(self) -> None:
        """Fail loudly if the part at this address is not a QMC5883P.

        This project has already been burned twice by mislabelled magnetometer
        hardware — a counterfeit MPU9250 with no compass die, then a board sold
        as a QMC5883L that was really this part. `app.py` treats a magnetometer
        that fails to open as "no compass" and keeps running, so raising here
        costs nothing but a printed reason.
        """
        chip_id = self._bus.read_byte_data(self._address, _CHIP_ID)
        if chip_id != _EXPECTED_CHIP_ID:
            raise RuntimeError(
                f"chip ID at 0x{self._address:02X} is 0x{chip_id:02X}, "
                f"expected 0x{_EXPECTED_CHIP_ID:02X} — this is not a QMC5883P. "
                f"A QMC5883L lives at 0x0D and a Honeywell HMC5883L at 0x1E; "
                f"neither is register-compatible with this driver."
            )

    def _configure(self) -> None:
        """Define the axis signs, then write both control registers until they stick.

        The datasheet's §7.1 sequence — 0x29, CONTROL_2, CONTROL_1, once each —
        does not work on this part. Measured on the bench with
        `magnetometer_range_probe`:

            written                       0x0A reads  0x0B reads
            CONTROL_2 then CONTROL_1      set         0x00   <- range lost
            CONTROL_1 then CONTROL_2      0x00        0x00   <- both lost
            both in one block write       0x00        0x00   <- both lost
            the pair, repeated            set         0x08   <- correct

        Writing the pair a second time is what makes both survive: the first
        pass takes the part out of suspend, and it is the suspend-to-normal
        transition that clears CONTROL_2. Once the part is already in normal
        mode, re-writing the same pair changes no mode and nothing is cleared.
        That mechanism is inferred, not documented, so the loop verifies
        rather than assuming a fixed number of passes.

        The cost of getting this wrong is invisible: the range silently falls
        back to its ±30 G default, headings still look reasonable, and every
        field value is 3.75× too small.
        """
        self._bus.write_byte_data(self._address, _AXIS_SIGN, _AXIS_SIGN_VALUE)
        for _ in range(_CONFIG_ATTEMPTS):
            self._bus.write_byte_data(
                self._address, _CONTROL_2, _CTRL2_8G_SET_RESET_ON
            )
            self._bus.write_byte_data(
                self._address, _CONTROL_1, _CTRL1_NORMAL_10HZ_OVERSAMPLE_8
            )
            time.sleep(0.02)
            if self._configuration_holds():
                break
        # One ODR period (100 ms at 10 Hz) so the first read has real data.
        time.sleep(0.1)

    def _configuration_holds(self) -> bool:
        """True when both control registers read back what we wrote."""
        return (
            self._bus.read_byte_data(self._address, _CONTROL_1)
            == _CTRL1_NORMAL_10HZ_OVERSAMPLE_8
            and self._bus.read_byte_data(self._address, _CONTROL_2)
            == _CTRL2_8G_SET_RESET_ON
        )

    def _verify_configuration(self) -> None:
        """Read both control registers back and confirm they hold what we wrote.

        Both are documented Read/Write (datasheet §9.1), so a mismatch means
        the write did not stick — a reset still settling, a marginal bus, or a
        clone that ignores a field.

        This check exists because the failure it catches is invisible without
        it. A wrong RNG value does not produce an error or an obviously broken
        heading; it produces a *plausible* heading at the wrong scale, which
        then quietly corrupts the hard-iron and soft-iron calibration derived
        from it. Failing at construction costs nothing — `app.py` treats an
        unopenable magnetometer as "no compass" and keeps running.
        """
        if self._configuration_holds():
            return
        ctrl1 = self._bus.read_byte_data(self._address, _CONTROL_1)
        ctrl2 = self._bus.read_byte_data(self._address, _CONTROL_2)
        raise RuntimeError(
            f"control registers did not stick after {_CONFIG_ATTEMPTS} "
            f"attempts: 0x0A reads 0x{ctrl1:02X} (wrote "
            f"0x{_CTRL1_NORMAL_10HZ_OVERSAMPLE_8:02X}), 0x0B reads "
            f"0x{ctrl2:02X} (wrote 0x{_CTRL2_8G_SET_RESET_ON:02X}). Field "
            f"range and output rate are not what this driver's unit "
            f"conversion assumes, so headings would be scaled wrongly. Run "
            f"magnetometer_range_probe to see which strategy this part accepts."
        )
