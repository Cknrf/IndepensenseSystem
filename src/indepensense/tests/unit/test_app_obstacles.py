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
    OBSTACLE_FAR_CM,
    OBSTACLE_READING_MAX_AGE_S,
    OBSTACLE_RELEASE_CM,
    OBSTACLE_RHYTHM_CONTACT_CM,
    OBSTACLE_RHYTHM_CONTACT_HZ,
    OBSTACLE_RHYTHM_DANGER_HZ,
    OBSTACLE_RHYTHM_MAX_AGE_S,
    OBSTACLE_RHYTHM_PULSE_S,
    OBSTACLE_RHYTHM_WARNING_HZ,
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


class _Motion:
    """Stands in for `WalkingDetector`: the obstacle path only reads
    `.walking`, and what it does with the answer is what is under test
    here. The classifier itself is tested in `safety/tests/unit`."""

    def __init__(self, walking):
        self.walking = walking


@pytest.fixture
def app():
    """A MockApp with feedback devices attached but nothing started.

    The buzzer is attached even though the obstacle path must never ring
    it — that is precisely what makes the silence assertions meaningful.
    A test that asserted no beep against an absent buzzer would pass for
    the wrong reason and keep passing if the beep came back.
    """
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
    sensor = _FixedUltrasonic(OBSTACLE_FAR_CM + 50)
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
    reading exactly at a threshold falls in the milder tier. Pinning this
    stops a later refactor flipping it silently."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_FAR_CM))
    assert app._obstacle_tier["top"] is None

    app._check_obstacle_sensor("bottom", _FixedUltrasonic(OBSTACLE_DANGER_CM))
    assert app._obstacle_tier["bottom"] == "warning"


def test_top_has_a_far_tier(app):
    """Head height is what the cane cannot reach, so TOP warns earlier."""
    app._check_obstacle_sensor("top", _FixedUltrasonic(OBSTACLE_WARNING_CM + 50))
    assert app._obstacle_tier["top"] == "far"
    assert "top" in app._obstacle_last_fired


def test_bottom_has_no_far_tier(app):
    """The cane already reaches about a metre at foot level; a warning
    beyond that is about something it is about to touch anyway."""
    app._check_obstacle_sensor("bottom", _FixedUltrasonic(OBSTACLE_WARNING_CM + 50))
    assert app._obstacle_tier["bottom"] is None
    assert app._obstacle_last_fired == {}


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
    """Someone stopped at 42 cm from a hazard should not be told once and
    then left. Danger — and only danger — re-notifies."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    app.walking_detector = _Motion(walking=False)
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
    app.walking_detector = _Motion(walking=False)
    close = OBSTACLE_DANGER_CM - 8
    _feed(app, "top", close)

    app._obstacle_last_fired["top"] -= OBSTACLE_DANGER_REPEAT_S / 2

    assert _feed(app, "top", close) == []


def test_walking_hands_the_danger_repeat_to_the_rhythm(app, monkeypatch):
    """While walking, the proximity rhythm pulses for as long as danger
    lasts, so the tier repeat would only be a second, slower signal for
    the same thing."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    app.walking_detector = _Motion(walking=True)
    close = OBSTACLE_DANGER_CM - 8
    _feed(app, "top", close)

    app._obstacle_last_fired["top"] -= OBSTACLE_DANGER_REPEAT_S + 1

    assert _feed(app, "top", close) == []


def test_no_motion_signal_is_treated_as_walking(app):
    """Without an IMU there is no evidence the user is still, so the
    rhythm — the side that suppresses nothing — stays available."""
    app.walking_detector = None
    assert app._user_walking() is True


# --- setting off -------------------------------------------------------------
#
# Alerts fire when an obstacle gets closer. Someone who stood in front of a
# post and then walked towards it heard nothing, because the distance had
# not changed when they set off. The chest IMU sees them start moving
# before the ultrasonic sees the gap close.

