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
from datetime import datetime, timezone

import pytest
import requests

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockBuzzer, MockVibrationMotor
from indepensense.intents import messages
from indepensense.messaging.mock import MockSMSSender
from indepensense.safety.base import FallEvent
from indepensense.sensors.mock import MockMagnetometer
from indepensense.sensors.base import GPSFix
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.config import EMERGENCY_REARM_S
from indepensense.conftest import TEST_BACKEND_URL, make_credential
from indepensense.telemetry.guardians import GuardianDirectory
from indepensense.telemetry.mock import MockTelemetryClient
from indepensense.telemetry.sms_alerts import (
    SMS_FAILED,
    SMS_NO_NUMBER,
    SMS_SENT,
    AlertDelivery,
    SMSAlertNotifier,
)

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
            base_url=TEST_BACKEND_URL, credential=make_credential(), cache_path=cache,
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


# --- telling the wearer, not only the guardian -------------------------------
#
# Automatic fall detection used to notify guardians and say nothing at all
# to the person on the ground, who then had no way to know whether help was
# coming. (The emergency BUTTON always spoke — it was only the automatic
# path that was silent.)

class _RecordingApp(MockApp):
    def __init__(self):
        super().__init__()
        self.spoken: list[tuple[str, bool]] = []     # (text, critical)

    def _announce(self, text: str, critical: bool = False) -> None:
        self.spoken.append((text, critical))


@pytest.fixture
def speaking_app():
    instance = _RecordingApp()
    instance.alert_sink = MockTelemetryClient()
    return instance


def test_a_detected_fall_is_spoken_to_the_wearer(speaking_app):
    speaking_app._on_fall_detected(_fall())

    assert len(speaking_app.spoken) == 1
    text, _critical = speaking_app.spoken[0]
    assert text.strip() != ""


def test_the_fall_announcement_preempts_whatever_is_speaking(speaking_app):
    """A fall part-way through a turn instruction has to cut it off, not
    queue behind it."""
    speaking_app._on_fall_detected(_fall())

    _text, critical = speaking_app.spoken[0]
    assert critical is True


def test_the_guardian_alert_still_fires_alongside_the_announcement(speaking_app):
    """Speaking to the wearer must not have displaced the alert — both
    parties need to know."""
    speaking_app._on_fall_detected(_fall())

    fall_alerts = [
        a for a in speaking_app.alert_sink.alerts
        if a.event_type is EventType.FALL_DETECTION
    ]
    assert len(fall_alerts) == 1


def test_the_fall_announcement_follows_the_active_language(speaking_app):
    """A Tagalog user being told about their own fall in English would be
    the worst possible moment for the language switch to leak."""
    speaking_app.language.set("tl")
    speaking_app._on_fall_detected(_fall())
    tagalog = speaking_app.spoken[0][0]

    speaking_app.spoken.clear()
    speaking_app.language.set("en")
    speaking_app._on_fall_detected(_fall())
    english = speaking_app.spoken[0][0]

    assert tagalog != english


def test_a_failing_announcer_does_not_block_the_guardian_alert(speaking_app):
    """The alert is the part that summons help. It must survive a broken
    speaker — `_announce` swallows so nothing after it is skipped."""
    class _BrokenAnnouncer:
        def say(self, *args, **kwargs):
            raise OSError("audio device gone")

    plain = MockApp()
    plain.alert_sink = MockTelemetryClient()
    plain.announcer = _BrokenAnnouncer()

    plain._on_fall_detected(_fall())      # must not raise

    fall_alerts = [
        a for a in plain.alert_sink.alerts
        if a.event_type is EventType.FALL_DETECTION
    ]
    assert len(fall_alerts) == 1


# --- delivery reporting ------------------------------------------------------
#
# The wearable said "Emergency alert sent to your guardian" through a whole
# test session in which every SMS was refused by polkit, because the spoken
# response was built from the HTTP leg alone. `_on_alert_delivery` is the
# correction that follows once both channels have answered.

def _delivery(backend_ok, sms):
    return AlertDelivery(backend_ok=backend_ok, sms=sms)


