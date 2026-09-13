"""Unit tests for `App._orient_towards_route`.

The decision logic is pure and tested in
`navigation/tests/unit/test_orientation.py`. This covers the loop around
it: reading the compass, pulsing the right motor, and — most importantly —
every way it can stop, because a user standing in the street being buzzed
at indefinitely is the failure this must not have.

Time is real here but tiny: the pulse intervals and timeout are overridden
per test so the whole file runs in well under a second.
"""
import threading
import time

import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockButton, MockVibrationMotor
from indepensense.routing.base import Coordinate, Route
from indepensense.sensors.base import GPSFix


class _OrientingApp(MockApp):
    """Captures announcements and serves a scripted compass."""

    def __init__(self, headings):
        super().__init__()
        self.spoken: list[str] = []
        # Consumed one per loop iteration; the last value repeats forever
        # so a test can settle on a heading without knowing the iteration
        # count.
        self._headings = list(headings)
        self.heading_reads = 0

    def _announce(self, text: str, critical: bool = False) -> None:
        self.spoken.append(text)

    def trusted_heading(self):
        self.heading_reads += 1
        if not self._headings:
            return None
        if len(self._headings) > 1:
            return self._headings.pop(0)
        return self._headings[0]


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


def _northward_route() -> Route:
    """A route heading due north, well past the 15 m target threshold."""
    return Route(
        distance_m=100.0, duration_s=75.0, instructions=[],
        points=[
            Coordinate(lat=14.0, lon=121.0),
            Coordinate(lat=14.0009, lon=121.0),      # ~100 m north
        ],
    )


@pytest.fixture(autouse=True)
def _fast(monkeypatch):
    """Shrink the timings so tests take milliseconds, not 20 s."""
    monkeypatch.setattr(app_module, "ORIENTATION_TIMEOUT_S", 0.4)
    monkeypatch.setattr(
        app_module, "ORIENTATION_BANDS", ((90.0, 0.02), (30.0, 0.01), (0.0, 0.01)),
    )
    monkeypatch.setattr(app_module, "COMPASS_CALIBRATED", True)


def _app(headings, fix=None):
    instance = _OrientingApp(headings)
    instance.gps_cache = _StubCache(fix if fix is not None else _fix())
    instance.nav_monitor.set_route(_northward_route(), "Home")
    instance.front_motor = MockVibrationMotor()
    instance.left_motor = MockVibrationMotor()
    instance.right_motor = MockVibrationMotor()
    instance.ptt_button = MockButton()
    instance.ptt_button.on("pressed", instance._on_ptt_press)
    return instance


# --- the happy path ----------------------------------------------------------

def test_already_facing_the_right_way_says_walk_ahead():
    app = _app([0.0])          # route runs north, user faces north

    app._orient_towards_route()

    assert app.spoken == ["Walk straight ahead."]


def test_alignment_pulses_every_motor():
    app = _app([0.0])
    app._orient_towards_route()

    for motor in (app.front_motor, app.left_motor, app.right_motor):
        assert _wait_until(lambda m=motor: m.events)


def test_facing_east_pulses_the_left_motor():
    """Route is north, user faces east — the short way round is left.

    Deliberately never aligns: the alignment cue pulses every motor on a
    spawned thread, which would race this assertion.
    """
    app = _app([90.0])

    app._orient_towards_route()

    assert app.left_motor.events
    assert app.right_motor.events == []


def test_facing_west_pulses_the_right_motor():
    app = _app([270.0])

    app._orient_towards_route()

    assert app.right_motor.events
    assert app.left_motor.events == []


def test_turning_into_alignment_finishes_and_speaks():
    """The sequence a real user produces: far out, coming round, aligned."""
    app = _app([180.0, 120.0, 40.0, 5.0])

    app._orient_towards_route()

    assert app.spoken == ["Walk straight ahead."]


# --- the ways out ------------------------------------------------------------

def test_it_gives_up_rather_than_buzzing_forever():
    """A user standing in the street being buzzed at indefinitely is the
    failure this must never have."""
    app = _app([180.0])        # never turns

    started = time.monotonic()
    app._orient_towards_route()
    elapsed = time.monotonic() - started

    assert app.spoken == ["Start walking, and I will guide you from there."]
    assert elapsed < 2.0


def test_an_emergency_press_abandons_it():
    app = _app([180.0])
    app._voice_cancel.set()

    app._orient_towards_route()

    assert app.spoken == []


def test_a_ptt_press_skips_it(monkeypatch):
    """For the user who already knows which way they are going.

    Pressed from another thread, because the button is only borrowed once
    the loop has started — a press before that lands on the ordinary
    push-to-talk handler.
    """
    monkeypatch.setattr(app_module, "ORIENTATION_TIMEOUT_S", 5.0)
    app = _app([180.0])

    def _press():
        time.sleep(0.05)
        app.ptt_button.press()

    threading.Thread(target=_press, daemon=True).start()

    started = time.monotonic()
    app._orient_towards_route()

    assert app.spoken == []                       # neither aligned nor gave up
    assert time.monotonic() - started < 2.0       # and it did not wait out the cap


def test_the_ptt_handler_is_handed_back():
    """Leaving it borrowed would strand the user with a device that no
    longer responds to push-to-talk at all."""
    app = _app([0.0])

    app._orient_towards_route()

    assert app.ptt_button._handlers["pressed"] == app._on_ptt_press


def test_the_handler_is_handed_back_even_when_the_compass_throws():
    app = _app([0.0])

    def _broken():
        raise OSError("I2C bus gone")

    app.trusted_heading = _broken
    app._orient_towards_route()      # must not raise

    assert app.ptt_button._handlers["pressed"] == app._on_ptt_press


# --- when it should not run at all -------------------------------------------

def test_an_uncalibrated_compass_skips_orientation(monkeypatch):
    """Today's behaviour, and every day until the compass is calibrated."""
    monkeypatch.setattr(app_module, "COMPASS_CALIBRATED", False)
    app = _app([180.0])
    # Use the real gated accessor rather than the scripted override.
    app.trusted_heading = MockApp.trusted_heading.__get__(app)

    app._orient_towards_route()

    assert app.spoken == []
    assert app.left_motor.events == []
    assert app.right_motor.events == []


def test_no_gps_fix_skips_orientation():
    """Without a position there is no bearing to aim at."""
    app = _app([180.0])
    app.gps_cache = _StubCache(None)

    app._orient_towards_route()

    assert app.spoken == []


def test_no_active_route_skips_orientation():
    app = _app([180.0])
    app.nav_monitor.clear()

    app._orient_towards_route()

    assert app.spoken == []


def test_a_compass_that_drops_out_mid_turn_lets_them_walk():
    """Better to let the user set off than to buzz at them with nothing
    behind it."""
    app = _OrientingApp([180.0, None])
    app.gps_cache = _StubCache(_fix())
    app.nav_monitor.set_route(_northward_route(), "Home")
    app.front_motor = MockVibrationMotor()
    app.left_motor = MockVibrationMotor()
    app.right_motor = MockVibrationMotor()

    app._orient_towards_route()

    assert app.spoken == ["Start walking, and I will guide you from there."]


def test_missing_motors_are_survivable():
    app = _app([90.0, 90.0, 0.0])
    app.front_motor = app.left_motor = app.right_motor = None

    app._orient_towards_route()

    assert app.spoken == ["Walk straight ahead."]


def _wait_until(predicate, timeout_s: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()
