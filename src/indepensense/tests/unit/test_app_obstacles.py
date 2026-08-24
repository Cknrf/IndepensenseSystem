"""Unit tests for obstacle tiering and warning feedback in `app.py`.

This is the code that runs 100 times a second on the real device and
decides whether the user gets warned about something in their path. It
had no automated coverage until now.

Tests build a bare `MockApp` and assign only the devices each one needs,
rather than calling `start()`. That keeps them fast and focused: `start()`
loads models, attempts a guardian fetch and opens a dozen devices, none of
which this logic touches.

Cooldown timing is asserted by writing `_obstacle_last_fired` directly.
The method reads `time.monotonic()` with no seam to inject, and adding one
purely for tests would be worse than reaching in — the dict *is* the
cooldown state, so a test that sets it is describing the same thing the
production code does.
"""
import time

import pytest

from indepensense.app_mock import MockApp
from indepensense.config import (
    OBSTACLE_COOLDOWN_S,
    OBSTACLE_DANGER_CM,
    OBSTACLE_WARNING_CM,
)
from indepensense.feedback.mock import MockBuzzer, MockVibrationMotor
from indepensense.sensors.base import UltrasonicReading


class _FixedUltrasonic:
    """Ultrasonic returning one scripted distance, or None / raising."""

    def __init__(self, distance_cm=None, raise_on_read=False):
        self._distance_cm = distance_cm
        self._raise = raise_on_read
        self.read_count = 0

    def read(self):
        self.read_count += 1
        if self._raise:
            raise OSError("simulated UART failure")
        if self._distance_cm is None:
            return None
        return UltrasonicReading(distance_cm=self._distance_cm, timestamp=time.time())

    def close(self):
        pass


@pytest.fixture
def app():
    """A MockApp with feedback devices attached but nothing started."""
    instance = MockApp()
    instance.buzzer = MockBuzzer()
    instance.front_motor = MockVibrationMotor()
    instance.left_motor = MockVibrationMotor()
    instance.right_motor = MockVibrationMotor()
    return instance


def _wait_for(condition, timeout_s=2.0):
    """Warning patterns play on a background thread."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return False


# --- tiering -----------------------------------------------------------------

def test_safe_distance_fires_nothing(app):
    sensor = _FixedUltrasonic(OBSTACLE_WARNING_CM + 50)
    app._check_obstacle_sensor("top", sensor)

    assert app._obstacle_last_fired == {}
    time.sleep(0.05)
    assert app.buzzer.events == []
    assert app.front_motor.events == []


def test_warning_zone_fires_the_warning_tier(app):
    sensor = _FixedUltrasonic((OBSTACLE_WARNING_CM + OBSTACLE_DANGER_CM) / 2)
    app._check_obstacle_sensor("top", sensor)
    assert "top:warning" in app._obstacle_last_fired


def test_danger_zone_fires_the_danger_tier(app):
    sensor = _FixedUltrasonic(OBSTACLE_DANGER_CM - 10)
    app._check_obstacle_sensor("top", sensor)
    assert "top:danger" in app._obstacle_last_fired
    assert "top:warning" not in app._obstacle_last_fired


def test_the_threshold_itself_is_the_safe_side(app):
    """Thresholds are exclusive (`distance < OBSTACLE_WARNING_CM`), so a
    reading exactly at 100 cm is safe. Pinning this stops a later
    refactor flipping it silently."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_WARNING_CM))
    assert app._obstacle_last_fired == {}

    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_DANGER_CM))
    assert "top:warning" in app._obstacle_last_fired
    assert "top:danger" not in app._obstacle_last_fired


# --- non-readings ------------------------------------------------------------

def test_absent_sensor_is_a_no_op(app):
    app._check_obstacle_sensor("top", None)
    assert app._obstacle_last_fired == {}


def test_no_fresh_frame_is_a_no_op(app):
    """At 100 Hz against a ~10 Hz sensor, 9 of 10 reads return None. This
    is the common case, not an edge case."""
    sensor = _FixedUltrasonic(None)
    app._check_obstacle_sensor("top", sensor)
    assert sensor.read_count == 1
    assert app._obstacle_last_fired == {}