def _emergency():
    return AlertEvent(
        device_id="dev-1", event_type=EventType.EMERGENCY_ALERT,
        latitude=14.5824, longitude=120.9760,
        occurred_at=datetime(2026, 8, 24, 9, 5, tzinfo=timezone.utc),
    )


def test_a_fully_delivered_alert_is_not_announced(speaking_app):
    """Nothing to correct. The wearer already heard the acknowledgement and
    does not need the same news twice."""
    speaking_app._on_alert_delivery(_emergency(), _delivery(True, SMS_SENT))
    assert speaking_app.spoken == []


@pytest.mark.parametrize("backend_ok,sms", [
    (True, SMS_FAILED),       # the field failure: polkit refusing every text
    (True, SMS_NO_NUMBER),    # nobody saved to text
    (False, SMS_SENT),        # offline, but the cell network worked
    (False, SMS_FAILED),      # nobody was told at all
    (False, SMS_NO_NUMBER),
])
def test_every_partial_failure_is_announced(speaking_app, backend_ok, sms):
    speaking_app._on_alert_delivery(_emergency(), _delivery(backend_ok, sms))

    assert len(speaking_app.spoken) == 1
    text, critical = speaking_app.spoken[0]
    assert text.strip() != ""
    # It corrects something the wearer is currently acting on, so it must
    # not queue behind an obstacle warning.
    assert critical is True


def test_the_four_failure_modes_are_told_apart(speaking_app):
    """A failed text with a working dashboard and nobody reached at all
    call for different responses from the user, so they must not collapse
    into one generic 'something went wrong'."""
    said = []
    for backend_ok, sms in [
        (True, SMS_FAILED), (True, SMS_NO_NUMBER), (False, SMS_SENT), (False, SMS_FAILED),
    ]:
        speaking_app.spoken.clear()
        speaking_app._on_alert_delivery(_emergency(), _delivery(backend_ok, sms))
        said.append(speaking_app.spoken[0][0])

    assert len(set(said)) == len(said)


def test_an_unmapped_delivery_state_reports_total_failure(speaking_app):
    """A state added to `sms_alerts.py` without a message here must not
    make the wearable go quiet about a failed emergency alert."""
    speaking_app._on_alert_delivery(_emergency(), _delivery(True, "something-new"))

    assert len(speaking_app.spoken) == 1
    pessimistic = messages.get("emergency.delivery.all_failed", "en")
    assert speaking_app.spoken[0][0] == pessimistic


def test_low_battery_delivery_is_not_announced(speaking_app):
    """Low battery texts guardians too, but the wearer already heard the
    battery warning — a delivery report on every one would be noise."""
    event = AlertEvent(
        device_id="dev-1", event_type=EventType.LOW_BATTERY,
        latitude=0.0, longitude=0.0,
        occurred_at=datetime(2026, 8, 24, 9, 5, tzinfo=timezone.utc),
    )
    speaking_app._on_alert_delivery(event, _delivery(True, SMS_FAILED))
    assert speaking_app.spoken == []


def test_the_delivery_report_follows_the_active_language(speaking_app):
    speaking_app.language.set("tl")
    speaking_app._on_alert_delivery(_emergency(), _delivery(True, SMS_FAILED))
    tagalog = speaking_app.spoken[0][0]

    speaking_app.spoken.clear()
    speaking_app.language.set("en")
    speaking_app._on_alert_delivery(_emergency(), _delivery(True, SMS_FAILED))
    english = speaking_app.spoken[0][0]

    assert tagalog != english


# --- the emergency button re-arm window --------------------------------------
#
# Three presses in a row in the field log produced three guardian
# notifications, three SMS attempts and three spoken confirmations talking
# over each other, all describing one event. Someone who has just pressed
# a panic button presses it again — that is what the button is for, and it
# must not multiply the alert.

@pytest.fixture
def pressable(app, monkeypatch):
    """An app whose emergency press is instrumented but does no I/O."""
    app.alert_sink = MockTelemetryClient()
    app.gps_cache = _StubCache(_fix())
    app.executor = _StubExecutor()
    monkeypatch.setattr(app, "_play_emergency_feedback", lambda: None)
    monkeypatch.setattr(app, "_play_button_ack", lambda: None)
    monkeypatch.setattr(app, "_announce", lambda text, critical=False: None)
    monkeypatch.setattr(app_module, "is_playing", lambda: False)
    return app


