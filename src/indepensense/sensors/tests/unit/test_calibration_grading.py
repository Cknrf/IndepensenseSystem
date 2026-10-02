"""Unit tests for the magnetometer sweep grader.

The min/max calibration derives six numbers from six readings — the
extremes — so one stray sample silently poisons an axis, and nothing
about the printed offsets looks wrong when it happens. You find out when
the wearable sends somebody the wrong way.

`grade_sweep` is the check that catches it, and it is a pure function
over a list of samples, so it is tested here against synthetic sweeps
with known defects rather than on a Pi with a magnetometer attached.

The property it tests: a correctly calibrated sensor rotated through
every orientation reads a CONSTANT field magnitude, because Earth's
field does not change strength as you turn.
"""
import math
import random

import pytest

from indepensense.sensors.tests.manual.magnetometer_calibrate import grade_sweep

EARTH_UT = 45.0


def _sphere(count, radius, offset=(0.0, 0.0, 0.0), stretch=(1.0, 1.0, 1.0),
            noise=0.0, seed=7):
    """Points scattered over a sphere, optionally displaced and stretched."""
    rng = random.Random(seed)
    points = []
    for _ in range(count):
        z = rng.uniform(-1.0, 1.0)
        theta = rng.uniform(0.0, 2.0 * math.pi)
        r = math.sqrt(1.0 - z * z)
        unit = (r * math.cos(theta), r * math.sin(theta), z)
        points.append(tuple(
            unit[i] * radius * stretch[i] + offset[i] + rng.gauss(0.0, noise)
            for i in range(3)
        ))
    return points


def _derive(samples):
    """The min/max derivation `main()` performs, so tests grade what ships."""
    axes = list(zip(*samples))
    offsets = tuple((max(a) + min(a)) / 2 for a in axes)
    spans = [(max(a) - min(a)) / 2 for a in axes]
    average = sum(spans) / 3
    return offsets, tuple(average / s for s in spans)


def _grade(samples):
    offsets, scales = _derive(samples)
    return grade_sweep(samples, offsets, scales)


# --- sweeps that should pass --------------------------------------------------

def test_a_clean_sweep_is_good():
    _mean, spread, verdict, _advice = _grade(_sphere(400, EARTH_UT, noise=0.3))

    assert verdict == "GOOD", spread


def test_strong_hard_iron_is_still_good():
    """Hard iron is what the offsets exist to remove. A sweep displaced by
    more than twice Earth's field must still grade well, or the check
    would reject exactly the devices that most need calibrating — this
    wearable carries three motor magnets and a 4S pack."""
    samples = _sphere(400, EARTH_UT, offset=(120.0, -80.0, 60.0), noise=0.3)

    _mean, spread, verdict, _advice = _grade(samples)

    assert verdict == "GOOD", spread


def test_soft_iron_is_still_good():
    """Likewise the scales. An axis stretched 40% is corrected, not
    condemned."""
    samples = _sphere(400, EARTH_UT, stretch=(1.4, 1.0, 1.0), noise=0.3)

    _mean, spread, verdict, _advice = _grade(samples)

    assert verdict == "GOOD", spread


def test_a_clean_sweep_recovers_earths_field():
    mean, _spread, _verdict, _advice = _grade(
        _sphere(400, EARTH_UT, offset=(120.0, -80.0, 60.0), noise=0.3)
    )

    assert 25.0 <= mean <= 65.0
    assert mean == pytest.approx(EARTH_UT, abs=3.0)


# --- sweeps that should fail --------------------------------------------------

def test_one_stray_extreme_sample_is_caught():
    """The failure mode the min/max method is built out of. A single bad
    reading at one extreme sets that axis' whole span, and the offsets it
    produces look perfectly ordinary."""
    samples = _sphere(399, EARTH_UT, noise=0.3) + [(400.0, 0.0, 0.0)]

    _mean, _spread, verdict, _advice = _grade(samples)

    assert verdict.startswith("BAD")


