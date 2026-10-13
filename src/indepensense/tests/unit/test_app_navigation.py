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
    """Built from the catalogue, not from the router's own text.

    The monitor used to hand over a finished English sentence wrapped
    around GraphHopper's instruction, so a Tagalog user heard "Sa isang
    daang metro, Turn left onto Rizal Street" — and the distance went in
    as a bare number, never reaching `speak_number`.
    """
    lang = app.language.current
    app._fire_navigation_cue(NavigationCue(
        kind="announce", direction="left",
        street_name="Rizal Street", distance_m=90.0,
    ))

    assert app.spoken == [messages.get(
        "nav.turn_in_distance", lang,
        distance=messages.speak_distance(90.0, lang),
        instruction=messages.nav_instruction("left", "Rizal Street", lang),
    )]
    assert "Rizal Street" in app.spoken[0]


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


def test_turn_now_uses_turn_not_face(app):
    """The two cues share an audio channel and mean different things:
    this one is a turn to take along the route, orientation's is "pivot
    on the spot". They were briefly the same words — `nav.started` ends
    with the route's first turn and orientation speaks right after it, so
    that put two different lefts back to back."""
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="right"))

    assert app.spoken == [
        messages.get("nav.turn_right", app.language.current)
    ]
    assert messages.get("nav.face_right", app.language.current) not in app.spoken


def test_arrive_is_spoken(app):
    app._fire_navigation_cue(NavigationCue(kind="arrive", destination="Home"))

    assert app.spoken == ["You have arrived at Home."]


def test_off_route_is_spoken(app):
    app._fire_navigation_cue(NavigationCue(kind="off_route"))

    assert app.spoken == [
        messages.get("nav.off_route", app.language.current)
    ]


def test_an_unrecognised_cue_kind_is_ignored(app):
    app._fire_navigation_cue(NavigationCue(kind="somersault"))
    assert app.spoken == []


# --- deferral while the user is talking --------------------------------------

def test_announce_is_suppressed_while_a_voice_command_is_in_flight(app):
    """Talking over the user's own command, or over a response they are
    listening to, loses information for both."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="announce", direction="left", distance_m=90.0))
    assert app.spoken == []


def test_off_route_is_suppressed_while_voice_is_busy(app):
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="off_route"))
    assert app.spoken == []


def test_turn_now_is_suppressed_while_voice_is_busy(app):
    """It used to fire regardless, because it was a motor pulse and could
    not collide with speech. Now it can, so it waits — and because it is
    handed back rather than dropped, waiting does not mean losing it."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="right"))

    assert app.spoken == []


def test_arrival_is_spoken_even_while_voice_is_busy(app):
    """Arrival fires exactly once ever — `check()` clears the route in the
    same breath as emitting it — so there is no latch left to hand it back
    to. It used to survive a busy pipeline as a motor pulse; nothing else
    covers it now, so this one cue ignores the guard."""
    app._voice_active.set()
    app._fire_navigation_cue(NavigationCue(kind="arrive", destination="Home"))

    assert app.spoken == [messages.get(
        "nav.arrived", app.language.current, destination="Home",
    )]


# --- cues the pipeline could not take ----------------------------------------
#
# Suppressed used to mean dropped. The monitor marks each cue fired before
# returning it, so nothing brought it back: an announce lost to a busy
# pipeline was never spoken, and a dropped off-route warning left the user
# with no further warning for the rest of that deviation. The comment here
# said they came round again on a later poll, and a test docstring agreed
# with it. Neither was true.


class _RecordingMonitor:
    """Stands in for the monitor to record what gets handed back."""

    def __init__(self):
        self.deferred: list[NavigationCue] = []

    def defer(self, cue: NavigationCue) -> None:
        self.deferred.append(cue)


@pytest.mark.parametrize("cue", [
    NavigationCue(kind="announce", direction="left", distance_m=90.0, index=1),
    NavigationCue(kind="turn_now", direction="right", index=1),
    NavigationCue(kind="missed_turn", direction="left", street_name="B"),
    NavigationCue(kind="off_route"),
])
def test_a_cue_we_cannot_speak_goes_back_to_the_monitor(app, cue):
    app.nav_monitor = _RecordingMonitor()
    app._voice_active.set()

    app._fire_navigation_cue(cue)

    assert app.spoken == []
    assert app.nav_monitor.deferred == [cue]


def test_arrival_is_never_handed_back(app):
    """There is nothing to hand it back to, and the guard it skips is the
    reason it is still spoken at all."""
    app.nav_monitor = _RecordingMonitor()
    app._voice_active.set()

    app._fire_navigation_cue(NavigationCue(kind="arrive", destination="Home"))

    assert app.spoken == [messages.get(
        "nav.arrived", app.language.current, destination="Home",
    )]
    assert app.nav_monitor.deferred == []