class _StubExecutor:
    def __init__(self):
        self.calls = 0

    def execute(self, result):
        self.calls += 1
        return "sending"


def test_the_three_press_sequence_sends_one_alert(pressable):
    """The field log, replayed."""
    for _ in range(3):
        pressable._on_emergency_press()

    assert pressable.executor.calls == 1


def test_a_suppressed_press_still_cancels_voice_work(pressable):
    """An emergency press must always interrupt. The user may have started
    a new command since the first press cleared the flag, and swallowing
    the cancel would leave the wearable mid-answer during an emergency."""
    pressable._on_emergency_press()
    pressable._voice_cancel.clear()          # as a new PTT command would

    pressable._on_emergency_press()

    assert pressable._voice_cancel.is_set()


def test_a_suppressed_press_is_still_felt(pressable, monkeypatch):
    """A panic button that gives nothing back reads as one that is not
    working — the worst possible moment for that impression."""
    acks = []
    monkeypatch.setattr(pressable, "_play_button_ack", lambda: acks.append(1))

    pressable._on_emergency_press()
    pressable._on_emergency_press()

    assert len(acks) == 1, "the repeat press gave no feedback"


def test_a_suppressed_press_does_not_talk_over_the_confirmation(
    pressable, monkeypatch,
):
    """"Already sent" is spoken as *critical*, which preempts — so saying
    it mid-announcement would cut off the very confirmation the user
    pressed again to hear."""
    said = []
    monkeypatch.setattr(pressable, "_announce",
                        lambda text, critical=False: said.append(text))
    monkeypatch.setattr(app_module, "is_playing", lambda: True)

    pressable._on_emergency_press()
    after_first = list(said)        # the first press speaks its own response
    pressable._on_emergency_press()

    assert said == after_first, "spoke over the confirmation in progress"


def test_a_suppressed_press_answers_into_silence(pressable, monkeypatch):
    """Press again nine seconds later, after everything has gone quiet,
    and the user must still be told why nothing happened."""
    said = []
    monkeypatch.setattr(pressable, "_announce",
                        lambda text, critical=False: said.append(text))

    pressable._on_emergency_press()
    pressable._on_emergency_press()

    assert said[-1] == messages.get("emergency.already_sent", "en")


def test_the_window_expires(pressable):
    """A genuine second emergency ten seconds after the first is a real
    thing. This is a debounce for a shaking hand, not a rate limit."""
    pressable._on_emergency_press()
    pressable._last_emergency_fired -= EMERGENCY_REARM_S + 1

    pressable._on_emergency_press()

    assert pressable.executor.calls == 2


def test_a_press_in_the_first_seconds_of_uptime_is_not_suppressed(pressable):
    """`time.monotonic()` counts from boot on Linux, so a zero sentinel
    would swallow any press in the first ten seconds of uptime — the one
    case where losing an alert is least acceptable."""
    assert pressable._last_emergency_fired == float("-inf")

    pressable._on_emergency_press()

    assert pressable.executor.calls == 1


def test_an_alert_that_reached_nobody_re_arms_the_button(pressable):
    """The one situation where mashing the button is exactly right. A
    debounce that blocked the retry would work against the user at the
    worst moment."""
    pressable._on_emergency_press()
    assert pressable.executor.calls == 1

    pressable._on_alert_delivery(_emergency(), AlertDelivery(False, SMS_FAILED))
    pressable._on_emergency_press()

    assert pressable.executor.calls == 2


def test_a_partly_delivered_alert_does_not_re_arm(pressable):
    """One channel through means a guardian knows. Re-sending on the next
    press would notify them twice about one event."""
    pressable._on_emergency_press()

    pressable._on_alert_delivery(_emergency(), AlertDelivery(True, SMS_FAILED))
    pressable._on_emergency_press()

    assert pressable.executor.calls == 1
