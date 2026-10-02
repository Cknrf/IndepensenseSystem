"""Unit tests for obstacle tiering and warning feedback in `app.py`.

This is the code that runs 100 times a second on the real device and
decides whether the user gets warned about something in their path. It
had no automated coverage until now.

Tests build a bare `MockApp` and assign only the devices each one needs,
rather than calling `start()`. That keeps them fast and focused: `start()`
loads models, attempts a guardian fetch and opens a dozen devices, none of
which this logic touches.

Re-notify timing is asserted by writing `_obstacle_last_fired` directly.
The method reads `time.monotonic()` with no seam to inject, and adding one
purely for tests would be worse than reaching in — the dict *is* the
timing state, so a test that sets it is describing the same thing the
production code does.

The tier state (`_obstacle_tier`) is deliberately NOT written directly in
the hysteresis tests. A latch is only meaningful across a *sequence* of
readings, so those drive the real method repeatedly and assert on what
fired — setting the latch by hand would assert the test's idea of the
state machine rather than the code's.
"""
import time

import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.config import (
    OBSTACLE_DANGER_CM,
    OBSTACLE_DANGER_REPEAT_S,
    OBSTACLE_RELEASE_CM,
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


@pytest.fixture(autouse=True)
def buzzer_unmuted(monkeypatch):
    """Assert the deployed feedback matrix, not whatever the bench mute
    happens to be set to.

    `config.OBSTACLE_BUZZER_ENABLED` is a convenience flag that gets flipped
    off during indoor testing. Without this fixture the meaning of every
    beep assertion below would silently change with it. The one test that
    cares about the muted case turns it off itself.
    """
    monkeypatch.setattr(app_module, "OBSTACLE_BUZZER_ENABLED", True)


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

    assert app._obstacle_tier["top"] is None
    assert app._obstacle_last_fired == {}
    time.sleep(0.05)
    assert app.buzzer.events == []
    assert app.front_motor.events == []


def test_warning_zone_fires_the_warning_tier(app):
    sensor = _FixedUltrasonic((OBSTACLE_WARNING_CM + OBSTACLE_DANGER_CM) / 2)
    app._check_obstacle_sensor("top", sensor)
    assert app._obstacle_tier["top"] == "warning"
    assert "top" in app._obstacle_last_fired


def test_danger_zone_fires_the_danger_tier(app):
    sensor = _FixedUltrasonic(OBSTACLE_DANGER_CM - 10)
    app._check_obstacle_sensor("top", sensor)
    assert app._obstacle_tier["top"] == "danger"


def test_the_threshold_itself_is_the_safe_side(app):
    """Thresholds are exclusive (`distance < OBSTACLE_WARNING_CM`), so a
    reading exactly at 100 cm is safe. Pinning this stops a later
    refactor flipping it silently."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_WARNING_CM))
    assert app._obstacle_tier["top"] is None

    app._check_obstacle_sensor("bottom", _FixedUltrasonic(OBSTACLE_DANGER_CM))
    assert app._obstacle_tier["bottom"] == "warning"


# --- non-readings ------------------------------------------------------------

def test_absent_sensor_is_a_no_op(app):
    app._check_obstacle_sensor("top", None)
    assert app._obstacle_tier == {}
    assert app._obstacle_last_fired == {}


def test_no_fresh_frame_is_a_no_op(app):
    """At 100 Hz against a ~10 Hz sensor, 9 of 10 reads return None. This
    is the common case, not an edge case."""
    sensor = _FixedUltrasonic(None)
    app._check_obstacle_sensor("top", sensor)
    assert sensor.read_count == 1
    assert app._obstacle_tier == {}
    assert app._obstacle_last_fired == {}


def test_a_raising_sensor_does_not_propagate(app):
    """A bad UART read must not take down the main loop — obstacle
    detection has to survive a transient glitch."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(raise_on_read=True))
    assert app._obstacle_tier == {}
    assert app._obstacle_last_fired == {}


# --- hysteresis --------------------------------------------------------------
#
# The field log that prompted this: `[obstacle:top] danger at 42 cm` every
# two seconds for minutes, each one a motor pulse, because the old rule
# re-fired on a fixed cooldown for as long as anything stayed in range.
# Walking a corridor beside a wall buzzed continuously, and a signal that
# never stops is one the wearer learns to ignore.

def _feed(app, name, *distances):
    """Drive one sensor through a sequence of readings.

    Returns how many times a warning pattern was dispatched, counted by
    the latch rather than by the motors: the patterns play on background
    threads and sleep for their own duration, so counting actuator events
    would be a race.
    """
    fired = []
    original = app._check_obstacle_sensor

    for distance in distances:
        before = app._obstacle_last_fired.get(name)
        original(name, _FixedUltrasonic(distance))
        after = app._obstacle_last_fired.get(name)
        if after != before:
            fired.append(distance)
    return fired


def test_staying_in_a_tier_fires_once(app, monkeypatch):
    """Entering alerts; remaining is silent. This is the whole fix."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    close = OBSTACLE_DANGER_CM - 8

    fired = _feed(app, "top", close, close, close, close, close)

    assert fired == [close]


def test_a_cane_wobbling_on_the_threshold_fires_once(app, monkeypatch):
    """The reason a plain "fire when the distance changes" rule fails: a
    hand holding the cane moves centimetres without the user going
    anywhere, so the reading is never still. These readings straddle the
    50 cm danger line and must not re-trigger on every crossing."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)

    fired = _feed(app, "top", 48, 52, 47, 53, 49, 51, 46)

    assert fired == [48], f"wobble re-triggered at {fired}"


def test_receding_past_the_release_threshold_re_arms(app, monkeypatch):
    """A genuine approach after a genuine retreat must warn again."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    close = OBSTACLE_DANGER_CM - 8
    clear = OBSTACLE_WARNING_CM + OBSTACLE_RELEASE_CM + 5

    fired = _feed(app, "top", close, clear, close)

    assert fired == [close, close]


def test_leaving_a_tier_needs_more_than_crossing_back_over_it(app, monkeypatch):
    """The hysteresis band itself. Stepping just past the danger line is
    not far enough to re-arm it; `OBSTACLE_RELEASE_CM` further is."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    close = OBSTACLE_DANGER_CM - 8

    # Back over the line, but inside the release band — still "danger".
    _feed(app, "top", close, OBSTACLE_DANGER_CM + 5)
    assert app._obstacle_tier["top"] == "danger"

    # Past the band — now genuinely out of danger.
    _feed(app, "top", OBSTACLE_DANGER_CM + OBSTACLE_RELEASE_CM + 5)
    assert app._obstacle_tier["top"] == "warning"


def test_escalating_from_warning_to_danger_fires_immediately(app, monkeypatch):
    """The safety-critical case: something approaching fast gets its
    danger warning at once, even though a warning fired moments ago."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)

    fired = _feed(app, "top", OBSTACLE_WARNING_CM - 5, OBSTACLE_DANGER_CM - 5)

    assert len(fired) == 2
    assert app._obstacle_tier["top"] == "danger"


def test_de_escalating_is_silent(app, monkeypatch):
    """Dropping from danger back to warning means the hazard is receding.
    Announcing that would spend the user's attention to tell them
    something is getting better."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    receded = OBSTACLE_DANGER_CM + OBSTACLE_RELEASE_CM + 5

    fired = _feed(app, "top", OBSTACLE_DANGER_CM - 8, receded)

    assert len(fired) == 1
    assert app._obstacle_tier["top"] == "warning"


# --- the danger backstop -----------------------------------------------------

def test_a_standing_danger_is_repeated_eventually(app, monkeypatch):
    """Someone walking a long wall at 42 cm should not be told once and
    then left. Danger — and only danger — re-notifies."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    close = OBSTACLE_DANGER_CM - 8
    _feed(app, "top", close)

    app._obstacle_last_fired["top"] -= OBSTACLE_DANGER_REPEAT_S + 1

    assert _feed(app, "top", close) == [close]


def test_a_standing_warning_is_never_repeated(app, monkeypatch):
    """Something an arm's length away does not need reminding about. Only
    the danger tier earns a backstop."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    mid = (OBSTACLE_WARNING_CM + OBSTACLE_DANGER_CM) / 2
    _feed(app, "top", mid)

    app._obstacle_last_fired["top"] -= OBSTACLE_DANGER_REPEAT_S * 10

    assert _feed(app, "top", mid) == []


def test_the_backstop_does_not_fire_early(app, monkeypatch):
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    close = OBSTACLE_DANGER_CM - 8
    _feed(app, "top", close)

    app._obstacle_last_fired["top"] -= OBSTACLE_DANGER_REPEAT_S / 2

    assert _feed(app, "top", close) == []


# --- independence ------------------------------------------------------------

def test_latches_are_independent_per_sensor(app, monkeypatch):
    """TOP and BOTTOM watch different parts of the world; one latching
    must not mute the other."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    close = OBSTACLE_DANGER_CM - 10

    assert _feed(app, "top", close) == [close]
    assert _feed(app, "bottom", close) == [close]
    assert app._obstacle_tier == {"top": "danger", "bottom": "danger"}


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


def test_bench_mute_drops_the_beep_but_keeps_the_vibration(app, monkeypatch):
    """Muting the buzzer must not mute the warning — the haptic half of
    every TOP pattern still has to fire, or indoor testing would be
    exercising a code path the deployed device never runs."""
    monkeypatch.setattr(app_module, "OBSTACLE_BUZZER_ENABLED", False)

    app._play_warning_pattern("top", "warning")
    app._play_warning_pattern("top", "danger")

    assert app.buzzer.events == []
    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events


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


# --- the tier function in isolation ------------------------------------------
#
# `_obstacle_tier_for` is pure arithmetic over two config values and its
# own argument — no device, no clock, no app state — so the hysteresis
# table can be asserted directly instead of inferred from how often a mock
# motor twitched.

@pytest.mark.parametrize("distance,current,expected", [
    # From clear: entry thresholds, exclusive.
    (OBSTACLE_WARNING_CM + 1,      None, None),
    (OBSTACLE_WARNING_CM,          None, None),
    (OBSTACLE_WARNING_CM - 1,      None, "warning"),
    (OBSTACLE_DANGER_CM,           None, "warning"),
    (OBSTACLE_DANGER_CM - 1,       None, "danger"),

    # Already in warning: escalates at the danger threshold, and holds
    # until the obstacle clears the release band.
    (OBSTACLE_DANGER_CM - 1,                       "warning", "danger"),
    (OBSTACLE_DANGER_CM,                           "warning", "warning"),
    (OBSTACLE_WARNING_CM + 1,                      "warning", "warning"),
    (OBSTACLE_WARNING_CM + OBSTACLE_RELEASE_CM,    "warning", None),

    # Already in danger: holds across its own release band, then falls
    # back only as far as the state the new distance justifies.
    (OBSTACLE_DANGER_CM + 1,                       "danger", "danger"),
    (OBSTACLE_DANGER_CM + OBSTACLE_RELEASE_CM - 1, "danger", "danger"),
    (OBSTACLE_DANGER_CM + OBSTACLE_RELEASE_CM,     "danger", "warning"),
    (OBSTACLE_WARNING_CM + OBSTACLE_RELEASE_CM,    "danger", None),
])
def test_the_hysteresis_table(distance, current, expected):
    assert app_module._obstacle_tier_for(distance, current) == expected


def test_a_tier_is_harder_to_leave_than_to_enter(app):
    """The defining property, stated once rather than per threshold: no
    distance exists that enters a tier from clear but also leaves it."""
    for entry, tier in (
        (OBSTACLE_DANGER_CM, "danger"),
        (OBSTACLE_WARNING_CM, "warning"),
    ):
        for offset in (0.0, 1.0, OBSTACLE_RELEASE_CM - 1):
            distance = entry + offset
            entered = app_module._obstacle_tier_for(distance, None)
            held = app_module._obstacle_tier_for(distance, tier)
            assert _rank(held) >= _rank(entered), (
                f"{distance} cm leaves {tier} but would not enter it"
            )


def _rank(tier):
    return app_module._OBSTACLE_RANK[tier]


# --- the cached reading vision.describe reads --------------------------------
#
# `vision.describe` used to answer "I don't see anything I recognize"
# while this very sensor had an obstacle at 42 cm. The cache is the seam
# that let the two subsystems finally talk.

def test_a_reading_is_cached_for_the_vision_fallback(app):
    app._check_obstacle_sensor("top", _FixedUltrasonic(42.0))

    assert app.obstacle_ahead_cm() == 42.0


def test_nothing_read_yet_is_none(app):
    assert app.obstacle_ahead_cm() is None


def test_a_stale_reading_is_not_reported(app):
    """The DYP-A22 emits at ~10 Hz, so an old reading means the sensor has
    stopped reporting — and the user has had a second to move, which at
    walking pace is about a metre."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(42.0))
    distance, stamped_at = app._obstacle_reading["top"]
    app._obstacle_reading["top"] = (distance, stamped_at - 60.0)

    assert app.obstacle_ahead_cm() is None


def test_an_obstacle_out_of_range_is_not_reported(app):
    """Nothing within warning range means there is nothing to describe.
    "Something is 350 centimetres away" is not an answer to "what is in
    front of me"."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_WARNING_CM + 50))

    assert app.obstacle_ahead_cm() is None


def test_the_bottom_sensor_is_not_used_for_the_vision_fallback(app):
    """BOTTOM points at foot level and sees the ground on most readings,
    so folding it in would answer "something is 80 centimetres away" to
    almost every question — true, useless, and the cane covers that
    height anyway."""
    app._check_obstacle_sensor("bottom", _FixedUltrasonic(42.0))

    assert app.obstacle_ahead_cm() is None


def test_the_cache_updates_even_when_no_alert_fires(app, monkeypatch):
    """Alerts fire on escalation only, so a sensor sitting in one tier is
    silent — but the distance it reports still has to be current."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    app._check_obstacle_sensor("top", _FixedUltrasonic(42.0))
    app._check_obstacle_sensor("top", _FixedUltrasonic(38.0))

    assert app.obstacle_ahead_cm() == 38.0
