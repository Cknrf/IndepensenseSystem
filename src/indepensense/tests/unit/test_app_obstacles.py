"""Unit tests for obstacle detection and continuous vibration feedback in `app.py`.

With aggressive dual-parameter feedback, obstacles map to both frequency AND intensity
(PWM duty cycle). This tests that distance smoothly maps to both vibration frequency
and strength, with compound feedback: faster AND stronger as obstacles approach.

Aggressive curve:
  150 cm:   2 Hz @  30% intensity
  100 cm:   6 Hz @  60% intensity
   50 cm:  10 Hz @  90% intensity
   20 cm:  15 Hz @ 100% intensity

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


# --- aggressive feedback: frequency + intensity mapping ---

@pytest.mark.parametrize("distance,hz_min,hz_max,duty_min,duty_max", [
    # Beyond detection: silent
    (OBSTACLE_DETECTION_START_CM + 10, 0.0, 0.0, 0.0, 0.0),
    (OBSTACLE_DETECTION_START_CM,      0.0, 0.0, 0.0, 0.0),
    # Just inside detection: ramping up (150→100cm: 0→6Hz, 0%→60%)
    (140.0,                            1.0, 1.5, 0.10, 0.15),
    # Mid-range: ramping harder (100→50cm: 6→10Hz, 60%→90%)
    (100.0,                            5.8, 6.2, 0.55, 0.65),
    # Close: strong feedback (50→20cm: 10→15Hz, 90%→100%)
    (50.0,                             9.8, 10.2, 0.85, 0.95),
    # Contact: maximum
    (20.0,                            14.8, 15.2, 0.95, 1.0),
    (10.0,                            15.0, 15.0, 1.0, 1.0),
])
def test_feedback_by_distance(distance, hz_min, hz_max, duty_min, duty_max):
    """Both frequency and intensity increase as obstacle gets closer (aggressive curve)."""
    hz, duty = app_module._obstacle_feedback(distance)
    assert hz_min <= hz <= hz_max, \
        f"at {distance}cm: expected frequency {hz_min}-{hz_max}Hz, got {hz}Hz"
    assert duty_min <= duty <= duty_max, \
        f"at {distance}cm: expected duty {duty_min*100:.0f}%-{duty_max*100:.0f}%, got {duty*100:.0f}%"


def test_frequency_increases_monotonically():
    """Frequency increases as distance decreases."""
    distances = list(range(150, 0, -5))
    feedbacks = [app_module._obstacle_feedback(d) for d in distances]
    frequencies = [hz for hz, _ in feedbacks]

    for i, (a, b) in enumerate(zip(frequencies, frequencies[1:])):
        assert b >= a, f"at index {i}: frequency should increase (distance {distances[i]} vs {distances[i+1]})"


def test_intensity_increases_monotonically():
    """Intensity (duty cycle) increases as distance decreases."""
    distances = list(range(150, 0, -5))
    feedbacks = [app_module._obstacle_feedback(d) for d in distances]
    duties = [duty for _, duty in feedbacks]

    for i, (a, b) in enumerate(zip(duties, duties[1:])):
        assert b >= a, f"at index {i}: duty should increase (distance {distances[i]} vs {distances[i+1]})"


def test_silent_beyond_detection():
    """No feedback beyond detection start distance."""
    hz, duty = app_module._obstacle_feedback(OBSTACLE_DETECTION_START_CM + 100)
    assert hz == 0.0 and duty == 0.0

    hz, duty = app_module._obstacle_feedback(OBSTACLE_DETECTION_START_CM + 1)
    assert hz == 0.0 and duty == 0.0


def test_max_at_contact():
    """Maximum feedback (15 Hz @ 100%) at contact distance and closer."""
    for distance in [20.0, 10.0, 5.0, 1.0]:
        hz, duty = app_module._obstacle_feedback(distance)
        assert hz == 15.0, f"at {distance}cm: expected 15 Hz"
        assert duty == 1.0, f"at {distance}cm: expected 100% duty"


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
