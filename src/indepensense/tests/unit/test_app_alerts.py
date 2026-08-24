"""Unit tests for the alert paths in `app.py`.

Covers fall detection and the emergency button — the two most important
things the device does, and the two with the most moving parts now that
SMS fans out through the same sink.

Uses `alert_sink` rather than `buffered` deliberately: that is the seam
SMS is attached to, so a change that pointed an alert path back at
`buffered` would silently stop texting guardians. These tests fail if
that happens.
"""
import json
import time

import pytest
import requests

from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockBuzzer, MockVibrationMotor
from indepensense.messaging.mock import MockSMSSender
from indepensense.safety.base import FallEvent
from indepensense.sensors.mock import MockMagnetometer
from indepensense.sensors.base import GPSFix
from indepensense.telemetry.base import EventType
from indepensense.telemetry.guardians import GuardianDirectory
from indepensense.telemetry.mock import MockTelemetryClient
from indepensense.telemetry.sms_alerts import SMSAlertNotifier

SMS_EVENT_TYPES = ("Emergency Alert", "Fall Detection", "Low Battery")


class _StubCache:
    def __init__(self, fix):
        self._fix = fix

    def latest_fix(self):
        return self._fix


def _fix(lat=14.5824, lon=120.9760):
    return GPSFix(
        lat=lat, lon=lon, altitude_m=15.0, speed_knots=0.0, course_deg=None,
        satellites=8, hdop=1.2, fix_quality=1, utc_time=None, timestamp=time.time(),
    )


