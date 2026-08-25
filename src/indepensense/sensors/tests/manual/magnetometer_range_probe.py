"""Bring-up diagnostic: how do you get both QMC5883P control registers to stick?

Run:
    python -m indepensense.sensors.tests.manual.magnetometer_range_probe

Why this exists
---------------

Two runs against this part disagreed, and together they point at something
the datasheet does not mention.

  * The driver writes CONTROL_2 (0x0B, range) then CONTROL_1 (0x0A, mode),
    which is the order the datasheet's §7.1 example uses. Result: CONTROL_1
    held its value, CONTROL_2 read back 0x00, and measurements flowed — but
    scaled as if the range were the ±30 G reset default rather than the
    ±8 G we asked for.
  * An earlier version of this probe wrote CONTROL_1 first, then CONTROL_2.
    Result: the mirror image. CONTROL_2 held every value written to it,
    and every measurement came back as exactly zero — which is what a part
    parked in suspend mode (MODE=00) reports.

One explanation fits both: writing either control register clears the
other. Whichever was written last survives. So there may be no single-byte
ordering that leaves both correct, and the fix has to come from somewhere
else — a block write that lands both in one transaction, a retry loop, or
accepting the range the part will actually hold.

This probe tries each strategy in turn against a freshly reset chip and
reports, for each: what both control registers read back, whether data
flowed, and what field strength the readings imply *at whatever range
CONTROL_2 actually reports*. That last column is the real prize — Earth's
field is 25-65 μT, so the strategy whose implied |B| lands in that band
has both a working mode and an honest sensitivity constant.

Hold the sensor still throughout so the rows stay comparable.

This talks to the chip directly rather than through the driver, on purpose:
its job is to question the assumptions the driver is built on. The register
constants below therefore mirror `sensors/qmc5883p.py` rather than importing
its privates — if you change them there, change them here.
"""
import time

from indepensense.config import MAG_ADDRESS, MAG_I2C_BUS

_CHIP_ID = 0x00
_XOUT_LSB = 0x01
_STATUS = 0x09
_CONTROL_1 = 0x0A
_CONTROL_2 = 0x0B
_AXIS_SIGN = 0x29

_STATUS_OVFL = 0x02

_CTRL1 = 0x01          # OSR2=1, OSR1=8, ODR=10 Hz, MODE=normal
_CTRL2 = 0x08          # RNG=±8 G, SET/RESET on
_AXIS_SIGN_VALUE = 0x06

_SAMPLES = 15

# RNG bits (CONTROL_2 bits 3:2) -> nominal LSB/Gauss, datasheet §2.1.
_LSB_PER_GAUSS = {0b00: 1000.0, 0b01: 2500.0, 0b10: 3750.0, 0b11: 15000.0}
_RANGE_LABEL = {0b00: "30G", 0b01: "12G", 0b10: "8G", 0b11: "2G"}


def _reset(bus):
    """Soft reset and wait generously — the datasheet gives no reset time."""
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, 0x80)
    time.sleep(0.3)


def _strategy_datasheet_order(bus):
    """§7.1 order, exactly what the driver does today."""
    bus.write_byte_data(MAG_ADDRESS, _AXIS_SIGN, _AXIS_SIGN_VALUE)
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, _CTRL2)
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_1, _CTRL1)


def _strategy_reverse_order(bus):
    """Mode first, range second."""
    bus.write_byte_data(MAG_ADDRESS, _AXIS_SIGN, _AXIS_SIGN_VALUE)
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_1, _CTRL1)
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, _CTRL2)


def _strategy_block_write(bus):
    """Both control registers in ONE auto-incrementing write from 0x0A.

    If the clobbering is an artefact of two separate write transactions,
    this is the fix: the part sees one transaction covering both registers.
    """
    bus.write_byte_data(MAG_ADDRESS, _AXIS_SIGN, _AXIS_SIGN_VALUE)
    bus.write_i2c_block_data(MAG_ADDRESS, _CONTROL_1, [_CTRL1, _CTRL2])


def _strategy_spaced_writes(bus):
    """Datasheet order with 50 ms of settling between every write."""
    bus.write_byte_data(MAG_ADDRESS, _AXIS_SIGN, _AXIS_SIGN_VALUE)
    time.sleep(0.05)
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, _CTRL2)
    time.sleep(0.05)
    bus.write_byte_data(MAG_ADDRESS, _CONTROL_1, _CTRL1)
    time.sleep(0.05)


def _strategy_retry_until_both_stick(bus):
    """Alternate the two writes, re-reading, until both registers agree."""
    bus.write_byte_data(MAG_ADDRESS, _AXIS_SIGN, _AXIS_SIGN_VALUE)
    for _ in range(10):
        bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, _CTRL2)
        bus.write_byte_data(MAG_ADDRESS, _CONTROL_1, _CTRL1)
        time.sleep(0.02)
        if (bus.read_byte_data(MAG_ADDRESS, _CONTROL_1) == _CTRL1
                and bus.read_byte_data(MAG_ADDRESS, _CONTROL_2) == _CTRL2):
            return


