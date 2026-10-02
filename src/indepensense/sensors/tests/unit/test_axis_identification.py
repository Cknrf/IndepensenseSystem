"""Unit tests for mount-axis identification.

Determining `MAG_FORWARD_AXIS` / `MAG_LEFT_AXIS` by watching a live
readout is hard to do alone and easy to get wrong — the first attempt on
this project's own vest produced spans of y=35 against x=82, z=82. The
right answer (y is vertical), reached by a motion sloppy enough that it
could as easily have been the wrong one.

Both decisions are pure functions over samples, so synthetic turns with
known geometry can test them here. Getting the signs wrong mirrors the
heading, which no offset can correct and which reads plausibly while
sending the user the wrong way.
"""
import math

import pytest

from indepensense.sensors.tests.manual.magnetometer_axes import (
    choose_signs,
    find_vertical_axis,
)

EARTH_UT = 45.0
DIP_UT = 15.0        # vertical component; Luzon's inclination is shallow


def _turn(vertical: str, degrees=360.0, count=200, tilt_deg=0.0,
          clockwise=True, offset=(0.0, 0.0, 0.0)):
    """Samples from turning on the spot with `vertical` pointing up.

    The two horizontal axes trace a circle; the vertical one holds the
    dip component. `tilt_deg` wobbles the vest to simulate a sloppy turn.
    """
    order = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}[vertical]
    samples = []
    for i in range(count):
        frac = i / (count - 1)
        angle = math.radians(degrees * frac * (1.0 if clockwise else -1.0))
        wobble = math.radians(tilt_deg) * math.sin(frac * 6.0)
        values = {
            order[0]: EARTH_UT * math.cos(angle),
            order[1]: EARTH_UT * math.sin(angle),
            vertical: DIP_UT + EARTH_UT * math.sin(wobble),
        }
        samples.append(tuple(
            values[a] + offset[i] for i, a in enumerate("xyz")
        ))
    return samples


# --- which axis is vertical --------------------------------------------------

@pytest.mark.parametrize("vertical", ["x", "y", "z"])
def test_a_clean_turn_identifies_the_vertical_axis(vertical):
    quiet, _spans, ratio = find_vertical_axis(_turn(vertical))

    assert quiet == vertical
    assert ratio < 0.35, ratio


def test_hard_iron_does_not_change_which_axis_is_vertical():
    """The whole point of doing this before calibration: a large constant
    offset shifts every axis but changes no span."""
    quiet, _spans, ratio = find_vertical_axis(
        _turn("y", offset=(120.0, -80.0, 60.0))
    )

    assert quiet == "y"
    assert ratio < 0.35


def test_a_tilted_turn_is_flagged_rather_than_guessed():
    """Tilting while turning moves the vertical axis too, so 'smallest
    span' becomes a coin toss. The measured 0.43 from the project's own
    first attempt sits in exactly this band."""
    _quiet, _spans, ratio = find_vertical_axis(_turn("y", tilt_deg=35.0))

    assert ratio > 0.35, ratio


def test_a_tumble_is_flagged():
    """All three axes sweeping fully is not a turn on the spot at all."""
    samples = []
    for i in range(200):
        a, b = i * 0.21, i * 0.13
        samples.append((
            EARTH_UT * math.cos(a) * math.cos(b),
            EARTH_UT * math.sin(a),
            EARTH_UT * math.cos(a) * math.sin(b),
        ))

    _quiet, _spans, ratio = find_vertical_axis(samples)

    assert ratio > 0.35, ratio


# --- which way round the axes go ---------------------------------------------

def test_a_rightward_turn_yields_an_increasing_heading():
    """The safety-critical half. A mirrored compass cannot be corrected
    by any offset."""
    samples = _turn("y", degrees=120.0, clockwise=True)

    forward, left, turned, _candidates = choose_signs(samples, ("x", "z"))

    assert forward is not None and left is not None
    assert turned > 0


def test_the_chosen_signs_actually_increase_the_heading():
    from indepensense.sensors.tests.manual.magnetometer_axes import _total_turn

    samples = _turn("y", degrees=120.0, clockwise=True)
    forward, left, _turned, _candidates = choose_signs(samples, ("x", "z"))

    assert _total_turn(samples, forward, left) > 0


def test_a_leftward_turn_picks_the_opposite_convention():
    """Same physical mount, opposite motion — the tool must not simply
    pick a fixed answer."""
    right = _turn("y", degrees=120.0, clockwise=True)
    left_turn = _turn("y", degrees=120.0, clockwise=False)

    right_choice = choose_signs(right, ("x", "z"))[:2]
    left_choice = choose_signs(left_turn, ("x", "z"))[:2]

    assert right_choice != left_choice


def test_the_surviving_candidates_are_reported_not_hidden():
    """Four combinations turn the right way and differ only by whole 90°
    steps. Separating them needs a bearing from outside the device, so
    claiming one would be inventing it."""
    samples = _turn("y", degrees=120.0, clockwise=True)

    _f, _l, _t, candidates = choose_signs(samples, ("x", "z"))

    assert len(candidates) == 4
    assert all(turned > 0 for _f, _l, turned in candidates)


def test_standing_still_establishes_nothing():
    """A vest that never turned cannot say which way round anything goes."""
    samples = _turn("y", degrees=0.0, count=50)

    _f, _l, turned, _candidates = choose_signs(samples, ("x", "z"))

    assert abs(turned) < 40.0


def test_a_turn_past_180_degrees_is_not_read_as_a_turn_the_other_way():
    """Accumulating shortest-path steps rather than comparing first to
    last — otherwise 270° right reads as 90° left."""
    samples = _turn("y", degrees=270.0, clockwise=True)

    _f, _l, turned, _candidates = choose_signs(samples, ("x", "z"))

    assert turned > 200.0, turned
