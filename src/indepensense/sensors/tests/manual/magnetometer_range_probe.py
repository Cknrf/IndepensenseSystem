"""Bring-up diagnostic: does the QMC5883P honour its field-range register?

Run:
    python -m indepensense.sensors.tests.manual.magnetometer_range_probe

Why this exists
---------------

`QMC5883P._verify_configuration` found that CONTROL_2 (0x0B) reads back
0x00 after being written 0x08 (±8 G). Two mutually exclusive causes, and
they need opposite fixes:

  A. The write is ignored. The part stays at its ±30 G reset default, so
     the driver must divide by 1000 LSB/G, not 3750.
  B. The write works but the register reads as zero on this silicon —
     undocumented but not unheard of. Then the range really is ±8 G,
     3750 LSB/G is correct, and the weak field readings have some other
     cause.

Read-back alone cannot distinguish them. Field strength can: the four
ranges have sensitivities differing by up to 15×, so writing each range
in turn while the sensor sits still must change the raw counts by a known
ratio *if* the writes take effect. If the counts do not budge, they don't.

Expected raw-count ratios relative to ±30 G, per datasheet §2.1:

    ±30 G   1000 LSB/G    1.00×
    ±12 G   2500 LSB/G    2.50×
    ± 8 G   3750 LSB/G    3.75×
    ± 2 G  15000 LSB/G   15.00×

So: hold the sensor absolutely still, and read the "raw |counts|" column.

  * Counts scale by roughly those ratios  -> writes work (cause B). The
    implied |B| column will read the same in every row.
  * Counts identical in all four rows     -> writes ignored (cause A).
    The implied |B| column will then only be right on the ±30 G row, and
    whichever row shows a plausible 25-65 μT names the real range.

This probe talks to the chip directly rather than through the driver, on
purpose: its whole job is to question the assumption the driver's unit
conversion is built on. The register constants below therefore mirror
`sensors/qmc5883p.py` instead of importing its privates — if you change
them there, change them here.
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

_CTRL1_NORMAL_10HZ_MAX_OVERSAMPLE = 0xC1
_AXIS_SIGN_VALUE = 0x06

_SAMPLES_PER_RANGE = 20

# (label, RNG bits, nominal LSB per Gauss)
_RANGES = [
    ("+/-30 G", 0b00, 1000.0),
    ("+/-12 G", 0b01, 2500.0),
    ("+/- 8 G", 0b10, 3750.0),
    ("+/- 2 G", 0b11, 15000.0),
]


def _read_axes(bus, address):
    """One sample as raw signed counts, or None if the chip flagged overflow."""
    status = bus.read_byte_data(address, _STATUS)
    raw = bytes(bus.read_i2c_block_data(address, _XOUT_LSB, 6))
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
        print()
        print("KEEP THE SENSOR PERFECTLY STILL for the next ~10 seconds.")
        print("Any movement invalidates the comparison.")
        print()
        time.sleep(2)

        # Soft reset, then the datasheet's setup order minus the range, which
        # is what we are about to vary.
        bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, 0x80)
        time.sleep(0.05)
        bus.write_byte_data(MAG_ADDRESS, _AXIS_SIGN, _AXIS_SIGN_VALUE)
        bus.write_byte_data(
            MAG_ADDRESS, _CONTROL_1, _CTRL1_NORMAL_10HZ_MAX_OVERSAMPLE
        )
        time.sleep(0.1)

        print(f"{'range':8} {'wrote':>6} {'reads':>6} "
              f"{'raw x':>8} {'raw y':>8} {'raw z':>8} "
              f"{'raw |B|':>9} {'implied':>9}  ovfl")
        print("-" * 78)

        baseline = None
        rows = []
        for label, rng_bits, lsb_per_gauss in _RANGES:
            wrote = rng_bits << 2          # SET/RESET mode 00 = set and reset on
            bus.write_byte_data(MAG_ADDRESS, _CONTROL_2, wrote)
            time.sleep(0.2)
            reads = bus.read_byte_data(MAG_ADDRESS, _CONTROL_2)

            sums = [0.0, 0.0, 0.0]
            good = 0
            overflows = 0
            for _ in range(_SAMPLES_PER_RANGE):
                sample = _read_axes(bus, MAG_ADDRESS)
                if sample is None:
                    overflows += 1
                else:
                    good += 1
                    for i in range(3):
                        sums[i] += sample[i]
                time.sleep(0.02)

            if good == 0:
                print(f"{label:8} 0x{wrote:02X}   0x{reads:02X}   "
                      f"{'all samples overflowed':>46}  {overflows:4}")
                continue

            x, y, z = (s / good for s in sums)
            counts = (x * x + y * y + z * z) ** 0.5
            # 1 Gauss = 100 μT.
            implied_ut = counts * 100.0 / lsb_per_gauss
            if baseline is None:
                baseline = counts
            rows.append((label, counts, implied_ut))

            print(f"{label:8} 0x{wrote:02X}   0x{reads:02X}   "
                  f"{x:8.0f} {y:8.0f} {z:8.0f} "
                  f"{counts:9.0f} {implied_ut:7.1f}uT  {overflows:4}")

        print()
        if len(rows) < 2 or baseline in (None, 0.0):
            print("Not enough usable rows to draw a conclusion.")
            return

        ratios = [counts / baseline for _label, counts, _ut in rows]
        print("Raw-count ratios vs the first row: "
              + "  ".join(f"{r:.2f}x" for r in ratios))
        spread = max(ratios) / min(ratios)
        print()
        if spread < 1.2:
            print("VERDICT: the counts barely moved, so writes to the RNG "
                  "field are being ignored.")
            print("The part is stuck at one range. Whichever row above shows "
                  "an implied |B| of")
            print("25-65 uT identifies it — that row's LSB/G is what the "
                  "driver must divide by.")
        else:
            print("VERDICT: the counts scaled with the range, so the RNG "
                  "writes DO take effect")
            print("and CONTROL_2 simply reads back as zero on this part. "
                  "+/-8 G and 3750 LSB/G")
            print("are correct; drop the CONTROL_2 read-back check and look "
                  "elsewhere for the")
            print("weak field (local shielding, or a genuinely quiet site).")
    finally:
        # Park the chip in suspend so it stops sampling.
        try:
            bus.write_byte_data(MAG_ADDRESS, _CONTROL_1, 0x00)
        except OSError:
            pass
        bus.close()


if __name__ == "__main__":
    main()