_STRATEGIES = [
    ("datasheet order", _strategy_datasheet_order),
    ("reverse order", _strategy_reverse_order),
    ("block write", _strategy_block_write),
    ("spaced writes", _strategy_spaced_writes),
    ("retry loop", _strategy_retry_until_both_stick),
]


def _sample(bus):
    """One sample as raw signed counts, or None if the chip flagged overflow."""
    status = bus.read_byte_data(MAG_ADDRESS, _STATUS)
    raw = bytes(bus.read_i2c_block_data(MAG_ADDRESS, _XOUT_LSB, 6))
    if status & _STATUS_OVFL:
        return None
    return tuple(
        int.from_bytes(raw[i:i + 2], "little", signed=True) for i in (0, 2, 4)
    )


def main():
    from smbus2 import SMBus  # lazy: only resolvable on the Pi

    bus = SMBus(MAG_I2C_BUS)
    try:
        chip_id = bus.read_byte_data(MAG_ADDRESS, _CHIP_ID)
        print(f"Chip ID at 0x{MAG_ADDRESS:02X}: 0x{chip_id:02X} "
              f"(expect 0x80 for QMC5883P)")
        print(f"Target config: CONTROL_1=0x{_CTRL1:02X} (normal, 10 Hz), "
              f"CONTROL_2=0x{_CTRL2:02X} (±8 G)")
        print()
        print("KEEP THE SENSOR PERFECTLY STILL for the next ~15 seconds.")
        print()
        time.sleep(2)

        print(f"{'strategy':18} {'0x0A':>6} {'0x0B':>6} {'range':>6} "
              f"{'raw x':>7} {'raw y':>7} {'raw z':>7} "
              f"{'counts':>7} {'implied |B|':>12}")
        print("-" * 86)

        results = []
        for name, apply_strategy in _STRATEGIES:
            _reset(bus)
            apply_strategy(bus)
            time.sleep(0.15)

            ctrl1 = bus.read_byte_data(MAG_ADDRESS, _CONTROL_1)
            ctrl2 = bus.read_byte_data(MAG_ADDRESS, _CONTROL_2)
            rng_bits = (ctrl2 >> 2) & 0b11
            lsb_per_gauss = _LSB_PER_GAUSS[rng_bits]

            sums = [0.0, 0.0, 0.0]
            good = 0
            for _ in range(_SAMPLES):
                s = _sample(bus)
                if s is not None:
                    good += 1
                    for i in range(3):
                        sums[i] += s[i]
                time.sleep(0.02)

            if good == 0:
                print(f"{name:18} 0x{ctrl1:02X}   0x{ctrl2:02X}   "
                      f"{_RANGE_LABEL[rng_bits]:>6} "
                      f"{'(every sample overflowed)':>44}")
                continue

            x, y, z = (v / good for v in sums)
            counts = (x * x + y * y + z * z) ** 0.5
            implied_ut = counts * 100.0 / lsb_per_gauss   # 1 Gauss = 100 μT
            plausible = 25.0 <= implied_ut <= 65.0
            results.append((name, ctrl1, ctrl2, implied_ut, counts, plausible))

            print(f"{name:18} 0x{ctrl1:02X}   0x{ctrl2:02X}   "
                  f"{_RANGE_LABEL[rng_bits]:>6} "
                  f"{x:7.0f} {y:7.0f} {z:7.0f} {counts:7.0f} "
                  f"{implied_ut:8.1f} uT{'  <-- plausible' if plausible else ''}")

        print()
        both_stuck = [r for r in results if r[1] == _CTRL1 and r[2] == _CTRL2]
        measuring = [r for r in results if r[4] > 0.0]

        if both_stuck:
            print("VERDICT: these strategies set BOTH registers correctly — "
                  "use the first one:")
            for name, _c1, _c2, ut, _counts, ok in both_stuck:
                print(f"  {name}: implied |B| = {ut:.1f} uT"
                      f"{' (plausible)' if ok else ' (NOT plausible — recheck)'}")
        elif measuring:
            print("VERDICT: no strategy holds both registers, so the part "
                  "cannot be configured to")
            print("±8 G while also measuring. The rows above that produced "
                  "data show which range")
            print("it will actually hold; the one with a plausible implied "
                  "|B| is the range the")
            print("driver should be built around — set its LSB/G as the "
                  "sensitivity constant and")
            print("stop trying to write the range at all.")
        else:
            print("VERDICT: nothing measured under any strategy. That is a "
                  "wiring or power fault,")
            print("not a configuration one — recheck 3.3 V and SDA/SCL.")
    finally:
        try:
            bus.write_byte_data(MAG_ADDRESS, _CONTROL_1, 0x00)
        except OSError:
            pass
        bus.close()


if __name__ == "__main__":
    main()
