"""Unit tests for turn-to-face decision logic.

Pure arithmetic — no compass, no motors, no threads. The app-side loop
that reads the sensor and fires the motor is covered in
`tests/unit/test_app_orientation.py`.

The properties worth locking down are the ones whose failure would be
invisible in a demo and wrong in the street: taking the long way round a
turn, oscillating at the tolerance boundary, and dropping a bearing of
exactly zero.
"""
import pytest

from indepensense.navigation.orientation import (
    OrientationGuide,
    first_meaningful_point,
    heading_error,
)
from indepensense.routing.base import Coordinate, bearing_to

LIPA = Coordinate(lat=13.9411, lon=121.1622)


# --- bearing -----------------------------------------------------------------

def test_due_north_is_zero_degrees():
    north = Coordinate(lat=LIPA.lat + 0.01, lon=LIPA.lon)
    assert bearing_to(LIPA, north) == pytest.approx(0.0, abs=0.5)


def test_due_east_is_ninety_degrees():
    east = Coordinate(lat=LIPA.lat, lon=LIPA.lon + 0.01)
    assert bearing_to(LIPA, east) == pytest.approx(90.0, abs=0.5)


def test_due_south_is_one_eighty():
    south = Coordinate(lat=LIPA.lat - 0.01, lon=LIPA.lon)
    assert bearing_to(LIPA, south) == pytest.approx(180.0, abs=0.5)


def test_due_west_is_two_seventy():
    west = Coordinate(lat=LIPA.lat, lon=LIPA.lon - 0.01)
    assert bearing_to(LIPA, west) == pytest.approx(270.0, abs=0.5)


def test_bearing_is_always_in_range():
    """Fed to GraphHopper and subtracted from a compass reading; a negative
    value would break both."""
    for d_lat, d_lon in ((0.01, 0.01), (-0.01, 0.01), (0.01, -0.01), (-0.01, -0.01)):
        bearing = bearing_to(
            LIPA, Coordinate(lat=LIPA.lat + d_lat, lon=LIPA.lon + d_lon)
        )
        assert 0.0 <= bearing < 360.0


# --- heading error -----------------------------------------------------------

def test_no_error_when_already_facing_the_target():
    assert heading_error(90.0, 90.0) == pytest.approx(0.0)


def test_a_rightward_turn_is_positive():
    assert heading_error(0.0, 90.0) == pytest.approx(90.0)


def test_a_leftward_turn_is_negative():
    assert heading_error(90.0, 0.0) == pytest.approx(-90.0)


def test_the_short_way_round_is_chosen_across_north():
    """Facing 350 and needing 10 is a 20 degree turn right, not 340 left.
    A user told to turn 340 degrees would stop trusting the device."""
    assert heading_error(350.0, 10.0) == pytest.approx(20.0)


def test_the_short_way_round_is_chosen_the_other_way():
    assert heading_error(10.0, 350.0) == pytest.approx(-20.0)


def test_the_error_never_exceeds_a_half_turn():
    for current in range(0, 360, 7):
        for target in range(0, 360, 11):
            assert -180.0 <= heading_error(current, target) < 180.0


def test_facing_exactly_backwards_picks_one_side_and_stays():
    """Either direction is equally correct at 180 degrees. Picking one
    deterministically stops the cue flickering on a degree of noise."""
    assert heading_error(0.0, 180.0) == pytest.approx(-180.0)
    assert heading_error(0.0, 180.0) == heading_error(0.0, 180.0)


# --- cues --------------------------------------------------------------------

def test_within_tolerance_is_aligned():
    assert OrientationGuide().cue(95.0, 90.0).aligned is True


def test_outside_tolerance_names_the_side_to_turn():
    cue = OrientationGuide().cue(0.0, 90.0)
    assert cue.aligned is False
    assert cue.direction == "right"


def test_a_leftward_error_pulses_the_left_side():
    assert OrientationGuide().cue(90.0, 0.0).direction == "left"


def test_pulses_get_faster_as_the_user_comes_round():
    """The whole interaction rests on this being perceptible: turn until
    the buzzing speeds up, then stop."""
    guide = OrientationGuide()
    far = guide.cue(0.0, 170.0).pulse_interval_s
    middle = guide.cue(0.0, 60.0).pulse_interval_s
    near = guide.cue(0.0, 25.0).pulse_interval_s

    assert far > middle > near


def test_an_aligned_cue_carries_no_direction_or_interval():
    cue = OrientationGuide().cue(90.0, 90.0)
    assert cue.direction is None
    assert cue.pulse_interval_s is None


def test_a_bearing_of_zero_is_honoured():
    """Due north is a real target. Anything treating 0 as "no bearing"
    would silently skip guidance for every northward route."""
    cue = OrientationGuide().cue(90.0, 0.0)
    assert cue.aligned is False
    assert cue.direction == "left"


# --- hysteresis --------------------------------------------------------------

def test_alignment_is_sticky_within_the_release_band():
    """A user who drifts a few degrees past the boundary must not be told
    to turn back, or they oscillate and the device nags somebody who is
    already pointing the right way."""
    guide = OrientationGuide(
        aligned_tolerance_deg=15.0, release_tolerance_deg=30.0,
    )
    assert guide.cue(90.0, 90.0).aligned is True

    assert guide.cue(70.0, 90.0).aligned is True      # 20° out, was not enough before


def test_drifting_past_the_release_band_starts_guiding_again():
    guide = OrientationGuide(
        aligned_tolerance_deg=15.0, release_tolerance_deg=30.0,
    )
    guide.cue(90.0, 90.0)

    cue = guide.cue(40.0, 90.0)       # 50° out — genuinely turned away
    assert cue.aligned is False
    assert cue.direction == "right"


def test_the_widened_band_does_not_apply_before_first_alignment():
    """Starting 20 degrees out should still be guided, not waved through."""
    guide = OrientationGuide(
        aligned_tolerance_deg=15.0, release_tolerance_deg=30.0,
    )
    assert guide.cue(70.0, 90.0).aligned is False


def test_has_aligned_reports_the_latch():
    guide = OrientationGuide()
    assert guide.has_aligned is False
    guide.cue(90.0, 90.0)
    assert guide.has_aligned is True


def test_a_release_band_tighter_than_the_aligned_band_is_rejected():
    """It would invert the hysteresis and cause the oscillation it exists
    to prevent."""
    with pytest.raises(ValueError):
        OrientationGuide(aligned_tolerance_deg=30.0, release_tolerance_deg=15.0)


# --- picking a target --------------------------------------------------------

def test_the_first_point_far_enough_away_is_chosen():
    """A point two metres ahead gives a bearing that swings with GPS
    jitter, and acting on it would spin the user on the spot."""
    near = Coordinate(lat=LIPA.lat + 0.00002, lon=LIPA.lon)     # ~2 m
    far = Coordinate(lat=LIPA.lat + 0.0005, lon=LIPA.lon)       # ~55 m

    assert first_meaningful_point([near, far], LIPA, 15.0) is far


def test_a_short_route_falls_back_to_its_last_point():
    """Every point is closer than the threshold, so any bearing is about as
    good as any other — but there must still be one."""
    a = Coordinate(lat=LIPA.lat + 0.00002, lon=LIPA.lon)
    b = Coordinate(lat=LIPA.lat + 0.00004, lon=LIPA.lon)

    assert first_meaningful_point([a, b], LIPA, 15.0) is b


def test_an_empty_polyline_has_no_target():
    assert first_meaningful_point([], LIPA, 15.0) is None
