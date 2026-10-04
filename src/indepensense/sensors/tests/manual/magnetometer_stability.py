"""Manual test: is the vest's own magnetic field actually constant?

Calibration assumes it is. Every offset it derives is the device's own
field, stored once and subtracted forever, which only works if that field
is the same tomorrow as today and the same upside down as upright.

This test exists because a sweep said otherwise. After its coverage
problems were fixed — every face a full turn, balanced axis half-spans,
a correct 42 uT field, in a location verified uniform by walking — it
still graded BAD at 41.2% spread. Fitting a *freely oriented* ellipsoid
instead of the per-axis one got that only to 38.1%, which rules out the
calibration model: the samples do not lie on an ellipsoid at all. The
field being measured changed while it was being measured.

Two ways that happens, needing opposite fixes:

  * **Time-varying.** The Pi's current draw, the cellular modem
    transmitting in bursts, the bit-banged I2C bus corrupting reads,
    temperature drift. The same orientation reads differently at
    different moments.

  * **Orientation-dependent.** Something magnetic shifting under gravity
    as the vest turns — a speaker, a motor, the battery, a cable moving
    a few millimetres. The offset is then a function of which way up the
    vest is, and "the device's own field" is not one number.

Phase 1 catches the first, Phase 2 the second.

Phase 1 — hold still
--------------------

Put the vest down and do not touch it. A stationary sensor in a static
field should read the same thing every time. Whatever spread appears here
is the noise floor, and nothing downstream can be tighter than it.

Phase 2 — return to the same orientation
----------------------------------------

Record one orientation, turn the vest right over, then bring it back to
exactly the orientation it started in and record again. Same place, same
moment, same way up: the two readings must agree. If they do not,
something inside moved, and no stored calibration can follow it.

Run on the Pi, in the same place you would calibrate:

    python -m indepensense.sensors.tests.manual.magnetometer_stability
"""
import math
import statistics
import time

from indepensense.config import MAG_ADDRESS, MAG_I2C_BUS
from indepensense.sensors.qmc5883p import QMC5883P
from indepensense.sensors.tests.manual.magnetometer_calibrate import (
    _TONE_BAD,
    _TONE_COUNTDOWN,
    _TONE_FINISH,
    _TONE_GOOD,
    _TONE_START,
    _beep,
)

STILL_S = 15.0
ORIENTATION_S = 6.0

# A stationary sensor should be far quieter than this. The QMC5883P's own
# noise is a fraction of a microtesla, so anything approaching one is
# interference or the bus, not the part.
_QUIET_UT = 1.0

# How far two recordings of the SAME orientation may differ before
# something is moving inside the vest. Generous: it has to survive being
# set down slightly differently by hand.
_RETURN_UT = 2.0


def _collect(mag, seconds, label):
    print(f"\n  {label}")
    for remaining in (3, 2, 1):
        print(f"    {remaining}...", flush=True)
        _beep(_TONE_COUNTDOWN)
        time.sleep(0.7)
    print("    GO", flush=True)
    _beep(_TONE_START)

    samples = []
    started = time.time()
    while time.time() - started < seconds:
        reading = mag.read()
        if reading is not None:
            samples.append((reading.magnetic_x, reading.magnetic_y,
                            reading.magnetic_z))
            left = seconds - (time.time() - started)
            magnitude = math.sqrt(sum(c * c for c in samples[-1]))
            print(f"\r    {left:4.1f}s  {len(samples):4d} samples  "
                  f"|B| {magnitude:5.1f} μT", end="", flush=True)
        time.sleep(0.05)
    print()
    _beep(_TONE_FINISH)
    return samples


def axis_means(samples):
    return tuple(statistics.fmean([s[axis] for s in samples])
                 for axis in (0, 1, 2))


def axis_spreads(samples):
    """Peak-to-peak per axis — what a *stationary* sensor should not have."""
    return tuple(max(s[axis] for s in samples) - min(s[axis] for s in samples)
                 for axis in (0, 1, 2))


def separation(first, second):
    """Distance between two mean field vectors, in uT."""
    return math.dist(axis_means(first), axis_means(second))


def main():
    print(__doc__.split("Run on the Pi")[0].rstrip())
    print("=" * 70)

    mag = QMC5883P(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)
    try:
        print("\nPHASE 1 — put the vest down and DO NOT TOUCH IT.")
        still = _collect(mag, STILL_S, "Hands off. Recording.")
        if len(still) < 20:
            print("\nToo few samples — the magnetometer is not returning data.")
            _beep(_TONE_BAD)
            return 1

        spreads = axis_spreads(still)
        print()
        print("  stationary spread:  "
              + "   ".join(f"{name}={value:5.2f}"
                           for name, value in zip("xyz", spreads))
              + " μT")
        noisy = max(spreads) > _QUIET_UT
        if noisy:
            print(f"  NOT QUIET. A sensor that is not moving should hold "
                  f"within {_QUIET_UT:.1f} μT.")
            print("  Something is varying in time: the Pi's current draw, the")
            print("  modem transmitting, the bit-banged I2C bus, or heat. No")
            print("  calibration can be tighter than this floor, so fix it")
            print("  first — try again with the modem and WiFi off.")
            _beep(_TONE_BAD)
        else:
            print("  Quiet. The field is steady when nothing moves, so the")
            print("  sweep's spread is not coming from time-varying noise.")
            _beep(_TONE_GOOD)

        print()
        print("PHASE 2 — the same orientation, twice, with a full turn between.")
        print("Put the vest down the way it normally sits. Note exactly how.")
        first = _collect(mag, ORIENTATION_S, "Orientation A — as it normally sits.")

        print("\n  Now turn it completely over and leave it a moment.")
        _collect(mag, ORIENTATION_S, "Orientation B — upside down.")

        print("\n  Now put it back EXACTLY as it was in A.")
        again = _collect(mag, ORIENTATION_S, "Orientation A again.")

        drift = separation(first, again)
        print()
        print(f"  A read {axis_means(first)[0]:+6.1f} "
              f"{axis_means(first)[1]:+6.1f} {axis_means(first)[2]:+6.1f} μT")
        print(f"  A again {axis_means(again)[0]:+6.1f} "
              f"{axis_means(again)[1]:+6.1f} {axis_means(again)[2]:+6.1f} μT")
        print(f"  difference: {drift:.1f} μT")
        print()

        if drift > _RETURN_UT:
            print("  THE SAME ORIENTATION READ DIFFERENTLY. Something magnetic")
            print("  inside the vest moved when it was turned over and did not")
            print("  come back — a speaker, a motor, the battery, or a cable")
            print("  carrying current shifting a few millimetres.")
            print()
            print("  This is why the sweep cannot be fitted. The offset is not")
            print("  one number, it is a function of which way up the vest is,")
            print("  and no stored calibration can follow that. Secure whatever")
            print("  is loose, then sweep again. Calibrating around it is not")
            print("  possible — this is a mechanical fix, not a software one.")
            _beep(_TONE_BAD)
            return 1

        print("  The vest returns to the same reading, so its field is fixed")
        print("  to the body and calibration is meaningful.")
        if noisy:
            print("  Phase 1 is then the remaining suspect — deal with that")
            print("  and sweep again.")
        else:
            print()
            print("  Both phases clean, yet the sweep could not be fitted.")
            print("  That is worth reporting as-is: the two explanations this")
            print("  test was built to separate are both ruled out, and the")
            print("  next suspect is the sensor itself rather than the vest.")
        _beep(_TONE_GOOD)
        return 0
    finally:
        mag.close()


if __name__ == "__main__":
    raise SystemExit(main())