def test_a_raising_sensor_does_not_propagate(app):
    """A bad UART read must not take down the main loop — obstacle
    detection has to survive a transient glitch."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(raise_on_read=True))
    assert app._obstacle_last_fired == {}


# --- cooldown ----------------------------------------------------------------

def test_cooldown_suppresses_a_repeat_in_the_same_tier(app):
    sensor = _FixedUltrasonic(OBSTACLE_DANGER_CM - 10)
    app._check_obstacle_sensor("top", sensor)
    first = app._obstacle_last_fired["top:danger"]

    app._check_obstacle_sensor("top", sensor)
    assert app._obstacle_last_fired["top:danger"] == first


def test_cooldown_expires(app):
    sensor = _FixedUltrasonic(OBSTACLE_DANGER_CM - 10)
    app._check_obstacle_sensor("top", sensor)

    # Backdate past the cooldown window.
    app._obstacle_last_fired["top:danger"] -= OBSTACLE_COOLDOWN_S + 1
    stale = app._obstacle_last_fired["top:danger"]

    app._check_obstacle_sensor("top", sensor)
    assert app._obstacle_last_fired["top:danger"] > stale


def test_crossing_into_danger_is_not_blocked_by_a_warning_cooldown(app):
    """The safety-critical case: an obstacle approaching fast must get its
    danger warning immediately, even though a warning fired moments ago.
    Cooldowns are keyed per (sensor, tier) precisely for this."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_WARNING_CM - 5))
    assert "top:warning" in app._obstacle_last_fired

    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_DANGER_CM - 5))
    assert "top:danger" in app._obstacle_last_fired


def test_cooldowns_are_independent_per_sensor(app):
    """TOP and BOTTOM watch different parts of the world; one firing must
    not mute the other."""
    close = OBSTACLE_DANGER_CM - 10
    app._check_obstacle_sensor("top", _FixedUltrasonic(close))
    app._check_obstacle_sensor("bottom", _FixedUltrasonic(close))

    assert "top:danger" in app._obstacle_last_fired
    assert "bottom:danger" in app._obstacle_last_fired


# --- feedback patterns -------------------------------------------------------

def test_top_warning_beeps_and_pulses_front(app):
    """TOP is the wearable's unique value — the cane cannot sweep head
    height — so its warnings are audible as well as haptic."""
    app._play_warning_pattern("top", "warning")

    assert any(e[0] == "beep" for e in app.buzzer.events)
    assert any(e[0] == "pulse" for e in app.front_motor.events)


def test_top_danger_uses_all_motors_and_two_beeps(app):
    app._play_warning_pattern("top", "danger")

    beeps = [e for e in app.buzzer.events if e[0] == "beep"]
    assert beeps and beeps[0][1] == 2
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events, "all three motors should fire on danger"


def test_bottom_warning_is_silent(app):
    """The user's cane already finds curbs by touch. Beeping about them
    would nag without adding information."""
    app._play_warning_pattern("bottom", "warning")

    assert app.buzzer.events == []
    assert any(e[0] == "pulse" for e in app.front_motor.events)


def test_bottom_danger_is_silent_but_uses_all_motors(app):
    app._play_warning_pattern("bottom", "danger")

    assert app.buzzer.events == []
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events


def test_missing_actuators_do_not_raise(app):
    """Running with a buzzer that failed to open must degrade, not crash."""
    app.buzzer = None
    app.front_motor = None
    app._play_warning_pattern("top", "warning")
    app._play_warning_pattern("top", "danger")


def test_a_raising_actuator_is_contained(app):
    class _BrokenBuzzer(MockBuzzer):
        def beep(self, *args, **kwargs):
            raise OSError("GPIO gone")

    app.buzzer = _BrokenBuzzer()
    app._play_warning_pattern("top", "warning")
    # The motor half of the pattern still ran.
    assert app.front_motor.events


# --- dispatch ----------------------------------------------------------------

def test_detection_actually_reaches_the_actuators(app):
    """End to end through the thread the main loop spawns, rather than
    calling the pattern directly."""
    sensor = _FixedUltrasonic(OBSTACLE_DANGER_CM - 10)
    app._check_obstacle_sensor("top", sensor)

    assert _wait_for(lambda: bool(app.buzzer.events))
    assert _wait_for(lambda: bool(app.front_motor.events))
