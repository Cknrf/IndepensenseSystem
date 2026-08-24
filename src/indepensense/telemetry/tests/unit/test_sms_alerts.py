"""Unit tests for SMS fan-out on alerts.

The fan-out runs on a short-lived thread, so tests poll for completion
rather than asserting immediately after `send_alert` returns.
"""
import json
import time
from datetime import datetime, timezone

import pytest
import requests

from indepensense.messaging.mock import MockSMSSender
from indepensense.telemetry.base import AlertEvent, EventType
from indepensense.telemetry.guardians import GuardianDirectory
from indepensense.telemetry.mock import MockTelemetryClient
from indepensense.telemetry.sms_alerts import SMSAlertNotifier, compose_alert_sms

SMS_EVENT_TYPES = ("Emergency Alert", "Fall Detection", "Low Battery")

_OCCURRED_AT = datetime(2026, 8, 24, 9, 5, tzinfo=timezone.utc)


def _alert(event_type=EventType.EMERGENCY_ALERT, lat=14.5824, lon=120.9760) -> AlertEvent:
    return AlertEvent(
        device_id="dev-1",
        event_type=event_type,
        latitude=lat,
        longitude=lon,
        occurred_at=_OCCURRED_AT,
    )


def _directory(tmp_path, *numbers: str) -> GuardianDirectory:
    """A directory pre-seeded via its cache file — no network needed."""
    cache = tmp_path / "guardians.json"
    cache.write_text(json.dumps({
        "guardians": [
            {"name": f"G{i}", "contactNumber": n, "role": "parent"}
            for i, n in enumerate(numbers)
        ]
    }))
    return GuardianDirectory(
        base_url="http://backend.test",
        device_id="dev-1",
        cache_path=cache,
    )


def _wait_until(condition, timeout_s: float = 2.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


# --- message composition -----------------------------------------------------

def test_message_carries_a_map_link_and_stays_in_one_part():
    text = compose_alert_sms(_alert())
    assert "maps.google.com/?q=14.582400,120.976000" in text
    assert "Emergency Alert" in text
    # Over 160 characters an SMS is split into multiple parts, which costs
    # more and can arrive out of order.
    assert len(text) <= 160


def test_message_admits_when_there_is_no_gps_fix():
    """(0.0, 0.0) means no lock, not the Gulf of Guinea. Sending a
    guardian a map link to the wrong hemisphere during an emergency is
    worse than saying we don't know."""
    text = compose_alert_sms(_alert(lat=0.0, lon=0.0))
    assert "maps.google.com" not in text
    assert "unavailable" in text.lower()


# --- fan-out -----------------------------------------------------------------

def test_alert_texts_every_guardian(tmp_path):
    sms = MockSMSSender()
    inner = MockTelemetryClient()
    notifier = SMSAlertNotifier(
        inner, sms, _directory(tmp_path, "09171234567", "09281234567"),
        SMS_EVENT_TYPES,
    )

    assert notifier.send_alert(_alert()) is True
    assert _wait_until(lambda: len(sms.sent) == 2)
    assert {number for number, _ in sms.sent} == {"+639171234567", "+639281234567"}
    # The HTTP alert still goes out.
    assert len(inner.alerts) == 1


def test_one_bad_number_does_not_stop_the_others(tmp_path):
    """The case that matters: a typo in one guardian's number must not
    silence the notification to everyone else."""
    sms = MockSMSSender(fail_numbers={"+639171234567"})
    notifier = SMSAlertNotifier(
        MockTelemetryClient(), sms,
        _directory(tmp_path, "09171234567", "09281234567"),
        SMS_EVENT_TYPES,
    )

    notifier.send_alert(_alert())
    assert _wait_until(lambda: notifier.sms_failed_count == 1)
    assert _wait_until(lambda: notifier.sms_sent_count == 1)
    assert [number for number, _ in sms.sent] == ["+639281234567"]


def test_a_raising_sender_does_not_stop_the_others(tmp_path):
    class _Exploding:
        def __init__(self):
            self.calls = 0

        def send(self, number, text):
            self.calls += 1
            raise RuntimeError("driver bug")

        def close(self):
            pass

    sender = _Exploding()
    notifier = SMSAlertNotifier(
        MockTelemetryClient(), sender,
        _directory(tmp_path, "09171234567", "09281234567"),
        SMS_EVENT_TYPES,
    )
    notifier.send_alert(_alert())
    assert _wait_until(lambda: sender.calls == 2)
    assert notifier.sms_failed_count == 2


@pytest.mark.parametrize(
    "event_type,should_text",
    [
        (EventType.EMERGENCY_ALERT, True),
        (EventType.FALL_DETECTION, True),
        (EventType.LOW_BATTERY, True),
        # Fires on every network transition, and an SMS about connectivity
        # is the one thing a guardian cannot act on.
        (EventType.CONNECTIVITY, False),
    ],
)
def test_only_configured_event_types_are_texted(tmp_path, event_type, should_text):
    sms = MockSMSSender()
    notifier = SMSAlertNotifier(
        MockTelemetryClient(), sms, _directory(tmp_path, "09171234567"),
        SMS_EVENT_TYPES,
    )
    notifier.send_alert(_alert(event_type=event_type))

    if should_text:
        assert _wait_until(lambda: len(sms.sent) == 1)
    else:
        # Give the thread a chance to have done the wrong thing.
        time.sleep(0.15)
        assert sms.sent == []


def test_heartbeats_are_never_texted(tmp_path):
    """Texting a guardian every 30 seconds would be useless and expensive."""
    from indepensense.telemetry.base import IntervalInformation

    sms = MockSMSSender()
    inner = MockTelemetryClient()
    notifier = SMSAlertNotifier(
        inner, sms, _directory(tmp_path, "09171234567"), SMS_EVENT_TYPES,
    )

    notifier.send_heartbeat(IntervalInformation(
        device_id="dev-1", battery_health=90, internet_status=True,
        latitude=14.5824, longitude=120.9760, created_at=_OCCURRED_AT,
    ))
    time.sleep(0.15)
    assert sms.sent == []
    assert len(inner.heartbeats) == 1


def test_no_guardians_is_survivable(tmp_path):
    """An empty list must not raise — the alert still has to reach HTTP."""
    sms = MockSMSSender()
    inner = MockTelemetryClient()
    notifier = SMSAlertNotifier(inner, sms, _directory(tmp_path), SMS_EVENT_TYPES)

    assert notifier.send_alert(_alert()) is True
    assert sms.attempts == []
    assert len(inner.alerts) == 1


def test_http_result_is_not_affected_by_sms_outcome(tmp_path):
    """An unreachable backend and an unreachable cell network are different
    failures; the return value governs only the former's retry logic."""
    sms = MockSMSSender(fail_numbers={"+639171234567"})
    inner = MockTelemetryClient(succeed=False)
    notifier = SMSAlertNotifier(
        inner, sms, _directory(tmp_path, "09171234567"), SMS_EVENT_TYPES,
    )
    assert notifier.send_alert(_alert()) is False
