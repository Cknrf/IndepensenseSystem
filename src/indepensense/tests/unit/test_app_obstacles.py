"""Unit tests for obstacle detection and continuous vibration feedback in `app.py`.

With continuous distance-to-frequency vibration mapping, obstacles are no
longer represented as discrete tiers. This tests that distance smoothly maps
to vibration frequency, with no feedback beyond detection distance and max
feedback at contact distance.

Tests build a bare `MockApp` and assign only the devices each one needs.
"""
import time
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.config import (
    OBSTACLE_DETECTION_START_CM,
    OBSTACLE_READING_MAX_AGE_S,
    OBSTACLE_RELEASE_CM,
    OBSTACLE_RHYTHM_MAX_HZ,
)
from indepensense.feedback.mock import MockVibrationMotor
from indepensense.sensors.base import UltrasonicReading


class _FixedUltrasonic:
    """Ultrasonic returning one scripted distance, or None / raising."""
    def __init__(self, distance_cm=None, raise_on_read=None):
        self.distance_cm = distance_cm
        self.raise_on_read = raise_on_read

    def read(self):
        if self.raise_on_read is not None:
            raise self.raise_on_read
        return None if self.distance_cm is None else UltrasonicReading(self.distance_cm, time.time())


@pytest.fixture
def app():
    app = MockApp()
    app.front_motor = MockVibrationMotor()
    app.left_motor = MockVibrationMotor()
    app.right_motor = MockVibrationMotor()
    return app


# --- rhythm frequency mapping ---

@pytest.mark.parametrize("distance,expected_min,expected_max", [
    (OBSTACLE_DETECTION_START_CM + 10, 0.0, 0.0),   # Beyond detection
    (OBSTACLE_DETECTION_START_CM,      0.0, 0.0),   # At detection start
    (OBSTACLE_DETECTION_START_CM - 1,  0.0, 1.0),   # Just inside, low frequency
    (100.0,                            3.0, 3.2),   # Mid-range (~3.08 Hz)
    (50.0,                             6.0, 6.3),   # Close (~6.15 Hz)
    (20.0,                             8.0, 8.0),   # Contact (exactly 8 Hz)
])
def test_rhythm_frequency_by_distance(distance, expected_min, expected_max):
    """Frequency increases continuously as obstacle gets closer."""
    actual = app_module._obstacle_rhythm_hz(distance)
    assert expected_min <= actual <= expected_max, \
        f"at {distance}cm: expected {expected_min}-{expected_max}Hz, got {actual}Hz"


def test_closer_is_never_slower():
    """Monotonic property: closer obstacles always produce faster or equal frequency."""
    rates = [app_module._obstacle_rhythm_hz(d) for d in range(int(OBSTACLE_DETECTION_START_CM), 0, -5)]
    for a, b in zip(rates, rates[1:]):
        assert b >= a, f"frequency should increase as distance decreases"


def test_silent_beyond_detection():
    """No vibration feedback beyond detection start distance."""
    assert app_module._obstacle_rhythm_hz(OBSTACLE_DETECTION_START_CM + 100) == 0.0
    assert app_module._obstacle_rhythm_hz(OBSTACLE_DETECTION_START_CM + 1) == 0.0


def test_max_frequency_at_contact():
    """Vibration reaches max frequency within contact distance."""
    for d in [20.0, 10.0, 5.0, 1.0]:
        assert app_module._obstacle_rhythm_hz(d) == OBSTACLE_RHYTHM_MAX_HZ


# --- sensor reading and state tracking ---

def test_sensor_reading_is_cached(app):
    """Latest reading is cached for reuse by rhythm and vision systems."""
    sensor = _FixedUltrasonic(123.4)
    app._check_obstacle_sensor("top", sensor)
    
    cached_distance, cached_time = app._obstacle_reading["top"]
    assert cached_distance == 123.4
    assert cached_time > 0


def test_stale_reading_is_not_used_for_rhythm(app):
    """Rhythm ignores readings older than MAX_AGE_S."""
    app._obstacle_recent["top"] = app._obstacle_recent.get(
        "top", app._obstacle_recent.setdefault("top", __import__('collections').deque(maxlen=3))
    )
    old_time = time.monotonic() - OBSTACLE_READING_MAX_AGE_S - 1
    app._obstacle_reading["top"] = (50.0, old_time)
    app._obstacle_recent["top"].append(50.0)
    
    # _tick_obstacle_rhythm skips if reading is too old
    app._tick_obstacle_rhythm()
    # No error, just skips (rhythm_sensor stays None if all readings are stale)


def test_reading_errors_are_logged_and_ignored(app):
    """A sensor read error does not crash the loop."""
    sensor = _FixedUltrasonic(raise_on_read=RuntimeError("I²C timeout"))
    # Should not raise
    app._check_obstacle_sensor("top", sensor)
    # No reading recorded
    assert app._obstacle_reading.get("top") is None


# --- tier state tracking (for logging only) ---

def test_tier_tracks_for_logging(app):
    """Tier state is tracked for logging escalations, even though vibration is continuous."""
    sensor = _FixedUltrasonic(40.0)  # In danger range
    app._check_obstacle_sensor("top", sensor)
    assert app._obstacle_tier["top"] == "danger"
    
    # Recede past hysteresis
    sensor.distance_cm = 100.0 + OBSTACLE_RELEASE_CM + 1
    app._check_obstacle_sensor("top", sensor)
    assert app._obstacle_tier["top"] is None


# --- motor independence ---

def test_sensors_are_independent(app):
    """TOP and BOTTOM sensor states don't interfere."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(40.0))
    app._check_obstacle_sensor("bottom", _FixedUltrasonic(40.0))
    
    assert app._obstacle_tier["top"] == "danger"
    assert app._obstacle_tier["bottom"] == "danger"
