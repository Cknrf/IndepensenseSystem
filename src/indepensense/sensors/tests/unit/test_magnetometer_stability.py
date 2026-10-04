"""Unit tests for the magnetometer stability checks.

The sweep that prompted this had every geometric problem fixed — full
turns, balanced half-spans, a correct 42 uT field, a location verified
uniform — and still could not be fitted, by the per-axis model (41.2%
spread) or by a freely oriented ellipsoid (38.1%). That rules out the
calibration model and points at the measurement.

The two pure functions here are what decide between the two remaining
explanations, so they are worth testing without a vest attached.
"""
import pytest

from indepensense.sensors.tests.manual.magnetometer_stability import (
    axis_means,
    axis_spreads,
    separation,
)


def test_a_stationary_sensor_shows_almost_no_spread():
    steady = [(30.0, -12.0, 40.0)] * 50

    assert axis_spreads(steady) == (0.0, 0.0, 0.0)


def test_spread_is_peak_to_peak_not_an_average():
    """One excursion is the whole point: a sensor that jumped once is not
    steady, and an average over 300 samples would hide it."""
    samples = [(30.0, 0.0, 0.0)] * 99 + [(36.0, 0.0, 0.0)]

    assert axis_spreads(samples)[0] == pytest.approx(6.0)


def test_spread_is_reported_per_axis():
    """Interference rarely arrives equally on all three, and which axis
    moved is a clue about where it came from."""
    samples = [(30.0, 0.0, 0.0), (30.0, 4.0, 0.0), (30.0, 0.0, 0.0)]

    x, y, z = axis_spreads(samples)
    assert (x, z) == (0.0, 0.0)
    assert y == pytest.approx(4.0)


def test_returning_to_the_same_orientation_reads_the_same():
    first = [(30.0, -12.0, 40.0)] * 20
    again = [(30.2, -11.8, 40.1)] * 20

    assert separation(first, again) < 1.0


def test_a_shifted_component_shows_as_separation():
    """The failure this is built to catch: something magnetic moved when
    the vest was turned over and did not come back, so the offset is a
    function of orientation rather than one number."""
    first = [(30.0, -12.0, 40.0)] * 20
    again = [(30.0, -12.0, 46.0)] * 20

    assert separation(first, again) == pytest.approx(6.0)


def test_separation_uses_the_whole_vector_not_the_magnitude():
    """Two fields of equal strength pointing different ways are a moved
    component, and comparing magnitudes alone would call them identical."""
    first = [(40.0, 0.0, 0.0)] * 20
    again = [(0.0, 40.0, 0.0)] * 20

    assert separation(first, again) == pytest.approx(40.0 * 2 ** 0.5)
    assert axis_means(first) != axis_means(again)