def test_a_long_busy_window_logs_each_kind_once(app, capsys):
    """The monitor re-offers a deferred cue on every poll, so logging each
    one would put a line a second in the journal for the length of every
    voice command — and turn-to-face runs for up to 20 s."""
    app.nav_monitor = _RecordingMonitor()
    app._voice_active.set()
    cue = NavigationCue(kind="announce", direction="left", distance_m=90.0, index=1)

    for _ in range(20):
        app._fire_navigation_cue(cue)

    deferred_lines = [
        line for line in capsys.readouterr().out.splitlines()
        if "deferred announce" in line
    ]
    assert len(deferred_lines) == 1
    assert len(app.nav_monitor.deferred) == 20


def test_the_log_speaks_again_for_the_next_busy_window(app, capsys):
    """Once-per-window, not once-per-run: a later command that loses a cue
    has to leave its own trace."""
    app.nav_monitor = _RecordingMonitor()
    cue = NavigationCue(kind="announce", direction="left", distance_m=90.0, index=1)

    app._voice_active.set()
    app._fire_navigation_cue(cue)
    app._voice_active.clear()
    app._fire_navigation_cue(cue)          # spoken, and clears the latch
    app._voice_active.set()
    app._fire_navigation_cue(cue)

    deferred_lines = [
        line for line in capsys.readouterr().out.splitlines()
        if "deferred announce" in line
    ]
    assert len(deferred_lines) == 2


# --- containment -------------------------------------------------------------

def test_a_raising_announce_does_not_propagate(app):
    """Cue firing runs on the main loop; an exception here would take
    down fall and obstacle detection with it."""
    def _boom(text, critical=False):
        raise OSError("audio gone")

    app._announce = _boom
    app._fire_navigation_cue(NavigationCue(kind="turn_now", direction="left"))
    app._fire_navigation_cue(NavigationCue(kind="arrive", destination="Home"))


def test_no_motor_is_touched_by_any_navigation_cue(app):
    """The motors are obstacle-only now. A navigation cue reaching them
    would be the directional encoding creeping back in."""
    for cue in (
        NavigationCue(kind="announce", direction="left", distance_m=90.0),
        NavigationCue(kind="turn_now", direction="left"),
        NavigationCue(kind="arrive", destination="Home"),
        NavigationCue(kind="off_route"),
        NavigationCue(kind="missed_turn", direction="left"),
    ):
        app._fire_navigation_cue(cue)

    time.sleep(0.05)   # a spawned haptic would have landed by now
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events == []


# --- polling ----------------------------------------------------------------

class _StubCache:
    def __init__(self, fix):
        self._fix = fix

    def latest_fix(self, max_age_s=None):
        # The real cache expires by age; this stub always holds a fresh
        # one, so the bound is accepted and ignored.
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
                NavigationCue(kind="announce", direction="right", distance_m=50.0),
                NavigationCue(kind="turn_now", direction="right"),
            ]

    app.nav_monitor = _CueingMonitor()
    app.gps_cache = _StubCache(_fix())
    app._last_nav_check = 0.0
    app._check_navigation()

    lang = app.language.current
    assert app.spoken == [
        messages.get(
            "nav.turn_in_distance", lang,
            distance=messages.speak_distance(50.0, lang),
            instruction=messages.nav_instruction("right", None, lang),
        ),
        messages.get("nav.turn_right", lang),
    ]


# --- missed turns ------------------------------------------------------------
#
# The monitor decides whether a turn was missed; this covers what `app.py`
# does with the verdict.

def test_a_missed_turn_is_spoken(app):
    """It names the turn that was missed rather than issuing a correction:
    the wearable cannot reroute, so it says what it believes happened and
    lets the user decide."""
    app._fire_navigation_cue(
        NavigationCue(kind="missed_turn", street_name="Rizal Street",
                      direction="left")
    )

    assert len(app.spoken) == 1
    assert "Rizal Street" in app.spoken[0]


def test_a_missed_turn_is_deferred_while_the_user_is_talking(app):
    """Same rule as every other spoken cue — talking over the user's own
    command loses information for both."""
    app._voice_active.set()

    app._fire_navigation_cue(
        NavigationCue(kind="missed_turn", direction="left")
    )

    assert app.spoken == []


def test_a_missed_turn_with_no_motors_at_all_still_speaks(app):
    app.front_motor = app.left_motor = app.right_motor = None

    app._fire_navigation_cue(
        NavigationCue(kind="missed_turn", direction="left")
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
