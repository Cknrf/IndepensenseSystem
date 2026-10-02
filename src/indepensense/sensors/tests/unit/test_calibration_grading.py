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