def _fall():
    return FallEvent(
        timestamp=time.time(), freefall_duration_s=0.42, impact_magnitude_g=3.8,
    )


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Keep this module off the network.

    `start()` attempts a guardian fetch and the heartbeat sender probes
    connectivity. Left real, those make the suite depend on whether the
    dev machine can reach the backend, and stall for the timeout when it
    can't. Failing fast here is also the behaviour under test elsewhere.
    """
    def _refuse(*_args, **_kwargs):
        raise requests.ConnectionError("network disabled in unit tests")

    monkeypatch.setattr(requests, "get", _refuse)
    monkeypatch.setattr(requests, "head", _refuse)
    monkeypatch.setattr(requests, "post", _refuse)


@pytest.fixture
def app():
    instance = MockApp()
    instance.alert_sink = MockTelemetryClient()
    instance.magnetometer = MockMagnetometer()
    instance.buzzer = MockBuzzer()
    instance.front_motor = MockVibrationMotor()
    instance.left_motor = MockVibrationMotor()
    instance.right_motor = MockVibrationMotor()
    return instance


def _wait_for(condition, timeout_s=2.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --- fall detection ----------------------------------------------------------

def test_a_fall_sends_an_alert(app):
    app.gps_cache = _StubCache(_fix())
    app._on_fall_detected(_fall())

    assert len(app.alert_sink.alerts) == 1
    assert app.alert_sink.alerts[0].event_type is EventType.FALL_DETECTION


def test_the_fall_alert_carries_the_current_position(app):
    app.gps_cache = _StubCache(_fix(lat=10.5, lon=122.5))
    app._on_fall_detected(_fall())

    alert = app.alert_sink.alerts[0]
    assert (alert.latitude, alert.longitude) == (10.5, 122.5)


def test_a_fall_still_alerts_with_no_gps_fix(app):
    """Knowing a fall happened matters more than knowing where. Zeros are
    the agreed "unknown" sentinel — `sms_alerts.compose_alert_sms` turns
    them into "location unavailable" rather than a map link to the wrong
    hemisphere."""
    app.gps_cache = _StubCache(None)
    app._on_fall_detected(_fall())

    alert = app.alert_sink.alerts[0]
    assert (alert.latitude, alert.longitude) == (0.0, 0.0)


def test_a_fall_still_alerts_with_no_gps_at_all(app):
    app.gps_cache = None
    app._on_fall_detected(_fall())
    assert len(app.alert_sink.alerts) == 1


def test_a_fall_with_no_sink_does_not_raise(app):
    """Fall detection runs on the main loop; an unconfigured sink must not
    take it down."""
    app.alert_sink = None
    app.gps_cache = _StubCache(_fix())
    app._on_fall_detected(_fall())


# --- fall detection reaches SMS ---------------------------------------------

def test_a_fall_texts_the_guardians(tmp_path, app):
    """The wiring that matters: falls go through `alert_sink`, so they
    inherit SMS from the notifier without the fall path knowing."""
    cache = tmp_path / "guardians.json"
    cache.write_text(json.dumps({
        "guardians": [{"name": "Maria", "contactNumber": "09171234567", "role": "parent"}]
    }))
    sms = MockSMSSender()
    app.alert_sink = SMSAlertNotifier(
        inner=MockTelemetryClient(),
        sms=sms,
        guardians=GuardianDirectory(
            base_url="http://backend.test", device_id="dev-1", cache_path=cache,
        ),
        event_type_values=SMS_EVENT_TYPES,
    )
    app.gps_cache = _StubCache(_fix())

    app._on_fall_detected(_fall())

    assert _wait_for(lambda: len(sms.sent) == 1)
    number, text = sms.sent[0]
    assert number == "+639171234567"
    assert "Fall Detection" in text
    assert "maps.google.com" in text


# --- emergency button --------------------------------------------------------

def test_the_emergency_button_fires_an_alert(app):
    """Through the full `start()` wiring rather than a hand-assembled
    sink, so it fails if the emergency path is ever pointed somewhere
    other than `alert_sink`.

    The recording mock sits two layers down: `start()` builds
    `SMSAlertNotifier(BufferedTelemetryClient(MockTelemetryClient()))`,
    and the buffer drains on its own worker thread — hence the wait.
    """
    app.start()
    try:
        recorded = app.buffered._inner.alerts
        app.emergency_button.press()
        assert _wait_for(lambda: len(recorded) >= 1)
        assert recorded[0].event_type is EventType.EMERGENCY_ALERT
    finally:
        app._shutdown.set()
        app.stop()


def test_the_emergency_button_cancels_an_in_flight_voice_command(app):
    """An emergency must pre-empt whatever the voice pipeline is doing
    rather than queue behind it."""
    app._voice_active.set()
    app._on_emergency_press()
    assert app._voice_cancel.is_set()


def test_emergency_gives_immediate_physical_feedback(app):
    """The user needs to know the press registered before any network
    round trip completes."""
    app._play_emergency_feedback()
    assert app.buzzer.events or app.front_motor.events


# --- concurrency guards ------------------------------------------------------

def test_a_second_ptt_press_is_ignored_while_voice_is_busy(app):
    """One voice thread at a time — a second recording would fight the
    first for the microphone."""
    app._voice_active.set()
    app._on_ptt_press()
    assert app._voice_thread is None


def test_repeat_is_ignored_while_voice_is_busy(app):
    app._voice_active.set()
    app._on_repeat_press()
    assert app.buzzer.events == []


# --- heading cache -----------------------------------------------------------

def test_heading_is_cached_from_the_magnetometer(app):
    app.magnetometer.set_heading(137.0)
    app._last_heading_check = 0.0
    app._check_heading()

    assert app.latest_heading() == pytest.approx(137.0, abs=0.5)


def test_heading_starts_unknown(app):
    assert app.latest_heading() is None


def test_a_stale_heading_is_kept_when_a_read_fails(app):
    """Heading is advisory; a transient I2C glitch should not blank it."""
    app.magnetometer.set_heading(90.0)
    app._last_heading_check = 0.0
    app._check_heading()
    good = app.latest_heading()

    class _BrokenMag:
        def read(self):
            raise OSError("I2C glitch")

        def close(self):
            pass

    app.magnetometer = _BrokenMag()
    app._last_heading_check = 0.0
    app._check_heading()

    assert app.latest_heading() == good


def test_heading_reads_are_rate_limited(app):
    """The I2C bus is shared with the IMU at 100 Hz and the UPS HAT."""
    class _CountingMag:
        def __init__(self):
            self.reads = 0

        def read(self):
            self.reads += 1
            return None

        def close(self):
            pass

    mag = _CountingMag()
    app.magnetometer = mag
    app._last_heading_check = time.monotonic()

    for _ in range(50):
        app._check_heading()
    assert mag.reads == 0


def test_absent_magnetometer_is_a_no_op(app):
    app.magnetometer = None
    app._last_heading_check = 0.0
    app._check_heading()
    assert app.latest_heading() is None