def test_setting_off_re_alerts_an_obstacle_already_in_range(app, monkeypatch):
    played = []
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: played.append(a))
    mid = (OBSTACLE_WARNING_CM + OBSTACLE_DANGER_CM) / 2
    _feed(app, "top", mid, mid, mid)
    assert len(played) == 1

    app._on_started_walking()

    assert _wait_for(lambda: len(played) == 2)
    assert played[1] == ("top", "warning")


def test_setting_off_re_alerts_each_sensor_in_its_own_tier(app, monkeypatch):
    played = []
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: played.append(a))
    _feed(app, "top", OBSTACLE_WARNING_CM + 50)
    _feed(app, "bottom", OBSTACLE_DANGER_CM - 10)
    assert _wait_for(lambda: len(played) == 2)

    app._on_started_walking()

    assert _wait_for(lambda: len(played) == 4)
    assert sorted(played[2:]) == [("bottom", "danger"), ("top", "far")]


def test_setting_off_with_nothing_in_range_is_silent(app, monkeypatch):
    played = []
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: played.append(a))
    _feed(app, "top", OBSTACLE_FAR_CM + 50)

    app._on_started_walking()

    time.sleep(0.05)
    assert played == []


def test_setting_off_ignores_a_stale_reading(app, monkeypatch):
    """A sensor that stopped reporting has a tier describing where the
    world was, not where it is."""
    played = []
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: played.append(a))
    _feed(app, "top", OBSTACLE_DANGER_CM - 10)
    assert _wait_for(lambda: len(played) == 1)
    distance, stamped_at = app._obstacle_reading["top"]
    app._obstacle_reading["top"] = (
        distance, stamped_at - OBSTACLE_READING_MAX_AGE_S - 1,
    )

    app._on_started_walking()

    time.sleep(0.05)
    assert len(played) == 1


def test_a_re_alert_restarts_the_danger_backstop(app, monkeypatch):
    """The re-alert counts as the latest danger notice, so the standing
    backstop does not fire a second one straight after it."""
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    app.walking_detector = _Motion(walking=False)
    close = OBSTACLE_DANGER_CM - 8
    _feed(app, "top", close)
    app._obstacle_last_fired["top"] -= OBSTACLE_DANGER_REPEAT_S + 1

    app._on_started_walking()

    assert _feed(app, "top", close) == []


# --- proximity rhythm --------------------------------------------------------
#
# Tier alerts fire once on entry, so past 50 cm nothing told 45 cm from
# 20 cm. While walking, the closest obstacle now drives a pulse rate that
# rises as it gets closer — the parking-sensor pattern.

@pytest.fixture
def pulses(app, monkeypatch):
    """Record rhythm pulses as `all_motors` flags instead of playing them."""
    played = []
    monkeypatch.setattr(app, "_play_warning_pattern", lambda *a: None)
    monkeypatch.setattr(app, "_play_rhythm_pulse", lambda all_motors: played.append(all_motors))
    return played


def _pulse_due(app):
    """Wind the rhythm clock back so the next tick is due at any rate."""
    app._rhythm_last_pulse -= 10.0


def test_the_rhythm_pulses_while_walking_towards_head_height(app, pulses):
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 80, 80, 80)

    app._tick_obstacle_rhythm()          # starts the clock, no pulse yet
    assert pulses == []
    _pulse_due(app)
    app._tick_obstacle_rhythm()

    assert _wait_for(lambda: pulses == [False]), "expected one front pulse"


def test_the_first_pulse_waits_one_interval(app, pulses):
    """The tier alert has just played; a pulse straight on top of it would
    blur both."""
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 80, 80, 80)

    app._tick_obstacle_rhythm()
    app._tick_obstacle_rhythm()

    time.sleep(0.02)
    assert pulses == []


def test_standing_still_silences_the_rhythm(app, pulses):
    """A queue or a crossing must stay quiet: still keeps fire-once."""
    app.walking_detector = _Motion(walking=False)
    _feed(app, "top", 40, 40, 40)

    app._tick_obstacle_rhythm()

    assert app._rhythm_last_pulse is None
    time.sleep(0.02)
    assert pulses == []


