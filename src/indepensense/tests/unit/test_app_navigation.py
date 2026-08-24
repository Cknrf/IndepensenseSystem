"""Unit tests for navigation cue routing in `app.py`.

`NavigationMonitor` decides *what* cue to fire and is tested separately.
This covers what `app.py` does with those cues: which motor a direction
maps to, and when speech is suppressed because the user is mid-command.
"""
import threading
import time

import pytest

from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockBuzzer, MockVibrationMotor
from indepensense.navigation.monitor import NavigationCue
from indepensense.sensors.base import GPSFix


class _RecordingApp(MockApp):
    """Captures what would have been spoken instead of synthesising audio.

    `_speak_error` is the helper `_fire_navigation_cue` reuses for all its
    speech. Overriding it here keeps these tests off the audio stack while
    leaving the cue-routing logic itself untouched.
    """

    def __init__(self):
        super().__init__()
        self.spoken: list[str] = []

    def _speak_error(self, message: str) -> None:
        self.spoken.append(message)


@pytest.fixture
def app():
    instance = _RecordingApp()
    instance.buzzer = MockBuzzer()
    instance.front_motor = MockVibrationMotor()
    instance.left_motor = MockVibrationMotor()
    instance.right_motor = MockVibrationMotor()
    return instance


# --- direction to motor ------------------------------------------------------

def test_directions_map_to_their_own_motor(app):
    assert app._motor_for_direction("left") is app.left_motor
    assert app._motor_for_direction("right") is app.right_motor
    assert app._motor_for_direction("straight") is app.front_motor


def test_unknown_directions_map_to_nothing(app):
    """Better a missing cue than the wrong one — a left-turn buzz on the
    right side of the body would actively mislead."""
    assert app._motor_for_direction("arrive") is None
    assert app._motor_for_direction("backwards") is None
    assert app._motor_for_direction(None) is None


# --- cue routing -------------------------------------------------------------

def test_announce_is_spoken(app):
    app._fire_navigation_cue(NavigationCue(kind="announce", text="In 90 meters, turn left"))
    assert app.spoken == ["In 90 meters, turn left"]


def test_haptic_pulses_only_the_matching_motor(app):
    app._fire_navigation_cue(NavigationCue(kind="haptic", direction="left"))

    assert app.left_motor.events
    assert app.right_motor.events == []
    assert app.front_motor.events == []
    assert app.spoken == []


def test_arrive_speaks_and_pulses_every_motor(app):
    """Arrival is the cue the user most needs, so it is both spoken and
    unmistakable to feel."""
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="You have arrived at Home."))

    assert app.spoken == ["You have arrived at Home."]
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events


def test_off_route_speaks_and_pulses(app):
    app._fire_navigation_cue(NavigationCue(kind="off_route", text="You are off the planned route."))

    assert app.spoken == ["You are off the planned route."]
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events


def test_an_unrecognised_cue_kind_is_ignored(app):
    app._fire_navigation_cue(NavigationCue(kind="somersault", text="???"))
    assert app.spoken == []


# --- deferral while the user is talking --------------------------------------

def test_announce_is_suppressed_while_a_voice_command_is_in_flight(app):
    """Talking over the user's own command, or over a response they are
    listening to, loses information for both."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="announce", text="turn left"))
    assert app.spoken == []


def test_off_route_is_suppressed_while_voice_is_busy(app):
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="off_route", text="off route"))
    assert app.spoken == []


def test_haptic_still_fires_while_voice_is_busy(app):
    """The reason haptics exist: a silent channel that works when the
    audio one is occupied."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="haptic", direction="right"))
    assert app.right_motor.events


def test_arrival_still_pulses_while_voice_is_busy(app):
    """Speech is deferred but the haptic half is not — the user should
    still learn they arrived."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="arrived"))

    assert app.spoken == []
    assert app.front_motor.events


# --- containment -------------------------------------------------------------

def test_a_raising_motor_does_not_propagate(app):
    """Cue firing runs on the main loop; an exception here would take
    down fall and obstacle detection with it."""
    class _BrokenMotor(MockVibrationMotor):
        def pulse(self, *args, **kwargs):
            raise OSError("GPIO gone")

    app.left_motor = _BrokenMotor()
    app._fire_navigation_cue(NavigationCue(kind="haptic", direction="left"))


def test_missing_motors_are_survivable(app):
    app.front_motor = app.left_motor = app.right_motor = None
    app._fire_navigation_cue(NavigationCue(kind="haptic", direction="left"))
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="arrived"))
    assert app.spoken == ["arrived"]


# --- polling ----------------------------------------------------------------

class _StubCache:
    def __init__(self, fix):
        self._fix = fix

    def latest_fix(self):
        return self._fix


def _fix(lat=14.0, lon=121.0):
    return GPSFix(
        lat=lat, lon=lon, altitude_m=15.0, speed_knots=0.0, course_deg=None,
        satellites=8, hdop=1.2, fix_quality=1, utc_time=None, timestamp=time.time(),
    )


def test_no_polling_without_an_active_route(app):
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0
    app._check_navigation()
    assert app.spoken == []


def test_no_polling_without_a_gps_fix(app):
    """Nothing useful to compare a route against."""
    app.gps_cache = _StubCache(None)
    app._last_nav_check = 0.0
    app._check_navigation()
    assert app.spoken == []


def test_polling_is_throttled_to_about_one_hertz(app):
    """Called from the 100 Hz loop, but GPS updates once a second at
    best — checking faster burns cycles on identical data."""
    calls = []

    class _CountingMonitor:
        def is_active(self):
            return True

        def check(self, position, now=None):
            calls.append(position)
            return []

    app.nav_monitor = _CountingMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = time.monotonic()

    for _ in range(50):
        app._check_navigation()
    assert calls == []

    app._last_nav_check = time.monotonic() - 2.0
    app._check_navigation()
    assert len(calls) == 1


def test_a_raising_monitor_does_not_break_the_loop(app):
    class _BrokenMonitor:
        def is_active(self):
            return True

        def check(self, position, now=None):
            raise ValueError("bad route state")

    app.nav_monitor = _BrokenMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0
    app._check_navigation()


def test_cues_from_the_monitor_reach_the_actuators(app):
    class _CueingMonitor:
        def is_active(self):
            return True

        def check(self, position, now=None):
            return [
                NavigationCue(kind="announce", text="In 50 meters, turn right"),
                NavigationCue(kind="haptic", direction="right"),
            ]

    app.nav_monitor = _CueingMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0
    app._check_navigation()

    assert app.spoken == ["In 50 meters, turn right"]
    assert app.right_motor.events


def test_warning_lock_is_released_after_a_cue(app):
    """Cue firing takes `_warning_lock` to avoid racing obstacle patterns
    on the same actuators. Holding it would deadlock every later
    warning."""
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="arrived"))
    assert app._warning_lock.acquire(timeout=1.0)
    app._warning_lock.release()
