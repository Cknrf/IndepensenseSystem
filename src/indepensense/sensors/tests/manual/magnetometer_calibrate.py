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
import statistics
import time

from indepensense.config import MAG_ADDRESS, MAG_I2C_BUS, MAG_SWEEP_DIR
from indepensense.sensors.qmc5883p import QMC5883P, apply_calibration
from indepensense.sensors.tests.manual.sweep_store import FACES, SweepStore
from indepensense.voice.audio import play_cue

# Seconds of actual SPINNING per face. This is the knob, not the total.
#
# The total used to be, and it made the transition eat the sweep: asking
# for more time gave you more of both, and shortening the sweep silently
# shortened the spinning that does the work. Nobody thinks "I want a
# 90-second sweep"; they think "I want ten seconds to spin at each face".
# So that is what `--spin` takes, and the total is derived.
#
# Ten is about two unhurried rotations, which is comfortable coverage.
# More is never worse — the derivation takes extremes, so extra samples
# only improve the odds of reaching them — it just tires the arms.
SPIN_S = 10.0

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
# so this is also how many of them there are: a 5-4-3-2-1 countdown, with
# the digits on screen matching the beeps rather than running beside them.
#
# Five seconds because turning a vest over by hand is slower than it
# sounds, and the cost of being hurried is a face swept badly or skipped
# — which is the one thing the min/max derivation cannot recover from.
# Note what it buys at the default 60 s: six faces of 10 s each, so 5 s of
# transition leaves 5 s of spinning. That is about one unhurried rotation
# per face, and opposite faces cover each other's gaps. Raise `--seconds`
# if the grade comes back short.
_TURN_LEAD_S = 5.0

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
# How far one face's CORRECTED mean may sit from the others before it is
# worth re-recording. Looser than it sounds: the corrected field is
# constant by construction, so anything past this is a real difference in
# what that face was measuring, not sampling luck.
_FACE_RESIDUAL_TOLERANCE = 0.12

# How many median-absolute-deviations from the median before a corrected
# magnitude is "far out". Four is roughly 2.7 sigma for well-behaved data
# — loose enough not to count the tails of an honest sweep.
_OUTLIER_MADS = 4.0

# Below this the least-squares fit has nothing to work with and min/max
# is no worse. Six unknowns, so this is a wide margin, not a tight one.
_MIN_FIT_SAMPLES = 50

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


# The six faces, in the order the sweep walks them. Named on screen so
# nobody has to hold the list in their head while holding a vest.
_FACE_NAMES = ("FRONT", "BACK", "LEFT SIDE", "RIGHT SIDE", "TOP", "BOTTOM")

# Width of the live line, padded so a shorter frame cannot leave the tail
# of a longer one behind it on the same carriage return.
_LINE_WIDTH = 76


def progress_line(position, within_s, segment_s, lead_s, magnitude_ut,
                  positions=_SWEEP_POSITIONS):
    """One frame of the live display.

    Two states, because they call for different actions and reading the
    wrong one wastes a face: SPIN while the clock runs, TURN during the
    counted changeover — and the TURN frame names where to go next rather
    than where you are, since that is the thing about to be needed.

    The magnitude shown is RAW — uncorrected — and labelled as such
    because it swings wildly during an uncalibrated sweep (16 to 68 uT on
    this project's own vest) and looks alarming otherwise. That swing is
    the hard-iron offset the sweep exists to measure, not a fault. The
    grade afterwards is what judges it.

    Pure, so the wording and the state boundary can be tested rather than
    inspected by standing in a room holding a vest.
    """
    face = _FACE_NAMES[min(position, len(_FACE_NAMES) - 1)]
    remaining = max(0.0, segment_s - within_s)
    is_last = position >= positions - 1

    if not is_last and remaining <= lead_s:
        upcoming = _FACE_NAMES[min(position + 1, len(_FACE_NAMES) - 1)]
        line = (
            f"  [{position + 1}/{positions}]  >>> TURN TO {upcoming} DOWN <<<"
            f"   {math.ceil(remaining)}"
        )
    else:
        filled = int(10 * min(1.0, within_s / segment_s)) if segment_s > 0 else 0
        bar = "#" * filled + "." * (10 - filled)
        line = (
            f"  [{position + 1}/{positions}]  SPIN: {face} DOWN"
            f"   [{bar}] {remaining:4.1f}s   raw |B| {magnitude_ut:5.1f}"
        )
    return f"{line:<{_LINE_WIDTH}}"


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


