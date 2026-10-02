"""Calibration helper for the QMC5883P magnetometer.

Rotate the assembled wearable through all orientations for ~30 s while
this script records the min and max field on each axis. From that one
sweep it derives both corrections the driver needs:

  * Hard-iron offset — `(max + min) / 2` per axis. This is the centre of
    the swing, i.e. the constant bias contributed by permanent magnets
    and ferrous mass on the cane (motor magnets, battery pack, the Pi).
    Subtracting it re-centres the field sphere on the origin.

  * Soft-iron scale — the axis half-spans `(max - min) / 2` should all be
    equal, because rotating through every orientation sweeps the same
    field magnitude on every axis. When they are not, the sphere has been
    stretched into an ellipsoid. Scaling each axis by
    `average_span / axis_span` restores it. Without this, heading error
    varies with which way you face, so it can't be trimmed out with a
    constant.

Run:
    python -m indepensense.sensors.tests.manual.magnetometer_calibrate

At the end, paste the printed values into `src/indepensense/config.py`:

    MAG_OFFSET_X/Y/Z
    MAG_SCALE_X/Y/Z

The calibration is device-specific — each assembled wearable needs its
own. Re-run if you significantly change the physical layout (relocate
batteries, add metal components, etc.). Not necessary if you just move
the wearable to a different room.

Runs with identity calibration (offsets 0, scales 1) so it captures the
raw min/max. Do this away from desks, speakers, laptops and steel
furniture — a local distortion baked into the offsets is worse than no
calibration at all.

Checking the result before you trust it
---------------------------------------

The min/max method derives six numbers from six readings — the extremes
— so one stray sample at one extreme silently poisons that whole axis,
and nothing about the printed values looks wrong when it happens. You
find out when the wearable sends somebody the wrong way.

So the sweep is graded against the one property that must hold: a
correctly calibrated sensor rotated through every orientation reads a
**constant field magnitude**, because Earth's field does not change
strength as you turn. Every sample is kept, the derived calibration is
applied to all of them, and the spread of the resulting magnitudes is
reported. Flat means the sphere was found; lumpy means it was not, and
no amount of offset can fix a sweep taken next to a filing cabinet.

This was added after analysing a calibration done against a phone
compass on this project's own hardware: its points were 20% out on
radius and up to 40° off their nominal spacing, and nothing in the
procedure had said so.

Run it without watching the screen
----------------------------------

Tumbling the wearable through every orientation and reading a terminal
are not things one person can do at the same time, and the screen is
where the result is. So the whole sweep is also audible through the
wearable's own speaker: a countdown, a start tone, a finish tone, and
two clearly different verdict tones for pass and fail.

That means the usable procedure is: start it, put the laptop down, pick
the vest up, wait for the start tone, tumble until the finish tone, and
listen for the verdict. Walk back to the screen only to copy numbers
that have already been graded worth copying.

Silent if there is no audio device — over SSH with no headset attached,
or on a dev machine — because a calibration helper must not fail on the
absence of a speaker.
"""
import argparse
import math
import time

from indepensense.config import MAG_ADDRESS, MAG_I2C_BUS
from indepensense.sensors.qmc5883p import QMC5883P, apply_calibration
from indepensense.voice.audio import play_cue

# Long enough to work through six orientations unhurried, including the
# time it takes to physically turn the vest between them. The original 30 s
# assumed a continuous tumble; six discrete positions with a transition
# between each is a different motion and needs the room. Override with
# `--seconds` — more is never worse, since the derivation takes extremes
# and extra samples only improve the odds of reaching them.
DURATION_S = 60.0

# The sweep is paced as six positions: each face of the vest pointed at
# the floor in turn, spinning at each. A tone marks every changeover, so
# nobody has to divide the clock in their head while holding a vest.
#
# Six because that is every face of a box, which is what guarantees each
# sensor axis points both along and against the field at some point — the
# condition the min/max derivation actually depends on.
_SWEEP_POSITIONS = 6

# Changeover is counted in, not announced at the instant it happens.
#
# A single "move now" blip leaves the user spinning right up to it and
# then scrambling to reposition, which is how a face gets missed. Two low
# beeps a second apart give warning, and the third sound — higher, so it
# cannot be mistaken for the other two — means the vest should already be
# on its next face and spinning again.
_TONE_TURN = [(520.0, 0.07)]
_TONE_SPIN = [(900.0, 0.14)]

