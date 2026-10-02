"""Work out `MAG_FORWARD_AXIS` / `MAG_LEFT_AXIS` by measurement.

Heading uses the two field components that are horizontal *once the board
is mounted*, and which two those are depends on the mount, not the chip.
`docs/hardware.md` describes finding them by watching a live readout and
reasoning about the numbers. That is hard to do alone: identifying the
quiet axis means turning the vest while reading a scrolling terminal, and
the two cannot be done at once by one person.

So this measures it instead, in two passes, and says the answer out loud.

Pass 1 — which axis is vertical
-------------------------------

Turn on the spot, upright, as the wearer would. The vertical axis sees
almost no change because it stays parallel to itself; the two horizontal
axes trace a circle. The axis with the smallest span is vertical, and
heading must *exclude* it.

Reported with the ratio of that span to the largest, because the
conclusion is only as good as the motion: tilting while turning moves the
vertical axis too, and a ratio near 1 means the pass measured a tumble
rather than a turn. A real example — the first attempt at this on the
project's own vest gave y=35 against x=82, z=82. A ratio of 0.43: the
right answer (y), reached by a motion sloppy enough that it could as
easily have been the wrong one.

Pass 2 — which way round they go
--------------------------------

Turn to the RIGHT. Heading must *increase* (N→E→S→W = 0→90→180→270). If
the chosen signs make it decrease, the compass is mirrored — and a
mirrored heading cannot be corrected by any offset, it reads perfectly
plausibly while sending the user the wrong way.

This pass needs no north reference at all, which matters: it is the
safety-critical half, and it can be done with a broken phone compass, in
the dark, indoors.

What this CANNOT determine
--------------------------

Where zero is. Four sign-and-order combinations survive pass 2, differing
only by a whole number of 90° rotations, and separating them needs one
known bearing from outside the device. Any of these will do:

  * a working compass, on any phone
  * a satellite map of where you are stood — find a straight wall or
    street, read its bearing off the map; map north is true north
  * Polaris, about 14° above the northern horizon at this latitude

Magnetic declination in Luzon is under a degree, so magnetic north and
true north are interchangeable here. Confirm for your own site with
NOAA's calculator rather than taking that on trust.

Run:
    python -m indepensense.sensors.tests.manual.magnetometer_axes

Audible throughout, like the calibration sweep, so the vest can be turned
away from the screen.
"""
import itertools
import math
import time

from indepensense.config import MAG_ADDRESS, MAG_I2C_BUS
from indepensense.sensors.base import heading_from_field
from indepensense.sensors.qmc5883p import QMC5883P
from indepensense.sensors.tests.manual.magnetometer_calibrate import (
    _TONE_BAD,
    _TONE_COUNTDOWN,
    _TONE_FINISH,
    _TONE_GOOD,
    _TONE_START,
    _beep,
)

TURN_SECONDS = 20.0
QUARTER_TURN_SECONDS = 10.0

# Largest acceptable ratio of the quiet axis' span to the busiest axis'.
#
# A clean turn on the spot leaves the vertical axis nearly flat, so the
# ratio lands well under 0.3. Above this the vest was tilted during the
# turn and all three axes moved, which makes "smallest span" a coin toss
# rather than a measurement.
_MAX_QUIET_RATIO = 0.35

# Minimum total rotation pass 2 must see before it will call a direction.
# A heading that wandered 10° either side of its start has not
# established which way round anything goes.
_MIN_TURN_DEG = 40.0

_AXES = ("x", "y", "z")


def _collect(mag, seconds: float, label: str):
    """Sample for `seconds`, returning `[(x, y, z), ...]`."""
    print(f"\n{label}")
    for remaining in (3, 2, 1):
        print(f"  {remaining}...", flush=True)
        _beep(_TONE_COUNTDOWN)
        time.sleep(0.7)
    print("  GO", flush=True)
    _beep(_TONE_START)

    samples = []
    started = time.time()
    while time.time() - started < seconds:
        reading = mag.read()
        if reading is not None:
            samples.append(
                (reading.magnetic_x, reading.magnetic_y, reading.magnetic_z)
            )
            left = seconds - (time.time() - started)
            print(f"\r  {left:4.1f}s  {len(samples):4d} samples", end="", flush=True)
        time.sleep(0.05)
    print()
    _beep(_TONE_FINISH)
    return samples


def find_vertical_axis(samples):
    """Return `(axis_letter, spans, ratio)`. Smallest span wins.

    Pure, so the decision can be tested against synthetic turns and
    tumbles rather than only on a Pi with a vest attached.
    """
    columns = list(zip(*samples))
    spans = {name: max(c) - min(c) for name, c in zip(_AXES, columns)}
    quiet = min(spans, key=spans.get)
    busiest = max(spans.values())
    ratio = spans[quiet] / busiest if busiest > 0 else 1.0
    return quiet, spans, ratio


def _total_turn(samples, forward_spec, left_spec):
    """Net rotation in degrees under one sign convention. Signed.

    Accumulates shortest-path steps rather than subtracting first from
    last, so a turn past 180° is not read as a turn the other way.
    """
    total = 0.0
    previous = None
    for field in samples:
        heading = heading_from_field(
            _component(field, forward_spec), _component(field, left_spec)
        )
        if previous is not None:
            total += (heading - previous + 180.0) % 360.0 - 180.0
        previous = heading
    return total