# A sample this far above the median is not the field — it is something
# magnetic that came close. Earth's field is constant in magnitude, so on
# a clean sweep every raw sample has the same |B| whatever the hard-iron
# offset is; a steady offset moves the centre of the swing, never its
# size.
_WILD_MULTIPLE = 1.5


def diagnose_interference(timed_samples, segment_s, positions=_SWEEP_POSITIONS):
    """Say what KIND of bad a failed sweep was. Returns a list of lines.

    "Move away from desks" is the right advice for a distorted field and
    useless for the two other ways this fails, which need different
    actions entirely:

      * the baseline itself is wrong — something magnetic is fixed close
        to the sensor, and no amount of moving the vest will help
      * spikes spread across most faces — something magnetic is moving
        WITH the vest, so it travels to the next room too
      * spikes in one or two faces — the vest passed something, once

    Told apart by where the wild samples sit in time. Pure, so the three
    conclusions can be tested against synthetic sweeps.
    """
    magnitudes = [math.sqrt(x * x + y * y + z * z) for _t, (x, y, z) in timed_samples]
    if not magnitudes:
        return []

    ordered = sorted(magnitudes)
    median = ordered[len(ordered) // 2]
    peak = max(magnitudes)
    lines = [f"  raw field: median {median:.0f} μT, peak {peak:.0f} μT"]

    if not _EARTH_FIELD_MIN_UT <= median <= _EARTH_FIELD_MAX_UT:
        lines.append(
            f"  The BASELINE is wrong, not just the extremes — a typical "
            f"sample reads {median:.0f} μT"
        )
        lines.append(
            "  where Earth gives 25-65. Something magnetic sits permanently "
            "close to the"
        )
        lines.append(
            "  sensor. Moving the vest will not help; the sensor has to move "
            "away from it."
        )
        return lines

    wild = [t for t, m in zip((t for t, _f in timed_samples), magnitudes)
            if m > median * _WILD_MULTIPLE]
    if not wild:
        lines.append(
            "  No single sample ran wild, so the field was distorted rather "
            "than spiked —"
        )
        lines.append("  steel in the walls or floor. Try outdoors.")
        return lines

    faces_hit = {min(positions - 1, int(t / segment_s)) for t in wild}
    share = 100.0 * len(wild) / len(magnitudes)
    lines.append(
        f"  {share:.0f}% of samples ran wild (over {_WILD_MULTIPLE:g}x the median), "
        f"across {len(faces_hit)} of the {positions} faces."
    )

    if len(faces_hit) >= positions / 2:
        lines.append("")
        lines.append(
            "  Spread across most of the sweep, which means it is moving WITH "
            "the vest."
        )
        lines.append(
            "  Look for something magnetic that swings when the vest is "
            "turned over but"
        )
        lines.append(
            "  not when it is worn: a dangling headset, an unsecured motor, "
            "buzzer or"
        )
        lines.append(
            "  battery lead. Secure it and re-run — a different room will not "
            "fix this."
        )
    else:
        faces = ", ".join(_FACE_NAMES[f] for f in sorted(faces_hit))
        lines.append("")
        lines.append(
            f"  Confined to {faces} — the vest passed something, rather than "
            f"carrying it."
        )
        lines.append(
            "  Re-run with more clear space around you, and keep it away from "
            "the desk"
        )
        lines.append("  you started the command from.")
    return lines


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


def reject_outliers(samples, tolerance=_OUTLIER_MADS):
    """Drop samples that cannot be on the same ellipsoid as the rest.

    Returns `(kept, dropped_count)`.

    Needed because *both* derivations collapse under a single bad
    reading, which was not obvious and is worth stating plainly:
    min/max takes its answer straight from the extremes, and least
    squares weights by the square of the residual, so a frame reading
    900 uT outvotes a thousand good ones. Injecting two corrupted frames
    into a clean sweep moved the min/max offset from 12.0 to 25.0 and the
    fitted one to -537.7. Robustness has to happen before either.

    The test is distance from a provisional centre — the per-axis median,
    which no single outlier can move — judged against the median absolute
    deviation of those distances rather than their standard deviation,
    since the outliers would otherwise inflate the measure meant to catch
    them. Deliberately loose: the distances vary honestly between the
    ellipsoid's shortest and longest semi-axis, and discarding real
    coverage to tidy the numbers is the one thing worse than keeping a
    stray sample.
    """
    if len(samples) < _MIN_FIT_SAMPLES:
        return list(samples), 0

    centre = [statistics.median([s[axis] for s in samples]) for axis in (0, 1, 2)]
    distances = [
        math.dist(sample, centre)
        for sample in samples
    ]
    middle = statistics.median(distances)
    deviation = statistics.median([abs(d - middle) for d in distances])
    if deviation <= 0:
        return list(samples), 0

    kept = [
        sample
        for sample, distance in zip(samples, distances)
        if abs(distance - middle) <= tolerance * deviation
    ]
    if len(kept) < _MIN_FIT_SAMPLES:
        # Rejecting this much means the assumption behind the test is
        # wrong, not that the data is. Keep everything and let the grade
        # report the mess honestly.
        return list(samples), 0
    return kept, len(samples) - len(kept)


def fit_ellipsoid(samples):
    """Least-squares fit of an axis-aligned ellipsoid. `(offsets, scales)`.

    The model is the same one `config.py` stores — a per-axis offset and
    a per-axis scale — so this is a better way of finding the same six
    numbers, not a different calibration.

    Why not min/max
    ---------------

    The min/max derivation takes each axis' offset from exactly two
    samples: the largest and the smallest. Everything in between is
    discarded. That makes it exact on a perfectly swept sphere and
    fragile on anything else, in two ways that both bit on the real vest:

      * **One corrupted reading moves an extreme.** The magnetometer is
        on a bit-banged I2C bus, where a mangled frame is a transport
        failure, not a magnetic one. Injecting three bad frames into an
        otherwise clean 1150-sample sweep moved the derived field from
        42 uT to 502 uT — and because the offsets themselves were wrong,
        every corrected magnitude was wrong with them. No statistic
        computed afterwards can separate that from real distortion.

      * **An axis that never quite reaches its extreme is biased.** Six
        faces, each rotated about one axis, trace six circles rather than
        a filled sphere. The true extremes may simply never be sampled,
        and min/max cannot tell "not reached" from "reached".

    A least-squares fit uses every sample for every parameter, so one bad
    reading is one vote among a thousand and an unreached extreme is
    interpolated rather than guessed.

    Returns `None` when the fit is degenerate — too few samples, or a
    sweep so flat the system is ill-conditioned — leaving the caller to
    fall back rather than hand back nonsense with a confident face.
    """
    import numpy as np                  # lazy: Pi-only at module import time

    if len(samples) < _MIN_FIT_SAMPLES:
        return None

    data = np.asarray(samples, dtype=float)
    x, y, z = data[:, 0], data[:, 1], data[:, 2]

    # ((v - c) / s)^2 summed = 1, expanded into terms linear in the
    # unknowns:  a.x^2 + a.y^2 + a.z^2 + b.x + b.y + b.z = 1
    design = np.column_stack([x * x, y * y, z * z, x, y, z])
    try:
        solution, _residuals, rank, _sv = np.linalg.lstsq(
            design, np.ones(len(data)), rcond=None
        )
    except np.linalg.LinAlgError:
        return None
    if rank < 6:
        return None

    quad = solution[:3]
    lin = solution[3:]
    if np.any(quad <= 0):
        # Not an ellipsoid — the sweep did not enclose a volume.
        return None

    centre = -lin / (2.0 * quad)
    # Recover the scale factor dropped when the constant was normalised.
    normaliser = 1.0 + float(np.sum(quad * centre * centre))
    if normaliser <= 0:
        return None
    semi_axes = 1.0 / np.sqrt(quad * normaliser)
    if not np.all(np.isfinite(semi_axes)) or np.any(semi_axes <= 0):
        return None

    # Same convention as the min/max path: normalise the three axes to
    # their mean so a sphere comes out a sphere at roughly true scale.
    scales = float(np.mean(semi_axes)) / semi_axes
    return tuple(float(c) for c in centre), tuple(float(s) for s in scales)


def calibration_from_minmax(samples):
    """Derive `(offsets, scales, spans)` from raw `(x, y, z)` triples.

    Hard-iron offset is the centre of each axis' range; soft-iron scale
    normalises the three half-spans to their mean, so a sphere comes out
    a sphere. Both are the standard min/max derivation.

    Raises `ValueError` naming the problem when the sweep cannot support
    a calibration at all — no samples, or an axis that never moved. That
    is a different failure from a sweep that is merely poor, which is
    what `grade_sweep` is for, and conflating the two would let "the
    sensor is dead" print as "try rotating more".

    Pure, and shared by the all-in-one sweep and the face-at-a-time one,
    so the two cannot drift into computing different numbers from the
    same samples.
    """
    if not samples:
        raise ValueError("no samples")

    xs = [s[0] for s in samples]
    ys = [s[1] for s in samples]
    zs = [s[2] for s in samples]

    offsets = (
        (max(xs) + min(xs)) / 2,
        (max(ys) + min(ys)) / 2,
        (max(zs) + min(zs)) / 2,
    )
    spans = (
        (max(xs) - min(xs)) / 2,
        (max(ys) - min(ys)) / 2,
        (max(zs) - min(zs)) / 2,
    )
    if min(spans) <= 0.0:
        raise ValueError(
            "at least one axis never moved — the sweep did not cover enough "
            "orientations, or an axis is dead"
        )

    span_avg = sum(spans) / 3
    scales = tuple(span_avg / span for span in spans)
    return offsets, scales, spans


def calibration_from_samples(samples):
    """Best available `(offsets, scales, spans)` for `samples`.

    Prefers the least-squares fit and falls back to min/max when the fit
    is degenerate. `spans` always comes from the observed extremes — it
    describes the sweep's coverage, which is a property of what was
    recorded rather than of how it was fitted.
    """
    kept, _dropped = reject_outliers(samples)

    offsets, scales, spans = calibration_from_minmax(kept)

    fitted = fit_ellipsoid(kept)
    if fitted is not None:
        offsets, scales = fitted
    return offsets, scales, spans


def corrected_magnitudes(samples, offsets, scales) -> list[float]:
    """Field strength after calibration, one per sample."""
    return [
        math.sqrt(
            apply_calibration(x, offsets[0], scales[0]) ** 2
            + apply_calibration(y, offsets[1], scales[1]) ** 2
            + apply_calibration(z, offsets[2], scales[2]) ** 2
        )
        for x, y, z in samples
    ]


def spread_profile(magnitudes) -> dict:
    """Peak-to-peak spread beside a robust one, and the outlier count.

    `grade_sweep` measures peak-to-peak on purpose — a stray sample at an
    extreme is exactly what poisons a min/max calibration, and a standard
    deviation over several hundred readings would average it away. The
    cost of that choice is that the verdict cannot tell *one corrupted
    reading* from *a genuinely distorted field*, and those need opposite
    responses: filter the sample, or go and stand somewhere else.

    So this reports both. If the middle 90% is tight while peak-to-peak
    is dreadful, a handful of readings are wild and the sweep itself is
    fine. That is a live possibility on this build — the magnetometer
    sits on a bit-banged I2C bus, where a corrupted frame is a transport
    failure rather than a magnetic one.

    Outliers are counted against the median absolute deviation rather
    than the standard deviation, because the outliers would otherwise
    inflate the very measure used to detect them.
    """
    ordered = sorted(magnitudes)
    count = len(ordered)
    median = statistics.median(ordered)
    low = ordered[int(0.05 * count)]
    high = ordered[min(count - 1, int(0.95 * count))]
    deviation = statistics.median([abs(m - median) for m in ordered])

    wild = [m for m in ordered
            if deviation > 0 and abs(m - median) > _OUTLIER_MADS * deviation]
    return {
        "median": median,
        "peak_to_peak_pct": (ordered[-1] - ordered[0]) / median * 100 if median else 0.0,
        "middle_pct": (high - low) / median * 100 if median else 0.0,
        "wild": len(wild),
        "count": count,
        "lowest": ordered[0],
        "highest": ordered[-1],
    }


def print_result(samples, diagnosis=()) -> bool:
    """Grade a sweep, print the verdict, and print the values if it passed.

    Returns True if the values were printed. `diagnosis` is extra lines
    shown only on a failure — where the all-in-one sweep says *when* it
    went wrong, the face-at-a-time one says *which face*.
    """
    try:
        offsets, scales, spans = calibration_from_samples(samples)
    except ValueError as exc:
        print(f"Cannot calibrate: {exc}.")
        print(f"Check `sudo i2cdetect -y {MAG_I2C_BUS}` "
              f"for address 0x{MAG_ADDRESS:02X}.")
        return False

    kept, dropped = reject_outliers(samples)
    if dropped:
        print(f"{dropped} of {len(samples)} samples discarded as impossible "
              "— they could not")
        print("lie on the same sphere as the rest. On this build that points at")
        print("the bit-banged I2C bus mangling frames, not at anything magnetic;")
        print("a handful is normal, a large fraction means check the wiring.")
        print()

    span_avg = sum(spans) / 3
    print(f"{len(kept)} samples.")
    print()
    print(f"Axis half-spans: x={spans[0]:.1f}  y={spans[1]:.1f}  "
          f"z={spans[2]:.1f} \u03bcT (mean {span_avg:.1f})")
    print()

    # Graded on the kept samples: a discarded frame's corrected
    # magnitude is meaningless and would dominate a peak-to-peak
    # measure purely by being wrong.
    mean_ut, spread_pct, verdict, advice = grade_sweep(kept, offsets, scales)

    # Printed before the values, not after. The whole point is to be read
    # by somebody about to copy six numbers into config.py.
    print("  " + "-" * 64)
    print(f"  SWEEP QUALITY: {verdict}")
    print(f"  corrected field {mean_ut:.1f} \u03bcT, "
          f"varying {spread_pct:.1f}% across the sweep")
    print("  " + "-" * 64)
    print()
    print(f"  {advice}")
    print()

    # Magnitude is a separate question from consistency: a sweep can be
    # beautifully spherical and still be measuring the wrong thing.
    if not _EARTH_FIELD_MIN_UT <= mean_ut <= _EARTH_FIELD_MAX_UT:
        print(f"  Also: {mean_ut:.1f} \u03bcT is outside Earth's range "
              f"({_EARTH_FIELD_MIN_UT:.0f}-{_EARTH_FIELD_MAX_UT:.0f} \u03bcT).")
        if mean_ut < _EARTH_FIELD_MIN_UT:
            print("  Too low usually means the sweep never reached the "
                  "extremes \u2014 rotate further.")
        else:
            print("  Too high means something magnetic is close to the "
                  "sensor. If it is part of")
            print("  the wearable it belongs there and the offsets will "
                  "absorb it; if it is the")
            print("  bench, move.")
        print()

    _beep(_TONE_BAD if verdict.startswith("BAD") else _TONE_GOOD)

    if verdict.startswith("BAD"):
        profile = spread_profile(corrected_magnitudes(kept, offsets, scales))
        print(f"  Spread, two ways:")
        print(f"    peak to peak   {profile['peak_to_peak_pct']:6.1f}%   "
              f"({profile['lowest']:.1f} to {profile['highest']:.1f} \u03bcT) "
              "- what the verdict uses")
        print(f"    middle 90%     {profile['middle_pct']:6.1f}%   "
              "- the same sweep with the extremes ignored")
        print(f"    far-out samples {profile['wild']:5d} of {profile['count']}")
        print()
        if profile["middle_pct"] <= _GOOD_SPREAD_PCT < profile["peak_to_peak_pct"]:
            print("  The bulk of the sweep is tight and only a few readings are")
            print("  wild, which is not what a distorted field looks like \u2014")
            print("  distortion moves whole stretches of a sweep, not isolated")
            print("  samples. Re-running outdoors will probably not help; the")
            print("  remaining strays are on the wire, not in the room.")
            print()

        for line in diagnosis:
            print(line)
        print()
        print("  Values withheld.")
        return False

    print("Paste these values into `src/indepensense/config.py`:")
    print()
    print(f"    MAG_OFFSET_X = {offsets[0]:.3f}")
    print(f"    MAG_OFFSET_Y = {offsets[1]:.3f}")
    print(f"    MAG_OFFSET_Z = {offsets[2]:.3f}")
    print(f"    MAG_SCALE_X = {scales[0]:.4f}")
    print(f"    MAG_SCALE_Y = {scales[1]:.4f}")
    print(f"    MAG_SCALE_Z = {scales[2]:.4f}")
    print()
    print("Then rerun `single_magnetometer_test.py` and verify that rotating")
    print("the cane through 360\u00b0 gives smooth heading values and a roughly")
    print("constant |B|.")
    return True


# --- face at a time ----------------------------------------------------------
#
# The all-in-one sweep above runs all six faces back to back on a timer.
# It works, but one spoiled face costs the whole 90 seconds, and the
# first real attempt came back BAD with no way to redo only the part that
# went wrong.
#
# These record one face per command instead, accumulating into
# `SweepStore`. The maths is identical — the store hands back one flat
# list of samples, exactly what the timed sweep collects — so the two
# modes cannot disagree about the same readings.
#
# What this mode makes easier to get wrong is covered in `sweep_store`:
# every face has to come from one unchanged physical setup, and nothing
# here can detect a re-seated battery.

_SWEEP_PATH = MAG_SWEEP_DIR / "sweep.json"

_FACE_INSTRUCTIONS = {
    "front": "front of the vest pointing UP, as if it were lying on its back",
    "back": "back of the vest pointing UP",
    "left": "LEFT side pointing UP",
    "right": "RIGHT side pointing UP",
    "top": "TOP pointing UP, the way it sits when worn",
    "bottom": "BOTTOM pointing UP, upside down",
}


def collect_face(mag, face: str, seconds: float):
    """Spin on one face for `seconds`, returning the samples."""
    print()
    print(f"  FACE: {face.upper()}")
    print(f"  Hold the vest with the {_FACE_INSTRUCTIONS[face]},")
    print(f"  then rotate it steadily for {seconds:.0f} seconds.")
    print()
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
            field = (reading.magnetic_x, reading.magnetic_y,
                     reading.magnetic_z)
            samples.append(field)
            magnitude = math.sqrt(sum(c * c for c in field))
            left = seconds - (time.time() - started)
            print(f"\r    {left:4.1f}s  {len(samples):4d} samples  "
                  f"|B| {magnitude:5.1f} \u03bcT", end="", flush=True)
        time.sleep(0.05)
    print()
    _beep(_TONE_FINISH)
    return samples


def status_lines(store) -> list[str]:
    """Progress so far.

    Shows the raw field RANGE per face, not a mean. Raw magnitude varies
    with orientation by twice the hard-iron offset, so a wide range is
    what a well-rotated face looks like and a mean is not comparable
    between faces at all. An earlier version compared those means and
    flagged a different innocent face on every run.

    The only judgement made here is whether a face moved. Everything else
    waits for the calibration — see `face_diagnosis`.
    """
    lines = []
    stats = store.face_stats()
    still = {face for face, _swing in store.still_faces()}

    lines.append("  face      samples   raw |B| range      rotated")
    lines.append("  " + "-" * 52)
    for face in FACES:
        stat = stats.get(face)
        if stat is None:
            lines.append(f"  {face:9s}       -           -              -")
            continue
        moved = "NO \u2014 re-record" if face in still else "yes"
        lines.append(
            f"  {face:9s} {stat['count']:7d}   "
            f"{stat['low']:5.1f}-{stat['high']:5.1f} \u03bcT      {moved}"
        )
    lines.append("")

    missing = store.missing()
    if missing:
        lines.append(f"  {len(store.recorded())}/6 recorded. "
                     f"Still needed: {', '.join(missing)}")
    else:
        lines.append("  All six recorded.")

    if still:
        lines.append("")
        lines.append("  A face marked NO barely moved: its samples are all")
        lines.append("  nearly the same orientation, so they pad the count")
        lines.append("  without adding anything the derivation can use.")
        lines.append("  Re-record it, rotating through the full 10 seconds.")

    if store.is_stale():
        hours = store.span_seconds() / 3600.0
        lines.append("")
        lines.append(f"  These faces span {hours:.1f} hours. The offsets being")
        lines.append("  computed are the device's OWN field, so they are only")
        lines.append("  valid if nothing about the assembly changed in that")
        lines.append("  time. If anything was unplugged, --reset and start over.")

    return lines


def residual_by_face(store, offsets, scales) -> dict[str, float]:
    """Mean CORRECTED field strength per face, in uT.

    This is the comparison the raw-magnitude check was reaching for and
    getting wrong. A raw reading is Earth's field plus the hard-iron
    offset, and the offset is fixed in the sensor frame while Earth's
    field rotates through it — so raw magnitude swings with orientation
    and says nothing about interference. Subtract the offset and apply
    the scales and the magnitude *is* constant in every orientation, by
    construction. A face that still reads differently from the rest saw a
    field the others did not.

    Only available once the calibration exists, which is why this is a
    finishing diagnosis and not a during-recording one.
    """
    means = {}
    for face in store.recorded():
        samples = store.face_samples(face)
        if not samples:
            continue
        means[face] = statistics.fmean(
            math.sqrt(
                apply_calibration(x, offsets[0], scales[0]) ** 2
                + apply_calibration(y, offsets[1], scales[1]) ** 2
                + apply_calibration(z, offsets[2], scales[2]) ** 2
            )
            for x, y, z in samples
        )
    return means


def face_diagnosis(store) -> list[str]:
    """Which face to re-record, decided after the calibration is derived."""
    try:
        offsets, scales, _spans = calibration_from_samples(store.samples())
    except ValueError:
        return []

    means = residual_by_face(store, offsets, scales)
    if len(means) < 3:
        return []
    median = statistics.median(means.values())
    if median <= 0:
        return []

    lines = []
    for face in sorted(means, key=lambda f: -abs(means[f] - median)):
        drift = abs(means[face] - median) / median
        if drift > _FACE_RESIDUAL_TOLERANCE:
            lines.append(
                f"  {face}: corrected field {means[face]:.1f} \u03bcT against "
                f"{median:.1f} \u03bcT elsewhere \u2014 re-record this face."
            )
    return lines


def run_face_mode(args) -> int:
    store = SweepStore(_SWEEP_PATH)

    if args.reset:
        store.reset()
        store.save()
        print(f"Cleared {_SWEEP_PATH}. Start again with --face front.")
        return 0

    if args.status:
        if not store.recorded():
            print("Nothing recorded yet. Start with:")
            print("    python -m indepensense.sensors.tests.manual."
                  "magnetometer_calibrate --face front")
            return 0
        print("\n".join(status_lines(store)))
        return 0

    if args.finish:
        missing = store.missing()
        if missing:
            print(f"Only {len(store.recorded())}/6 faces recorded. "
                  f"Missing: {', '.join(missing)}.")
            print("Record them first — a calibration from a partial sweep is")
            print("worse than none, because it looks like a real answer.")
            return 1
        print("\n".join(status_lines(store)))
        print()
        print_result(store.samples(), face_diagnosis(store))
        return 0

    face = args.face.lower()
    if face not in FACES:
        print(f"Unknown face {args.face!r}. Expected one of: "
              f"{', '.join(FACES)}")
        return 2

    mag = QMC5883P(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)
    try:
        samples = collect_face(mag, face, max(1.0, args.spin))
    finally:
        mag.close()

    if not samples:
        print("No samples — the magnetometer is not returning data.")
        print(f"Check `sudo i2cdetect -y {MAG_I2C_BUS}` "
              f"for address 0x{MAG_ADDRESS:02X}.")
        _beep(_TONE_BAD)
        return 1

    store.record(face, samples)
    store.save()
    print()
    print("\n".join(status_lines(store)))

    # The sixth face computes on the spot. `--finish` still exists and is
    # still the only way to recompute, which is what you want after
    # re-recording a face the cross-check flagged — but in the ordinary
    # run-through there is nothing to decide, so there is no reason to
    # make somebody type a seventh command to see the answer.
    if not store.missing():
        print()
        print_result(store.samples(), face_diagnosis(store))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Magnetometer calibration sweep.")
    knob = parser.add_mutually_exclusive_group()
    knob.add_argument(
        "--spin", type=float, default=SPIN_S, metavar="SECONDS",
        help=f"seconds of spinning per face (default {SPIN_S:.0f}). The "
             f"{_TURN_LEAD_S:.0f}s changeover is added on top, so the whole "
             f"sweep takes (spin + {_TURN_LEAD_S:.0f}) x {_SWEEP_POSITIONS}.",
    )
    knob.add_argument(
        "--seconds", type=float, default=None, metavar="SECONDS",
        help="total sweep length instead, if you would rather cap the whole "
             "thing. The changeover comes out of this, not on top of it.",
    )
    parser.add_argument(
        "--face", metavar="NAME",
        help="record ONE face and stop, accumulating across runs: "
             f"{', '.join(FACES)}. Lets a spoiled face be redone on its "
             "own instead of costing the whole sweep.",
    )
    parser.add_argument(
        "--status", action="store_true",
        help="show which faces are recorded, and flag any that look wrong",
    )
    parser.add_argument(
        "--finish", action="store_true",
        help="compute the calibration from the faces recorded so far",
    )
    parser.add_argument(
        "--reset", action="store_true",
        help="discard the accumulated faces and start a new sweep",
    )
    args = parser.parse_args()

    if args.face or args.status or args.finish or args.reset:
        return run_face_mode(args)

    if args.seconds is not None:
        duration_s = max(6.0, args.seconds)
    else:
        duration_s = (max(1.0, args.spin) + _TURN_LEAD_S) * _SWEEP_POSITIONS

    mag = QMC5883P(bus_number=MAG_I2C_BUS, address=MAG_ADDRESS)

    segment = duration_s / _SWEEP_POSITIONS
    print(f"Hold the vest away from your body. Treat it as a box with six")
    print(f"faces. Point each face at the FLOOR in turn, and spin the vest")
    print(f"round while it is there.")
    print()
    print(f"  1. front    2. back    3. left side")
    print(f"  4. right    5. top     6. bottom")
    print()
    print(f"{segment - _TURN_LEAD_S:.0f}s spinning at each face, then a "
          f"{_TURN_LEAD_S:.0f}s countdown to")
    print(f"turn it over. Counted for you — you never have to watch a clock.")
    print(f"{duration_s:.0f}s in total.")
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

    # Every sample, not just the extremes. The grade at the end needs to
    # apply the derived calibration to all of them, and 30 s at the
    # driver's poll rate is a few hundred triples.
    samples: list[tuple[float, float, float]] = []
    # The same samples with their elapsed time, so a failed sweep can say
    # WHEN it went wrong — which is what separates "you passed something"
    # from "something is riding on the vest".
    timed: list[tuple[float, tuple[float, float, float]]] = []

    t_start = time.time()
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
                field = (
                    reading.magnetic_x, reading.magnetic_y, reading.magnetic_z
                )
                samples.append(field)
                timed.append((time.time() - t_start, field))
                magnitude = math.sqrt(
                    reading.magnetic_x ** 2
                    + reading.magnetic_y ** 2
                    + reading.magnetic_z ** 2
                )
                print(
                    "\r" + progress_line(
                        position,
                        elapsed - position * segment,
                        segment,
                        _TURN_LEAD_S,
                        magnitude,
                    ),
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
    print_result(samples, diagnose_interference(timed, segment))


if __name__ == "__main__":
    raise SystemExit(main())