# How long before the changeover the warning beeps start. One per second,
# so this is also how many of them there are.
_TURN_LEAD_S = 2.0

# Audible structure of the sweep, for running it away from the screen.
# Pitch carries the meaning: rising is progress or success, falling is
# finished or failed.
_TONE_COUNTDOWN = [(600.0, 0.08)]
_TONE_START = [(500.0, 0.09), (700.0, 0.09), (1000.0, 0.22)]
_TONE_FINISH = [(1000.0, 0.10), (700.0, 0.10), (500.0, 0.22)]
_TONE_GOOD = [(700.0, 0.10), (900.0, 0.10), (1200.0, 0.30)]
# Deliberately low, slow and unmistakable. Hearing this from across a
# field has to be enough to know the sweep must be done again.
_TONE_BAD = [(420.0, 0.30), (300.0, 0.45)]


# Residual magnitude spread, as a percentage of the mean, below which the
# sweep is worth pasting.
#
# Zero is unreachable by hand: the sensor is being turned by a person, no
# rotation covers the sphere evenly, and the min/max method fits only a
# box around the data. Measured on a good outdoor sweep this lands in
# single figures; the bad phone-referenced dataset that prompted this
# check sat at 20-24%.
_GOOD_SPREAD_PCT = 10.0
_MARGINAL_SPREAD_PCT = 20.0

# Earth's field, as the magnitude a corrected sweep should average out
# at. Varies with latitude — roughly 25 μT near the magnetic equator to
# 65 μT near the poles, about 40-45 μT in the Philippines.
_EARTH_FIELD_MIN_UT = 25.0
_EARTH_FIELD_MAX_UT = 65.0


def _beep(steps) -> None:
    """Play a cue through the wearable's speaker. Never raises.

    The whole point is to be usable away from the terminal, so a missing
    audio device must cost the audio and nothing else — the sweep and its
    grade are still printed.
    """
    try:
        play_cue(steps)
    except Exception:
        pass


def cue_schedule(duration_s, positions, lead_s):
    """When each changeover cue falls, as `[(seconds, cue), ...]`.

    `cue` is `"turn"` for a warning beep or `"spin"` for the go tone. The
    go tone lands exactly on a face boundary; the warnings lead it by one
    second each.

    Pure and computed up front, so the pacing can be checked against a
    clock in a test rather than by standing in a room holding a vest.

    Degrades rather than misleads when there is no room for a lead-in: a
    segment shorter than the warning window drops the warnings and keeps
    the go tones, because knowing *when* to move matters more than being
    warned about it.
    """
    segment = duration_s / positions
    lead = min(lead_s, max(0.0, segment - 1.0))
    beeps = int(lead)

    events = []
    for boundary in range(1, positions):
        at = boundary * segment
        for countdown in range(beeps, 0, -1):
            events.append((at - countdown, "turn"))
        events.append((at, "spin"))
    return events


def grade_sweep(samples, offsets, scales):
    """How close the corrected sweep comes to a sphere.

    Returns `(mean_ut, spread_pct, verdict, advice)`.

    The measure is the spread of corrected magnitudes as a percentage of
    their mean. A correctly calibrated sensor reads the same field
    strength in every orientation, so this is the one number that says
    whether the sweep found the sphere — and, unlike the offsets
    themselves, it cannot look reasonable while being wrong.

    Peak-to-peak rather than standard deviation. A single stray sample at
    one extreme is exactly what poisons the min/max method, and a
    standard deviation over several hundred samples would average that
    one reading away — hiding the failure this exists to catch.

    Pure, and takes its samples as an argument, so the grading can be
    tested against known-good and known-bad sweeps on a machine with no
    magnetometer attached.
    """
    magnitudes = [
        math.sqrt(
            apply_calibration(x, offsets[0], scales[0]) ** 2
            + apply_calibration(y, offsets[1], scales[1]) ** 2
            + apply_calibration(z, offsets[2], scales[2]) ** 2
        )
        for x, y, z in samples
    ]
    if not magnitudes:
        return 0.0, 0.0, "no data", "No samples to grade."

    mean = sum(magnitudes) / len(magnitudes)
    if mean <= 0.0:
        return 0.0, 0.0, "no data", "Corrected field is zero — check the wiring."

    spread_pct = 100.0 * (max(magnitudes) - min(magnitudes)) / mean

    if spread_pct <= _GOOD_SPREAD_PCT:
        verdict = "GOOD"
        advice = "The sweep found the sphere. These values are worth pasting."
    elif spread_pct <= _MARGINAL_SPREAD_PCT:
        verdict = "MARGINAL"
        advice = (
            "Usable but not good. Most often this is incomplete coverage — "
            "re-run and rotate\nthrough more orientations, especially "
            "upside-down and on each side."
        )
    else:
        verdict = "BAD — do not paste these"
        advice = (
            "No offset can correct this; the field itself was distorted "
            "while you swept.\nMove away from desks, chairs, laptops, "
            "speakers, cars and reinforced walls —\noutdoors and well "
            "clear of buildings — then re-run."
        )
    return mean, spread_pct, verdict, advice