def test_danger_range_pulses_all_motors(app, pulses):
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 40, 40, 40)
    app._tick_obstacle_rhythm()
    _pulse_due(app)
    app._tick_obstacle_rhythm()

    assert _wait_for(lambda: pulses == [True])


def test_bottom_only_joins_inside_danger(app, pulses):
    """BOTTOM sees the ground around 80 cm on most readings; a rhythm
    from there would buzz the whole walk."""
    app.walking_detector = _Motion(walking=True)
    _feed(app, "bottom", 80, 80, 80)
    app._tick_obstacle_rhythm()
    assert app._rhythm_last_pulse is None

    _feed(app, "bottom", 40, 40, 40)
    app._tick_obstacle_rhythm()
    assert app._rhythm_last_pulse is not None


def test_the_closer_sensor_drives_the_rhythm(app, pulses):
    """One beat at a time: two sensors must never produce two rhythms."""
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 90, 90, 90)
    _feed(app, "bottom", 35, 35, 35)

    app._tick_obstacle_rhythm()

    assert app._rhythm_sensor == "bottom"


def test_a_stale_sensor_stops_the_rhythm(app, pulses):
    """No echo looks like silence from the DYP-A22, so a sensor that has
    gone quiet means the obstacle has probably left range."""
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 60, 60, 60)
    app._tick_obstacle_rhythm()
    distance, stamped_at = app._obstacle_reading["top"]
    app._obstacle_reading["top"] = (distance, stamped_at - OBSTACLE_RHYTHM_MAX_AGE_S - 0.1)

    app._tick_obstacle_rhythm()

    assert app._rhythm_last_pulse is None
    assert app._rhythm_sensor is None


def test_one_wobbly_reading_does_not_move_the_rate(app, pulses):
    """The rate follows the median, so a single sway reading across the
    danger line does not switch the rhythm to all motors."""
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 60, 60, 45)
    app._tick_obstacle_rhythm()
    _pulse_due(app)
    app._tick_obstacle_rhythm()

    assert _wait_for(lambda: pulses == [False])


def test_closing_in_shortens_the_very_next_gap(app, pulses):
    """The interval is judged at the current rate, so stepping closer does
    not wait out the slower gap that was already running."""
    app.walking_detector = _Motion(walking=True)
    _feed(app, "top", 95, 95, 95)
    app._tick_obstacle_rhythm()
    slow_gap = 1.0 / app_module._obstacle_rhythm_hz(95)
    fast_gap = 1.0 / app_module._obstacle_rhythm_hz(OBSTACLE_RHYTHM_CONTACT_CM - 5)
    app._rhythm_last_pulse -= (slow_gap + fast_gap) / 2   # due at fast, not slow

    _feed(app, "top", *([OBSTACLE_RHYTHM_CONTACT_CM - 5] * 3))
    app._tick_obstacle_rhythm()

    assert _wait_for(lambda: len(pulses) == 1)


def test_a_rhythm_pulse_yields_to_a_cue_already_playing(app):
    """Dropped, not queued: a backlog would fire in a burst after the cue,
    and a turn instruction must never wait behind rhythm."""
    with app._warning_lock:
        app._play_rhythm_pulse(all_motors=False)

    assert app.front_motor.events == []


def test_a_rhythm_pulse_is_short(app):
    app._play_rhythm_pulse(all_motors=False)

    assert app.front_motor.events == [("pulse", 1, OBSTACLE_RHYTHM_PULSE_S, app.front_motor.events[0][3])]


def test_a_rhythm_pulse_never_sounds_the_buzzer(app):
    app._play_rhythm_pulse(all_motors=True)
    app._play_rhythm_pulse(all_motors=False)

    assert app.buzzer.events == []


