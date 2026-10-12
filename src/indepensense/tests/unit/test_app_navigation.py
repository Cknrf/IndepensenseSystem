"""Unit tests for navigation cue routing in `app.py`.

`NavigationMonitor` decides *what* cue to fire and is tested separately.
This covers what `app.py` does with those cues: what each one says, and
when speech is suppressed because the user is mid-command. Every cue is
speech now — the motors carried direction until it was found that all
three share the cane handle and arrive at the hand as one buzz.
"""
import threading
import time

import pytest

from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockBuzzer, MockVibrationMotor
from indepensense.intents import messages
from indepensense.navigation.monitor import NavigationCue
from indepensense.sensors.base import GPSFix


class _RecordingApp(MockApp):
    """Captures what would have been announced instead of synthesising audio.

    `_announce` is the seam `_fire_navigation_cue` hands all its speech to —
    it enqueues on the `Announcer` thread rather than blocking. Overriding it
    keeps these tests off the audio stack while leaving the cue-routing logic
    itself untouched.
    """

    def __init__(self):
        super().__init__()
        self.spoken: list[str] = []
        self.critical: list[str] = []

    def _announce(self, text: str, critical: bool = False) -> None:
        self.spoken.append(text)
        if critical:
            self.critical.append(text)


@pytest.fixture
def app():
    instance = _RecordingApp()
    instance.buzzer = MockBuzzer()
    instance.front_motor = MockVibrationMotor()
    instance.left_motor = MockVibrationMotor()
    instance.right_motor = MockVibrationMotor()
    return instance


# --- cue routing -------------------------------------------------------------

def test_announce_is_spoken(app):
    app._fire_navigation_cue(NavigationCue(kind="announce", text="In 90 meters, turn left"))
    assert app.spoken == ["In 90 meters, turn left"]


def test_turn_now_speaks_the_direction_alone(app):
    """Two words at the junction. The street name and the distance were
    spoken 80 m back; repeating them here would still be playing while
    the user is in the road."""
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="left"))

    assert app.spoken == ["Turn left."]


def test_turn_now_with_an_unknown_direction_says_nothing(app):
    """Better silence than the wrong instruction: "arrive" reaching this
    branch and being read as a turn would send the user off a kerb."""
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="arrive"))
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction=None))

    assert app.spoken == []


def test_turn_now_uses_the_same_words_as_turn_to_face(app):
    """One phrase to learn, not two. Both paths go through
    `_ORIENTATION_MESSAGE_KEYS` precisely so they cannot drift."""
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="right"))

    assert app.spoken == [
        messages.get("nav.turn_right", app.language.current)
    ]


def test_arrive_is_spoken(app):
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="You have arrived at Home."))

    assert app.spoken == ["You have arrived at Home."]


def test_off_route_is_spoken(app):
    app._fire_navigation_cue(NavigationCue(kind="off_route", text="You are off the planned route."))

    assert app.spoken == ["You are off the planned route."]


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


def test_turn_now_is_suppressed_while_voice_is_busy(app):
    """It used to fire regardless, because it was a motor pulse and could
    not collide with speech. Now it can, and it is the one cue it is safe
    to drop: the turn is 20 m ahead and the monitor is still polling."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="right"))

    assert app.spoken == []


def test_arrival_is_spoken_even_while_voice_is_busy(app):
    """Arrival fires exactly once ever — `check()` clears the route in the
    same breath as emitting it — so deferring it loses it outright. It
    used to survive a busy pipeline as a motor pulse; nothing else covers
    it now, so this one cue ignores the guard."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="arrived"))

    assert app.spoken == ["arrived"]


# --- containment -------------------------------------------------------------

def test_a_raising_announce_does_not_propagate(app):
    """Cue firing runs on the main loop; an exception here would take
    down fall and obstacle detection with it."""
    def _boom(text, critical=False):
        raise OSError("audio gone")

    app._announce = _boom
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="left"))
    app._fire_navigation_cue(NavigationCue(kind="arrive", text="arrived"))


def test_no_motor_is_touched_by_any_navigation_cue(app):
    """The motors are obstacle-only now. A navigation cue reaching them
    would be the directional encoding creeping back in."""
    for cue in (
        NavigationCue(kind="announce", text="In 90 meters, turn left"),
        NavigationCue(kind="turn_now", direction="left"),
        NavigationCue(kind="arrive", text="arrived"),
        NavigationCue(kind="off_route", text="off route"),
        NavigationCue(kind="missed_turn", text="Turn left", direction="left"),
    ):
        app._fire_navigation_cue(cue)

    time.sleep(0.05)   # a spawned haptic would have landed by now
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events == []


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

        def check(self, position, now=None, heading=None):
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

        def check(self, position, now=None, heading=None):
            raise ValueError("bad route state")

    app.nav_monitor = _BrokenMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0
    app._check_navigation()


def test_cues_from_the_monitor_reach_the_actuators(app):
    class _CueingMonitor:
        def is_active(self):
            return True

        def check(self, position, now=None, heading=None):
            return [
                NavigationCue(kind="announce", text="In 50 meters, turn right"),
                NavigationCue(kind="turn_now", direction="right"),
            ]

    app.nav_monitor = _CueingMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0
    app._check_navigation()

    assert app.spoken == ["In 50 meters, turn right", "Turn right."]


# --- missed turns ------------------------------------------------------------
#
# The monitor decides whether a turn was missed; this covers what `app.py`
# does with the verdict.

def test_a_missed_turn_is_spoken(app):
    """It names the turn that was missed rather than issuing a correction:
    the wearable cannot reroute, so it says what it believes happened and
    lets the user decide."""
    app._fire_navigation_cue(
        NavigationCue(kind="missed_turn", text="Turn left onto Rizal Street",
                      direction="left")
    )

    assert len(app.spoken) == 1
    assert "Rizal Street" in app.spoken[0]


def test_a_missed_turn_is_deferred_while_the_user_is_talking(app):
    """Same rule as every other spoken cue — talking over the user's own
    command loses information for both."""
    app._voice_active.set()

    app._fire_navigation_cue(
        NavigationCue(kind="missed_turn", text="Turn left", direction="left")
    )

    assert app.spoken == []


def test_a_missed_turn_with_no_motors_at_all_still_speaks(app):
    app.front_motor = app.left_motor = app.right_motor = None

    app._fire_navigation_cue(
        NavigationCue(kind="missed_turn", text="Turn left", direction="left")
    )

    assert len(app.spoken) == 1


def test_the_heading_is_passed_to_the_monitor(app):
    """Turn verification is off unless the monitor is given one, and the
    app is the only thing that can supply it."""
    seen = []

    class _RecordingMonitor:
        def is_active(self):
            return True

        def check(self, position, now=None, heading=None):
            seen.append(heading)
            return []

    app.nav_monitor = _RecordingMonitor()
    app.gps_cache = _StubCache(_fix())
    app.trusted_heading = lambda: 137.0
    app._last_nav_check = 0.0

    app._check_navigation()

    assert seen == [137.0]


def test_an_uncalibrated_compass_passes_no_heading(app):
    """Which leaves turn verification inert — today's behaviour."""
    seen = []

    class _RecordingMonitor:
        def is_active(self):
            return True

        def check(self, position, now=None, heading=None):
            seen.append(heading)
            return []

    app.nav_monitor = _RecordingMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0

    app._check_navigation()

    assert seen == [None]