def main():
    parser = argparse.ArgumentParser(description="Magnetometer calibration sweep.")
    parser.add_argument(
        "--seconds", type=float, default=DURATION_S,
        help=f"how long to sweep (default {DURATION_S:.0f}). Longer is never "
             f"worse — the derivation takes extremes, so extra samples only "
             f"improve the odds of reaching them.",
    )
    args = parser.parse_args()
    duration_s = max(6.0, args.seconds)

    mag = QMC5883P(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)

    segment = duration_s / _SWEEP_POSITIONS
    print(f"Hold the vest away from your body. Treat it as a box with six")
    print(f"faces. Point each face at the FLOOR in turn, and spin the vest")
    print(f"round while it is there.")
    print()
    print(f"  1. front    2. back    3. left side")
    print(f"  4. right    5. top     6. bottom")
    print()
    print(f"Each face gets {segment:.0f}s, counted for you — you never have to")
    print(f"watch a clock. {duration_s:.0f}s total.")
    print()
    print("Listen for the tones — you do not need to watch this screen:")
    print("  three beeps, then a RISING tone  = start, face 1, spin")
    print("  two LOW beeps                    = finish up, start repositioning")
    print("  one HIGHER tone                  = you should be on the next face")
    print("                                     now — start spinning again")
    print("  a FALLING tone                   = stop, sweep finished")
    print("  a rising three-note chime        = PASS, numbers are printed here")
    print("  two low slow tones               = FAIL, come back and re-run")
    print()
    for remaining in (3, 2, 1):
        print(f"{remaining}...", flush=True)
        _beep(_TONE_COUNTDOWN)
        time.sleep(0.7)
    print("GO!", flush=True)
    _beep(_TONE_START)

    x_min = x_max = None
    y_min = y_max = None
    z_min = z_max = None

    # Every sample, not just the extremes. The grade at the end needs to
    # apply the derived calibration to all of them, and 30 s at the
    # driver's poll rate is a few hundred triples.
    samples: list[tuple[float, float, float]] = []

    t_start = time.time()
    sample_count = 0
    try:
        schedule = cue_schedule(duration_s, _SWEEP_POSITIONS, _TURN_LEAD_S)
        next_cue = 0
        position = 0
        while time.time() - t_start < duration_s:
            elapsed = time.time() - t_start
            # Walk the schedule rather than recomputing boundaries: the
            # cue times are decided once, up front, where they can be
            # tested without a magnetometer or a stopwatch.
            while next_cue < len(schedule) and schedule[next_cue][0] <= elapsed:
                _, cue = schedule[next_cue]
                next_cue += 1
                if cue == "turn":
                    _beep(_TONE_TURN)
                else:
                    position += 1
                    _beep(_TONE_SPIN)

            reading = mag.read()
            if reading is not None:
                sample_count += 1
                samples.append(
                    (reading.magnetic_x, reading.magnetic_y, reading.magnetic_z)
                )
                x_min = reading.magnetic_x if x_min is None else min(x_min, reading.magnetic_x)
                x_max = reading.magnetic_x if x_max is None else max(x_max, reading.magnetic_x)
                y_min = reading.magnetic_y if y_min is None else min(y_min, reading.magnetic_y)
                y_max = reading.magnetic_y if y_max is None else max(y_max, reading.magnetic_y)
                z_min = reading.magnetic_z if z_min is None else min(z_min, reading.magnetic_z)
                z_max = reading.magnetic_z if z_max is None else max(z_max, reading.magnetic_z)

                elapsed = time.time() - t_start
                print(
                    f"\r  [face {position + 1}/{_SWEEP_POSITIONS}] "
                    f"[{elapsed:5.1f}s / {duration_s:.0f}s] "
                    f"x=[{x_min:+7.1f},{x_max:+7.1f}] "
                    f"y=[{y_min:+7.1f},{y_max:+7.1f}] "
                    f"z=[{z_min:+7.1f},{z_max:+7.1f}] μT",
                    end="",
                    flush=True,
                )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print()
    finally:
        mag.close()
    _beep(_TONE_FINISH)

    print()
    print()
    if sample_count == 0 or x_min is None:
        print("No samples captured — the magnetometer isn't returning data.")
        print(
            f"Check `sudo i2cdetect -y {MAG_I2C_BUS}` "
            f"for address 0x{MAG_ADDRESS:02X}."
        )
        return

    offset_x = (x_max + x_min) / 2
    offset_y = (y_max + y_min) / 2
    offset_z = (z_max + z_min) / 2

    span_x = (x_max - x_min) / 2
    span_y = (y_max - y_min) / 2
    span_z = (z_max - z_min) / 2

    if min(span_x, span_y, span_z) <= 0.0:
        print("At least one axis never moved — the sweep didn't cover enough")
        print("orientations, or an axis is dead. Re-run and rotate more fully.")
        return

    span_avg = (span_x + span_y + span_z) / 3
    scale_x = span_avg / span_x
    scale_y = span_avg / span_y
    scale_z = span_avg / span_z

    print(f"Calibration complete. {sample_count} samples captured.")
    print()
    print(f"Axis half-spans: x={span_x:.1f}  y={span_y:.1f}  z={span_z:.1f} μT "
          f"(mean {span_avg:.1f})")
    print()

    mean_ut, spread_pct, verdict, advice = grade_sweep(
        samples,
        (offset_x, offset_y, offset_z),
        (scale_x, scale_y, scale_z),
    )

    # Printed before the values, not after. The whole point is to be read
    # by somebody about to copy six numbers into config.py.
    print("  " + "-" * 64)
    print(f"  SWEEP QUALITY: {verdict}")
    print(f"  corrected field {mean_ut:.1f} μT, "
          f"varying {spread_pct:.1f}% across the sweep")
    print("  " + "-" * 64)
    print()
    print(f"  {advice}")
    print()

    # Magnitude is a separate question from consistency: a sweep can be
    # beautifully spherical and still be measuring the wrong thing.
    if not _EARTH_FIELD_MIN_UT <= mean_ut <= _EARTH_FIELD_MAX_UT:
        print(f"  Also: {mean_ut:.1f} μT is outside Earth's range "
              f"({_EARTH_FIELD_MIN_UT:.0f}-{_EARTH_FIELD_MAX_UT:.0f} μT).")
        if mean_ut < _EARTH_FIELD_MIN_UT:
            print("  Too low usually means the sweep never reached the "
                  "extremes — rotate further.")
        else:
            print("  Too high means something magnetic is close to the "
                  "sensor. If it is part of")
            print("  the wearable it belongs there and the offsets will "
                  "absorb it; if it is the")
            print("  bench, move.")
        print()

    _beep(_TONE_BAD if verdict.startswith("BAD") else _TONE_GOOD)

    if verdict.startswith("BAD"):
        print("  Values withheld. Re-run somewhere cleaner.")
        return

    print("Paste these values into `src/indepensense/config.py`:")
    print()
    print(f"    MAG_OFFSET_X = {offset_x:.3f}")
    print(f"    MAG_OFFSET_Y = {offset_y:.3f}")
    print(f"    MAG_OFFSET_Z = {offset_z:.3f}")
    print(f"    MAG_SCALE_X = {scale_x:.4f}")
    print(f"    MAG_SCALE_Y = {scale_y:.4f}")
    print(f"    MAG_SCALE_Z = {scale_z:.4f}")
    print()
    print("Then rerun `single_magnetometer_test.py` and verify that rotating")
    print("the cane through 360° gives smooth heading values and a roughly")
    print("constant |B|.")


if __name__ == "__main__":
    main()