def test_rotating_in_one_plane_only_is_caught():
    """The most common way to do the sweep wrong: spinning the device flat
    instead of tumbling it. Two axes look fine and the third never moves."""
    rng = random.Random(3)
    samples = [
        (EARTH_UT * math.cos(a), EARTH_UT * math.sin(a), rng.gauss(0.0, 1.5))
        for a in [rng.uniform(0.0, 2 * math.pi) for _ in range(400)]
    ]

    _mean, _spread, verdict, _advice = _grade(samples)

    assert verdict.startswith("BAD")


def test_a_distorted_field_is_caught():
    """Sweeping next to steel. No offset can fix it — the field itself was
    wrong while it was measured."""
    _mean, _spread, verdict, _advice = _grade(_sphere(400, EARTH_UT, noise=4.0))

    assert verdict.startswith("BAD")


def test_the_real_bad_dataset_is_caught():
    """Eight points recorded against a phone compass on this project's own
    hardware. They were pasted into a working sketch and nothing in the
    procedure said they were 20% out on radius and up to 40 degrees off
    their nominal spacing. This test is why the grader exists."""
    x = [-3833.1, -5834.0, -10235.8, -13318.5, -5622.2, 978.6, 2359.8, 2011.5]
    y = [-6813.3, -6132.7, -3281.7, 463.0, 3551.9, 490.9, -1460.3, -5003.6]
    samples = [(a, b, 0.0) for a, b in zip(x, y)]

    offsets = ((max(x) + min(x)) / 2, (max(y) + min(y)) / 2, 0.0)
    spans = [(max(x) - min(x)) / 2, (max(y) - min(y)) / 2]
    average = sum(spans) / 2
    scales = (average / spans[0], average / spans[1], 1.0)

    _mean, spread, verdict, _advice = grade_sweep(samples, offsets, scales)

    assert verdict.startswith("BAD")
    assert spread > 40.0


# --- degenerate input ---------------------------------------------------------

def test_no_samples_does_not_raise():
    mean, spread, verdict, advice = grade_sweep([], (0.0,) * 3, (1.0,) * 3)

    assert verdict == "no data"
    assert (mean, spread) == (0.0, 0.0)
    assert advice


def test_an_all_zero_sweep_does_not_divide_by_zero():
    samples = [(0.0, 0.0, 0.0)] * 10

    _mean, _spread, verdict, _advice = grade_sweep(samples, (0.0,) * 3, (1.0,) * 3)

    assert verdict == "no data"


def test_every_verdict_carries_advice():
    """A grade with nothing to do about it wastes the user's attention."""
    for samples in (
        _sphere(200, EARTH_UT, noise=0.3),      # good
        _sphere(200, EARTH_UT, noise=2.2),      # marginal-ish
        _sphere(200, EARTH_UT, noise=4.0),      # bad
    ):
        _mean, _spread, _verdict, advice = _grade(samples)
        assert advice.strip()


# --- changeover pacing -------------------------------------------------------
#
# A single "move now" blip left the user spinning right up to it and then
# scrambling to reposition, which is how a face gets missed — and a missed
# face is exactly what leaves an axis short of its extreme. Two warning
# beeps lead the changeover; the third sound means the vest should already
# be on its next face.

from indepensense.sensors.tests.manual.magnetometer_calibrate import cue_schedule


def test_every_face_boundary_gets_a_go_tone():
    schedule = cue_schedule(60.0, 6, 2.0)
    go_times = [at for at, cue in schedule if cue == "spin"]

    # Five changeovers between six faces; the first face starts on the
    # sweep's own start tone and the last ends on the finish tone.
    assert go_times == [10.0, 20.0, 30.0, 40.0, 50.0]


def test_the_warnings_lead_the_changeover_by_one_second_each():
    schedule = cue_schedule(60.0, 6, 2.0)
    first = [(at, cue) for at, cue in schedule if at <= 10.0]

    assert first == [(8.0, "turn"), (9.0, "turn"), (10.0, "spin")]


def test_the_count_matches_the_lead():
    """One beep per second of lead, so the user can count them."""
    for lead, expected in ((2.0, 2), (3.0, 3), (1.0, 1)):
        schedule = cue_schedule(60.0, 6, lead)
        warnings = [at for at, cue in schedule if cue == "turn" and at < 10.0]
        assert len(warnings) == expected, lead


