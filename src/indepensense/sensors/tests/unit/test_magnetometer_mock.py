"""Unit tests for MockMagnetometer and heading conventions.

Nothing here touches real hardware — the mock is deterministic. These
tests lock down the compass-heading convention (0°=north, 90°=east)
so future refactors can't silently flip the sign.
"""
import math

import pytest

from indepensense.sensors.magnetometer import MockMagnetometer


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