def _component(field, spec):
    sign = -1.0 if spec.startswith("-") else 1.0
    return sign * field[_AXES.index(spec[-1])]


def choose_signs(samples, horizontal):
    """Pick the (forward, left) spec whose heading increases turning right.

    Returns `(forward_spec, left_spec, turn_deg, candidates)`. Every
    combination that turns the right way is reported, because they are
    genuinely indistinguishable without a north reference — pretending
    otherwise would be inventing a bearing.
    """
    first, second = horizontal
    options = []
    for forward_axis, left_axis in ((first, second), (second, first)):
        for fs, ls in itertools.product("+-", "+-"):
            forward = f"{fs}{forward_axis}"
            left = f"{ls}{left_axis}"
            options.append((forward, left, _total_turn(samples, forward, left)))

    rightward = [o for o in options if o[2] > 0]
    if not rightward:
        return None, None, 0.0, []
    # All survivors measure the SAME turn — they differ only by where zero
    # sits — so this is a stable pick for the caller to start from, not a
    # determination. `options` is built in a fixed order, so the same vest
    # gives the same suggestion on every run, which matters when somebody
    # is working down the list by trial.
    best = rightward[0]
    return best[0], best[1], best[2], rightward


def main():
    mag = QMC5883P(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)
    print(__doc__.split("Run:")[0].rstrip())
    print("=" * 68)

    try:
        turn = _collect(
            mag, TURN_SECONDS,
            "PASS 1 — hold the vest UPRIGHT, as worn, and turn slowly on the\n"
            "spot through one full circle. Keep it level: do not tilt it.",
        )
        if len(turn) < 20:
            print("\nToo few samples — the magnetometer is not returning data.")
            _beep(_TONE_BAD)
            return

        quiet, spans, ratio = find_vertical_axis(turn)
        horizontal = tuple(a for a in _AXES if a != quiet)

        print()
        print(f"  spans:  " + "   ".join(
            f"{name}={spans[name]:6.1f} μT" for name in _AXES
        ))
        print(f"  quietest axis: {quiet}   "
              f"(ratio to busiest {ratio:.2f}, want below {_MAX_QUIET_RATIO:.2f})")
        print()

        if ratio > _MAX_QUIET_RATIO:
            print("  ALL THREE AXES MOVED. The vest was tilted during the turn,")
            print("  so 'smallest span' is a coin toss rather than a measurement.")
            print("  Re-run, keeping it upright and level while you turn.")
            _beep(_TONE_BAD)
            return

        print(f"  '{quiet}' is VERTICAL — heading must exclude it.")
        print(f"  Heading comes from '{horizontal[0]}' and '{horizontal[1]}'.")
        _beep(_TONE_GOOD)

        quarter = _collect(
            mag, QUARTER_TURN_SECONDS,
            "PASS 2 — still upright, now turn steadily to your RIGHT\n"
            "(clockwise, as seen from above) through at least a quarter turn.",
        )
        forward, left, turned, candidates = choose_signs(quarter, horizontal)

        print()
        if forward is None or abs(turned) < _MIN_TURN_DEG:
            print(f"  Only {abs(turned):.0f}° of rotation was seen; "
                  f"at least {_MIN_TURN_DEG:.0f}° is needed")
            print("  to tell which way round the axes go. Re-run pass 2 and "
                  "turn further.")
            _beep(_TONE_BAD)
            return

        print(f"  Saw {turned:.0f}° of rightward turn — enough to settle which")
        print("  way round the axes go. Start with:")
        print()
        print(f"      MAG_FORWARD_AXIS = \"{forward}\"")
        print(f"      MAG_LEFT_AXIS    = \"{left}\"")
        print()
        print("  That rotates the heading the correct way, which is the half")
        print("  that cannot be fixed later — a mirrored compass reads")
        print("  plausibly while sending the user the wrong way.")

        if len(candidates) > 1:
            print()
            print(f"  It is NOT the only answer. These {len(candidates)} all rotate correctly")
            print("  and all measured the same turn, so this pass cannot choose")
            print("  between them — they differ only by where zero sits, in whole")
            print("  90° steps:")
            for f, l, _t in candidates:
                marker = "  <- printed above" if (f, l) == (forward, left) else ""
                print(f"      forward={f}  left={l}{marker}")
            print()
            print("  Settle it with ONE known bearing. Either:")
            print("    * read the axis arrows printed on the breakout and work out")
            print("      which way they point on the assembled vest — no")
            print("      instrument needed, and it is exact; or")
            print("    * point the vest along a street you can read off a")
            print("      satellite map, and if the heading is out by about 90,")
            print("      180 or 270°, move to the next line in this list.")
            print()
            print("  Calibration does not depend on this. `magnetometer_calibrate`")
            print("  works on the raw chip axes, so run it now and settle the")
            print("  ambiguity afterwards.")
        _beep(_TONE_GOOD)
    finally:
        mag.close()


if __name__ == "__main__":
    main()