def test_a_longer_sweep_keeps_the_same_lead():
    """More time per face buys more spinning, not a longer countdown —
    the repositioning takes what it takes."""
    schedule = cue_schedule(90.0, 6, 2.0)
    first = [(at, cue) for at, cue in schedule if at <= 15.0]

    assert first == [(13.0, "turn"), (14.0, "turn"), (15.0, "spin")]


def test_cues_are_in_time_order():
    """The loop walks this list without sorting it."""
    times = [at for at, _cue in cue_schedule(90.0, 6, 2.0)]

    assert times == sorted(times)


def test_a_segment_too_short_to_lead_still_marks_the_boundaries():
    """Degrades rather than misleads: knowing *when* to move matters more
    than being warned about it, so the warnings go and the go tones stay."""
    schedule = cue_schedule(6.0, 6, 2.0)      # 1 s per face

    assert [cue for _at, cue in schedule] == ["spin"] * 5


def test_no_cue_lands_before_the_sweep_starts():
    """A negative time would fire every warning at once on the first tick."""
    for total in (6.0, 12.0, 60.0, 90.0):
        assert all(at > 0.0 for at, _cue in cue_schedule(total, 6, 2.0)), total


# --- the live display --------------------------------------------------------
#
# Two states that call for different actions, so reading the wrong one
# costs a face. The TURN frame names where to go NEXT rather than where
# you are, since that is the thing about to be needed.

from indepensense.sensors.tests.manual.magnetometer_calibrate import progress_line

SEGMENT = 10.0
LEAD = 2.0


def test_spinning_names_the_current_face():
    line = progress_line(0, 3.0, SEGMENT, LEAD, 47.0)

    assert "SPIN" in line
    assert "FRONT DOWN" in line


def test_the_changeover_names_the_next_face_not_the_current_one():
    """Where you are is no longer useful; where you are going is."""
    line = progress_line(0, 8.5, SEGMENT, LEAD, 47.0)

    assert "TURN" in line
    assert "BACK DOWN" in line
    assert "FRONT" not in line


def test_the_state_flips_exactly_at_the_lead():
    assert "SPIN" in progress_line(0, SEGMENT - LEAD - 0.1, SEGMENT, LEAD, 47.0)
    assert "TURN" in progress_line(0, SEGMENT - LEAD + 0.1, SEGMENT, LEAD, 47.0)


def test_the_changeover_counts_down_in_whole_seconds():
    """Matches the beeps, which are one per second — the digit and the
    sound have to agree or they fight each other."""
    assert progress_line(0, 8.0, SEGMENT, LEAD, 47.0).rstrip().endswith("2")
    assert progress_line(0, 9.0, SEGMENT, LEAD, 47.0).rstrip().endswith("1")


def test_the_last_face_never_shows_a_turn():
    """There is no seventh face. Prompting for one sends the user looking
    for an instruction that does not exist."""
    line = progress_line(5, 9.5, SEGMENT, LEAD, 47.0)

    assert "SPIN" in line
    assert "TURN" not in line


def test_the_bar_fills_across_the_face():
    assert "[..........]" in progress_line(0, 0.0, SEGMENT, LEAD, 47.0)
    assert "[#####.....]" in progress_line(0, 5.0, SEGMENT, LEAD, 47.0)


def test_every_frame_is_the_same_width():
    """Written with a carriage return, so a short frame must not leave the
    tail of a long one behind it."""
    frames = [
        progress_line(0, 1.0, SEGMENT, LEAD, 47.0),
        progress_line(0, 9.0, SEGMENT, LEAD, 47.0),      # the short TURN frame
        progress_line(2, 5.0, SEGMENT, LEAD, 123.4),
        progress_line(5, 9.9, SEGMENT, LEAD, 7.0),
    ]

    assert len({len(f) for f in frames}) == 1, [len(f) for f in frames]


def test_the_field_magnitude_is_shown_and_labelled_raw():
    """It swings wildly during an uncalibrated sweep — 16 to 68 uT on this
    project's own vest — which is the hard-iron offset being measured, not
    a fault. Labelling it stops that reading as alarming."""
    line = progress_line(0, 3.0, SEGMENT, LEAD, 47.3)

    assert "47.3" in line
    assert "raw" in line
