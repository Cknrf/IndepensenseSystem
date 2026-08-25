"""Unit tests for MockMagnetometer and heading conventions.

Nothing here touches real hardware — the mock is deterministic. These
tests lock down the compass-heading convention (0°=north, 90°=east)
so future refactors can't silently flip the sign. The convention itself
lives in `sensors/base.heading_from_field`, shared by the mock and the
QMC5883P driver, so exercising it through the mock covers both.
"""
import math

import pytest

from indepensense.sensors.base import axis_component, heading_from_field
from indepensense.sensors.mock import MockMagnetometer


def test_default_heading_is_zero():
    m = MockMagnetometer()
    r = m.read()
    assert r is not None
    assert r.heading_deg == pytest.approx(0.0)


def test_north_is_zero_degrees():
    """0° = north = X-axis positive, Y = 0."""
    m = MockMagnetometer(heading_deg=0.0, magnitude_ut=50.0)
    r = m.read()
    assert r.magnetic_x == pytest.approx(50.0)
    assert r.magnetic_y == pytest.approx(0.0, abs=1e-6)


def test_east_is_ninety_degrees():
    """90° = east = X=0, Y positive."""
    m = MockMagnetometer(heading_deg=90.0, magnitude_ut=50.0)
    r = m.read()
    assert r.magnetic_x == pytest.approx(0.0, abs=1e-6)
    assert r.magnetic_y == pytest.approx(50.0)


def test_south_is_180_degrees():
    m = MockMagnetometer(heading_deg=180.0, magnitude_ut=50.0)
    r = m.read()
    assert r.magnetic_x == pytest.approx(-50.0)
    assert r.magnetic_y == pytest.approx(0.0, abs=1e-6)


def test_west_is_270_degrees():
    m = MockMagnetometer(heading_deg=270.0, magnitude_ut=50.0)
    r = m.read()
    assert r.magnetic_x == pytest.approx(0.0, abs=1e-6)
    assert r.magnetic_y == pytest.approx(-50.0)


def test_set_heading_updates_reading():
    m = MockMagnetometer(heading_deg=0.0)
    m.set_heading(180.0)
    r = m.read()
    assert r.heading_deg == pytest.approx(180.0)


def test_heading_wraps_at_360():
    m = MockMagnetometer(heading_deg=450.0)   # 450 mod 360 = 90
    r = m.read()
    assert r.heading_deg == pytest.approx(90.0)


def test_heading_wraps_for_negative_input():
    m = MockMagnetometer(heading_deg=-90.0)   # equivalent to 270
    r = m.read()
    assert r.heading_deg == pytest.approx(270.0)


def test_close_flips_state():
    m = MockMagnetometer()
    assert m.closed is False
    m.close()
    assert m.closed is True


def test_computed_heading_from_x_y_matches_stored():
    """The Reading's heading_deg should match atan2(y, x) of the raw field.
    Guards against internal state drifting away from the reported value."""
    m = MockMagnetometer(heading_deg=137.0)
    r = m.read()
    computed = math.degrees(math.atan2(r.magnetic_y, r.magnetic_x)) % 360.0
    assert computed == pytest.approx(r.heading_deg, abs=1e-6)


# --- the shared convention, tested directly --------------------------------


@pytest.mark.parametrize(
    "x, y, expected",
    [
        (50.0, 0.0, 0.0),      # north
        (0.0, 50.0, 90.0),     # east
        (-50.0, 0.0, 180.0),   # south
        (0.0, -50.0, 270.0),   # west
        (50.0, 50.0, 45.0),    # north-east
    ],
)
def test_heading_from_field_cardinal_directions(x, y, expected):
    assert heading_from_field(x, y) == pytest.approx(expected)


def test_heading_from_field_never_returns_negative():
    """atan2 returns -180..180; the compass contract is 0..360. A negative
    heading leaking through would break any consumer doing arithmetic on it."""
    for x, y in [(-1.0, -1.0), (1.0, -1.0), (-1.0, -0.001)]:
        assert 0.0 <= heading_from_field(x, y) < 360.0


def test_heading_from_field_is_magnitude_independent():
    """Only direction matters — a weak field and a strong one pointing the
    same way must give the same heading."""
    assert heading_from_field(1.0, 1.0) == pytest.approx(heading_from_field(500.0, 500.0))


# --- mount orientation: axis selection ------------------------------------


_FIELD = (10.0, 20.0, 30.0)


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("x", 10.0), ("+x", 10.0), ("-x", -10.0),
        ("y", 20.0), ("+y", 20.0), ("-y", -20.0),
        ("z", 30.0), ("+z", 30.0), ("-z", -30.0),
        ("X", 10.0), ("-Z", -30.0),      # case-insensitive
    ],
)
def test_axis_component_selects_and_signs(spec, expected):
    assert axis_component(_FIELD, spec) == pytest.approx(expected)


@pytest.mark.parametrize("spec", ["", "w", "xx", "+", "-", "xy", "0", "+w", "--x"])
def test_axis_component_rejects_bad_specs(spec):
    """A typo in config.py must fail loudly. Silently defaulting to an axis
    would mirror or rotate every heading the wearable ever reports."""
    with pytest.raises(ValueError):
        axis_component(_FIELD, spec)


def test_flat_mount_reproduces_the_original_convention():
    """Board flat: x forward, y left — the hard-coded behaviour this replaced.
    Field pointing along +x is north."""
    field = (50.0, 0.0, 0.0)
    heading = heading_from_field(
        axis_component(field, "+x"), axis_component(field, "+y")
    )
    assert heading == pytest.approx(0.0)


def test_upright_mount_uses_z_and_x():
    """Board upright on a vest back: z is horizontal (front/back), y is
    vertical and must not reach the heading at all. Here the field points
    along +z, i.e. straight ahead, so heading is north despite a large
    vertical component on y."""
    field = (0.0, 999.0, 50.0)
    heading = heading_from_field(
        axis_component(field, "+z"), axis_component(field, "-x")
    )
    assert heading == pytest.approx(0.0)


def test_a_flipped_sign_mirrors_the_heading():
    """Why the sign is configurable and not inferred: getting it wrong is not
    a rotation, it is a reflection, so no heading offset can repair it."""
    field = (30.0, 40.0, 0.0)
    correct = heading_from_field(
        axis_component(field, "+x"), axis_component(field, "+y")
    )
    flipped = heading_from_field(
        axis_component(field, "+x"), axis_component(field, "-y")
    )
    assert flipped == pytest.approx((360.0 - correct) % 360.0)