@pytest.mark.parametrize("distance,expected", [
    (OBSTACLE_WARNING_CM,             OBSTACLE_RHYTHM_WARNING_HZ[0]),
    (OBSTACLE_DANGER_CM,              OBSTACLE_RHYTHM_WARNING_HZ[1]),
    (OBSTACLE_DANGER_CM - 0.001,      OBSTACLE_RHYTHM_DANGER_HZ[0]),
    (OBSTACLE_RHYTHM_CONTACT_CM,      OBSTACLE_RHYTHM_DANGER_HZ[1]),
    (OBSTACLE_RHYTHM_CONTACT_CM - 1,  OBSTACLE_RHYTHM_CONTACT_HZ),
    (5.0,                             OBSTACLE_RHYTHM_CONTACT_HZ),
])
def test_the_rhythm_rate_table(distance, expected):
    assert app_module._obstacle_rhythm_hz(distance) == pytest.approx(expected, abs=1e-3)


def test_closer_is_never_slower():
    """The defining property of the rhythm, over the whole range."""
    rates = [app_module._obstacle_rhythm_hz(d / 2) for d in range(2 * int(OBSTACLE_WARNING_CM), 0, -1)]
    assert all(b >= a for a, b in zip(rates, rates[1:]))


def test_crossing_into_danger_is_a_felt_step():
    """The bands do not meet: crossing 50 cm must change the rhythm by more
    than the warning band's own slope would."""
    just_outside = app_module._obstacle_rhythm_hz(OBSTACLE_DANGER_CM)
    just_inside = app_module._obstacle_rhythm_hz(OBSTACLE_DANGER_CM - 0.5)
    assert just_inside - just_outside >= 0.5


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

@pytest.mark.parametrize("sensor_name", ["top", "bottom"])
@pytest.mark.parametrize("tier", ["far", "warning", "danger"])
def test_no_obstacle_pattern_ever_sounds_the_buzzer(app, sensor_name, tier):
    """The invariant the whole feedback matrix now rests on.

    The buzzer is reserved for emergencies, because it is the only output
    a bystander can perceive and that exclusivity is what gives it
    meaning. Obstacles are the most frequent event the device has, so a
    beep leaking back into this path would be the one regression that
    quietly undoes the decision — the device would still work, still
    vibrate, still pass every other test here, and a bystander would lose
    the ability to tell an awning from someone in trouble.

    Parametrised over the full matrix rather than asserted per pattern:
    the rule is about the path, not about any one sensor or tier, and a
    new tier added later should fail here by default.
    """
    app._play_warning_pattern(sensor_name, tier)

    assert app.buzzer.events == []


def test_top_warning_pulses_the_front_motor(app):
    """TOP is the wearable's unique value — the cane cannot sweep head
    height — so a warning there still has to be felt."""
    app._play_warning_pattern("top", "warning")

    assert any(e[0] == "pulse" for e in app.front_motor.events)


def test_top_far_is_a_short_silent_tick(app):
    app._play_warning_pattern("top", "far")

    assert app.buzzer.events == []
    assert app.front_motor.events == [("pulse", 1, 0.1, app.front_motor.events[0][3])]


def test_front_motor_obstacle_cues_are_single_pulses_of_distinct_length(app):
    """Pulse *counts* belong to navigation — two front pulses mean
    "straight on" — so every obstacle cue on the front motor is one pulse,
    and head height (long) must not feel like foot level (short)."""
    lengths = {}
    for sensor, tier in (("top", "far"), ("top", "warning"), ("bottom", "warning")):
        app.front_motor.events.clear()
        app._play_warning_pattern(sensor, tier)
        (event,) = app.front_motor.events
        assert event[0] == "pulse" and event[1] == 1, (sensor, tier, event)
        lengths[(sensor, tier)] = event[2]

    assert len(set(lengths.values())) == 3, lengths


def test_top_danger_uses_all_three_motors(app):
    """All three motors is the most distinctive haptic available, and
    since the beep is gone it is now the *whole* danger signal."""
    app._play_warning_pattern("top", "danger")

    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events, "all three motors should fire on danger"


def test_bottom_warning_pulses_the_front_motor(app):
    app._play_warning_pattern("bottom", "warning")

    assert any(e[0] == "pulse" for e in app.front_motor.events)


