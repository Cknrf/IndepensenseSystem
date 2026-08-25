"""Payload-shape unit tests.

These test the pure functions that translate our internal dataclasses
into the JSON shape the NestJS backend accepts. If a test here fails, it
means the client would send a payload the backend rejects — a real
integration break, not a stylistic issue.
"""
from datetime import datetime, timezone

from indepensense.telemetry.base import AlertEvent, EventType, IntervalInformation
from indepensense.telemetry.nestjs_client import alert_payload, heartbeat_payload


_TEST_DEVICE_ID = "00000000-0000-0000-0000-000000000001"
_TEST_TIMESTAMP = datetime(2026, 7, 25, 10, 30, 0, tzinfo=timezone.utc)


def test_heartbeat_payload_matches_backend_contract():
    info = IntervalInformation(
        device_id=_TEST_DEVICE_ID,
        battery_health=78,
        internet_status=True,
        latitude=60.1699,
        longitude=24.9384,
        created_at=_TEST_TIMESTAMP,
    )
    payload = heartbeat_payload(info)
    assert payload == {
        "batteryHealth": 78,
        "internetStatus": True,
        "latitude": 60.1699,
        "longitude": 24.9384,
    }


def test_heartbeat_payload_preserves_boolean_type():
    """internetStatus must be JSON boolean, not string 'true'."""
    info = IntervalInformation(
        device_id="x", battery_health=100, internet_status=False,
        latitude=0.0, longitude=0.0, created_at=_TEST_TIMESTAMP,
    )
    assert heartbeat_payload(info)["internetStatus"] is False


def test_alert_payload_uses_backend_typo():
    """The backend field is `occuredAt` (missing 'r' in 'occurred').
    This test guards against someone 'fixing' the spelling and silently
    breaking integration — both sides must match."""
    event = AlertEvent(
        device_id=_TEST_DEVICE_ID,
        event_type=EventType.FALL_DETECTION,
        latitude=60.1720,
        longitude=24.9450,
        occurred_at=_TEST_TIMESTAMP,
    )
    payload = alert_payload(event)
    assert "occuredAt" in payload
    assert "occurredAt" not in payload


def test_alert_payload_matches_backend_contract():
    event = AlertEvent(
        device_id=_TEST_DEVICE_ID,
        event_type=EventType.FALL_DETECTION,
        latitude=60.1720,
        longitude=24.9450,
        occurred_at=_TEST_TIMESTAMP,
    )
    payload = alert_payload(event)
    assert payload == {
        "eventType": "Fall Detection",
        "latitude": 60.1720,
        "longitude": 24.9450,
        "occuredAt": "2026-07-25T10:30:00+00:00",
    }


def test_no_payload_carries_a_device_id():
    """Identity comes from the bearer token now. Sending `deviceID` was
    the whole vulnerability — it let any caller claim to be any device —
    so its absence is the thing worth pinning, not its format."""
    info = IntervalInformation(
        device_id=_TEST_DEVICE_ID, battery_health=50, internet_status=True,
        latitude=0.0, longitude=0.0, created_at=_TEST_TIMESTAMP,
    )
    event = AlertEvent(
        device_id=_TEST_DEVICE_ID, event_type=EventType.FALL_DETECTION,
        latitude=0.0, longitude=0.0, occurred_at=_TEST_TIMESTAMP,
    )
    for payload in (heartbeat_payload(info), alert_payload(event)):
        assert "deviceID" not in payload
        assert _TEST_DEVICE_ID not in str(payload)


def test_heartbeat_does_not_send_a_timestamp():
    """The server timestamps this row itself. The Pi has no RTC, so its
    clock is wrong between boot and NTP settling — sending it would put
    heartbeats in the dashboard at times they did not happen."""
    info = IntervalInformation(
        device_id=_TEST_DEVICE_ID, battery_health=50, internet_status=True,
        latitude=0.0, longitude=0.0, created_at=_TEST_TIMESTAMP,
    )
    assert "createdAt" not in heartbeat_payload(info)


def test_alert_still_sends_when_it_happened():
    """Unlike heartbeats, an alert's timestamp matters: it can sit in the
    retry queue for hours while offline, so delivery time is not event
    time."""
    event = AlertEvent(
        device_id=_TEST_DEVICE_ID, event_type=EventType.EMERGENCY_ALERT,
        latitude=0.0, longitude=0.0, occurred_at=_TEST_TIMESTAMP,
    )
    assert alert_payload(event)["occuredAt"] == "2026-07-25T10:30:00+00:00"


def test_all_event_types_serialise_to_backend_strings():
    """The backend's whitelist requires these exact strings. It is a DB
    enum, so an unrecognised value currently causes a 500 rather than a
    400 — a malformed alert looks like a backend outage."""
    assert EventType.EMERGENCY_ALERT.value == "Emergency Alert"
    assert EventType.FALL_DETECTION.value == "Fall Detection"
    assert EventType.LOW_BATTERY.value == "Low Battery"
    assert EventType.CONNECTIVITY.value == "Connectivity"


def test_all_event_types_have_alert_payload_support():
    """Every EventType should produce a valid alert_payload without
    raising."""
    for event_type in EventType:
        event = AlertEvent(
            device_id="x", event_type=event_type,
            latitude=0.0, longitude=0.0, occurred_at=_TEST_TIMESTAMP,
        )
        payload = alert_payload(event)
        assert payload["eventType"] == event_type.value
