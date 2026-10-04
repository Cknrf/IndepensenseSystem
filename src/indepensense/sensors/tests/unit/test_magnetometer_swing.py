"""Unit tests for the horizontal ("swinging the compass") calibration.

The three-axis sweep could not be fitted on the assembled vest: 41.2%
spread from the per-axis model, and still 38.1% from a freely oriented
ellipsoid, which rules out the model and says the samples are not on an
ellipsoid at all. The sweep requires the vest tumbled onto every face,
and the magnetometer is mounted permanently upright on a vest that only
ever turns horizontally — so it failed on orientations the device never
experiences.

This fits the plane it does turn in. Two or three unknowns instead of
nine, which is the whole argument, and these tests check that the smaller
problem actually recovers what the bigger one could not.
"""
import math

import pytest

from indepensense.sensors.tests.manual.magnetometer_swing import (
    axis_aligned_from,
    fit_ellipse_2d,
    general_spread,
    spread_of,
)


def _turn(centre=(14.0, -6.0), radius=38.0, stretch=(1.0, 1.0),
          degrees=360.0, tilt=0.0, count=400):
    """One horizontal turn, optionally stretched and tilted (soft iron)."""
    points = []
    angle = math.radians(tilt)
    for i in range(count):
        theta = math.radians(degrees) * i / count
        u = radius * math.cos(theta) * stretch[0]
        v = radius * math.sin(theta) * stretch[1]
        points.append((centre[0] + u * math.cos(angle) - v * math.sin(angle),
                       centre[1] + u * math.sin(angle) + v * math.cos(angle)))
    return points


# --- hard iron, which is the common case ------------------------------------

def test_a_plain_offset_circle_is_recovered():
    centre, scales = axis_aligned_from(_turn(centre=(14.0, -6.0)))

    assert centre == pytest.approx((14.0, -6.0), abs=0.5)
    assert scales == pytest.approx((1.0, 1.0), abs=0.05)


def test_the_corrected_field_is_constant_around_the_turn():
    """The property the whole calibration exists to produce."""
    points = _turn(centre=(14.0, -6.0))
    centre, scales = axis_aligned_from(points)

    spread_pct, field = spread_of(points, centre, scales)

    assert spread_pct < 1.0
    assert field == pytest.approx(38.0, rel=0.05)


def test_an_offset_this_large_defeats_an_uncalibrated_heading():
    """Context for the numbers: the vest's measured offset is about
    two-thirds of the field, so leaving it uncorrected is not a small
    error."""
    points = _turn(centre=(24.6, 0.0), radius=35.6)

    raw = [math.hypot(u, v) for u, v in points]

    assert max(raw) / min(raw) > 4.0


# --- axis-aligned soft iron -------------------------------------------------

def test_a_stretched_circle_is_normalised():
    points = _turn(stretch=(1.0, 0.7))
    centre, scales = axis_aligned_from(points)

    assert scales[1] / scales[0] == pytest.approx(1.0 / 0.7, rel=0.05)
    assert spread_of(points, centre, scales)[0] < 1.0


# --- tilted soft iron, which the per-axis model cannot express --------------

def test_a_tilted_ellipse_defeats_the_per_axis_model():
    """And the 2x2 fit shows it, which is what tells the operator the
    printed values are not usable."""
    points = _turn(stretch=(1.0, 0.6), tilt=35.0)
    centre, scales = axis_aligned_from(points)

    per_axis = spread_of(points, centre, scales)[0]
    full = general_spread(points, fit_ellipse_2d(points))

    assert per_axis > 10.0
    assert full < 1.0


def test_an_untilted_ellipse_needs_no_more_than_the_per_axis_model():
    """The reassuring case — the gap between the two is what the operator
    is asked to read, so it must be small when the simple model suffices."""
    points = _turn(stretch=(1.0, 0.7))
    centre, scales = axis_aligned_from(points)

    per_axis = spread_of(points, centre, scales)[0]
    full = general_spread(points, fit_ellipse_2d(points))

    assert abs(per_axis - full) < 2.0


# --- refusing to answer -----------------------------------------------------

def test_a_partial_turn_still_fits_but_is_caught_upstream():
    """`main` gates on arc coverage before fitting. The fit itself is
    happy to extrapolate from half a circle, which is exactly why that
    gate exists rather than relying on the residual looking bad."""
    half = _turn(degrees=180.0)

    assert fit_ellipse_2d(half) is not None


def test_a_straight_line_is_not_an_ellipse():
    line = [(float(i), 2.0 * i) for i in range(100)]

    assert fit_ellipse_2d(line) is None


def test_too_few_points_to_fit():
    assert fit_ellipse_2d(_turn(count=10)) is None


def test_an_axis_that_never_moved_is_refused():
    flat = [(float(i) / 10.0, 5.0) for i in range(100)]

    assert axis_aligned_from(flat) is None