def test_bottom_danger_uses_all_three_motors(app):
    app._play_warning_pattern("bottom", "danger")

    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert motor.events


def test_missing_actuators_do_not_raise(app):
    """Running with a motor that failed to open must degrade, not crash."""
    app.buzzer = None
    app.front_motor = None
    app._play_warning_pattern("top", "warning")
    app._play_warning_pattern("top", "danger")


def test_a_raising_actuator_is_contained(app):
    """A dead motor must not take the pattern down with it.

    The front motor rather than the buzzer, which this path no longer
    touches — a broken-buzzer test here would pass without executing
    anything.
    """
    class _BrokenMotor(MockVibrationMotor):
        def pulse(self, *args, **kwargs):
            raise OSError("GPIO gone")

    app.front_motor = _BrokenMotor()
    app._play_warning_pattern("top", "warning")   # must not raise


# --- dispatch ----------------------------------------------------------------

def test_detection_actually_reaches_the_actuators(app):
    """End to end through the thread the main loop spawns, rather than
    calling the pattern directly."""
    sensor = _FixedUltrasonic(OBSTACLE_DANGER_CM - 10)
    app._check_obstacle_sensor("top", sensor)

    assert _wait_for(lambda: bool(app.front_motor.events))
    assert app.buzzer.events == []


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
    """BOTTOM: the two-tier table."""
    assert app_module._obstacle_tier_for(distance, current, "bottom") == expected


@pytest.mark.parametrize("distance,current,expected", [
    # From clear: the far tier is entered first.
    (OBSTACLE_FAR_CM,                           None, None),
    (OBSTACLE_FAR_CM - 1,                       None, "far"),
    (OBSTACLE_WARNING_CM,                       None, "far"),
    (OBSTACLE_WARNING_CM - 1,                   None, "warning"),

    # In far: escalates at warning's entry line, holds through its band.
    (OBSTACLE_WARNING_CM - 1,                   "far", "warning"),
    (OBSTACLE_FAR_CM + OBSTACLE_RELEASE_CM - 1, "far", "far"),
    (OBSTACLE_FAR_CM + OBSTACLE_RELEASE_CM,     "far", None),

    # Receding from warning or danger lands in far, not clear.
    (OBSTACLE_WARNING_CM + OBSTACLE_RELEASE_CM, "warning", "far"),
    (OBSTACLE_WARNING_CM + OBSTACLE_RELEASE_CM, "danger", "far"),
    (OBSTACLE_FAR_CM + OBSTACLE_RELEASE_CM,     "danger", None),
])
def test_the_top_hysteresis_table(distance, current, expected):
    assert app_module._obstacle_tier_for(distance, current, "top") == expected


@pytest.mark.parametrize("sensor", ["top", "bottom"])
def test_a_tier_is_harder_to_leave_than_to_enter(sensor):
    """The defining property, stated once rather than per threshold: no
    distance exists that enters a tier from clear but also leaves it."""
    for tier, entry in app_module._OBSTACLE_TIERS[sensor]:
        for offset in (0.0, 1.0, OBSTACLE_RELEASE_CM - 1):
            distance = entry + offset
            entered = app_module._obstacle_tier_for(distance, None, sensor)
            held = app_module._obstacle_tier_for(distance, tier, sensor)
            assert _rank(held) >= _rank(entered), (
                f"{sensor}: {distance} cm leaves {tier} but would not enter it"
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


def test_the_main_loop_reports_setting_off(app, monkeypatch):
    """The wiring: an IMU sample that the walking detector calls the start
    of a walk reaches `_on_started_walking` from `run()`."""
    from indepensense.sensors.mock import MockIMU

    class _SetsOff:
        walking = True

        def process(self, reading):
            return True

    app.imu = MockIMU()
    app.walking_detector = _SetsOff()
    monkeypatch.setattr(app, "stop", lambda: None)
    started = []

    def _on_started_walking():
        started.append(True)
        app._shutdown.set()

    monkeypatch.setattr(app, "_on_started_walking", _on_started_walking)

    app.run()

    assert started == [True]
