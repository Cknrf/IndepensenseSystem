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
from indepensense.conftest import TEST_BACKEND_URL, make_credential
from indepensense.telemetry.buffered import BufferedTelemetryClient
from indepensense.telemetry.guardians import GuardianDirectory
from indepensense.telemetry.mock import MockTelemetryClient
from indepensense.telemetry.null import NullTelemetryClient
from indepensense.telemetry.sms_alerts import (
    SMS_NO_MODEM,
    SMS_FAILED,
    SMS_NO_NUMBER,
    SMS_SENT,
    SMS_UNAVAILABLE,
    SMSAlertNotifier,
    compose_alert_sms,
)

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
        base_url=TEST_BACKEND_URL,
        credential=make_credential(),
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
    """A driver bug on one recipient must not cost the others.

    The call count is deliberately not asserted. It used to be `== 2`,
    one attempt per number, and that was the contract before retries
    existed — the assertion then failed for a reason that had nothing to
    do with what the test is named after. What matters is that both
    numbers were attempted and both were counted as failed; how many
    times each was retried is the retry policy's business, and tested
    where that policy lives.
    """
    class _Exploding:
        def __init__(self):
            self.numbers = []

        def send(self, number, text):
            self.numbers.append(number)
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

    assert _wait_until(lambda: notifier.sms_failed_count == 2)
    assert set(sender.numbers) == {"+639171234567", "+639281234567"}


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


# --- delivery reporting ------------------------------------------------------
#
# The wearable told a user "Emergency alert sent to your guardian" through
# a whole test session in which every SMS was refused by polkit, because
# `send_alert`'s boolean only ever covered the HTTP leg. These tests pin
# the per-channel report that replaced that guess.

def _report_collector():
    """A delivery callback plus the list it appends to."""
    received = []
    return received, lambda event, delivery: received.append((event, delivery))


def _deliver(tmp_path, *, numbers, backend_ok, fail_numbers=frozenset()):
    """Fire one alert and return the `AlertDelivery` that was reported."""
    received, on_delivery = _report_collector()
    notifier = SMSAlertNotifier(
        MockTelemetryClient(succeed=backend_ok),
        MockSMSSender(fail_numbers=set(fail_numbers)),
        _directory(tmp_path, *numbers),
        SMS_EVENT_TYPES,
        on_delivery=on_delivery,
    )
    notifier.send_alert(_alert())
    assert _wait_until(lambda: len(received) == 1), "no delivery report arrived"
    return received[0][1]


def test_delivery_reports_both_channels_succeeding(tmp_path):
    delivery = _deliver(tmp_path, numbers=["09171234567"], backend_ok=True)
    assert delivery.backend_ok is True
    assert delivery.sms == SMS_SENT


def test_delivery_reports_a_refused_sms(tmp_path):
    """The exact field failure: HTTP fine, modem refusing every message."""
    delivery = _deliver(
        tmp_path,
        numbers=["09171234567"],
        backend_ok=True,
        fail_numbers={"+639171234567"},
    )
    assert delivery.backend_ok is True
    assert delivery.sms == SMS_FAILED


def test_delivery_distinguishes_no_number_from_a_failed_send(tmp_path):
    """Two different things to tell the user: one is fixed by a guardian
    filling in the web form, the other is a fault on the device."""
    delivery = _deliver(tmp_path, numbers=[], backend_ok=True)
    assert delivery.sms == SMS_NO_NUMBER


def test_delivery_reports_both_channels_failing(tmp_path):
    delivery = _deliver(
        tmp_path,
        numbers=["09171234567"],
        backend_ok=False,
        fail_numbers={"+639171234567"},
    )
    assert delivery.backend_ok is False
    assert delivery.sms == SMS_FAILED


def test_delivery_reports_sms_through_with_the_backend_down(tmp_path):
    """Offline but on the cell network — a guardian still gets the text."""
    delivery = _deliver(tmp_path, numbers=["09171234567"], backend_ok=False)
    assert delivery.backend_ok is False
    assert delivery.sms == SMS_SENT


def test_one_guardian_reached_counts_as_sent(tmp_path):
    """A partial success is still a person who knows. The wearer does not
    need a roll call; the per-number detail is in the log."""
    delivery = _deliver(
        tmp_path,
        numbers=["09171234567", "09281234567"],
        backend_ok=True,
        fail_numbers={"+639171234567"},
    )
    assert delivery.sms == SMS_SENT


def test_untexted_event_types_are_not_reported(tmp_path):
    """Connectivity events never text anyone, so there is no delivery to
    report and the wearer must not be interrupted about one."""
    received, on_delivery = _report_collector()
    notifier = SMSAlertNotifier(
        MockTelemetryClient(), MockSMSSender(),
        _directory(tmp_path, "09171234567"), SMS_EVENT_TYPES,
        on_delivery=on_delivery,
    )
    notifier.send_alert(_alert(event_type=EventType.CONNECTIVITY))
    time.sleep(0.15)
    assert received == []


def test_a_raising_delivery_callback_does_not_lose_the_sms(tmp_path):
    """The callback speaks, so it touches TTS and the announcer. A failure
    there must not take the fan-out thread down with it."""
    sms = MockSMSSender()
    notifier = SMSAlertNotifier(
        MockTelemetryClient(), sms, _directory(tmp_path, "09171234567"),
        SMS_EVENT_TYPES,
        on_delivery=lambda event, delivery: 1 / 0,
    )
    notifier.send_alert(_alert())
    assert _wait_until(lambda: len(sms.sent) == 1)


def test_no_callback_keeps_the_old_silent_behaviour(tmp_path):
    """`on_delivery` is optional — without it the notifier logs and counts
    exactly as it did before reporting existed."""
    sms = MockSMSSender()
    notifier = SMSAlertNotifier(
        MockTelemetryClient(), sms, _directory(tmp_path, "09171234567"),
        SMS_EVENT_TYPES,
    )
    assert notifier.send_alert(_alert()) is True
    assert _wait_until(lambda: notifier.sms_sent_count == 1)


# --- the production wiring: a buffered inner client ---------------------------
#
# The runtime wraps BufferedTelemetryClient, whose send_alert returns True
# on queueing. Reporting that as the backend result made `backend_ok`
# permanently True: offline with a refusing modem, the wearer heard "your
# guardian was notified online" when nobody had been told anything.

def _deliver_buffered(tmp_path, *, backend_ok, fail_numbers=frozenset()):
    received, on_delivery = _report_collector()
    buffered = BufferedTelemetryClient(
        MockTelemetryClient(succeed=backend_ok), retry_interval_s=60.0,
    )
    try:
        notifier = SMSAlertNotifier(
            buffered,
            MockSMSSender(fail_numbers=set(fail_numbers)),
            _directory(tmp_path, "09171234567"),
            SMS_EVENT_TYPES,
            on_delivery=on_delivery,
        )
        assert notifier.send_alert(_alert()) is True   # queued
        assert _wait_until(lambda: len(received) == 1), "no delivery report arrived"
        return received[0][1]
    finally:
        buffered.close(drain_timeout_s=0.1)


def test_a_buffered_backend_that_is_down_is_reported_as_down(tmp_path):
    delivery = _deliver_buffered(
        tmp_path, backend_ok=False, fail_numbers={"+639171234567"},
    )
    assert delivery.backend_ok is False
    assert delivery.sms == SMS_FAILED


def test_a_buffered_backend_that_is_up_is_reported_as_up(tmp_path):
    delivery = _deliver_buffered(tmp_path, backend_ok=True)
    assert delivery.backend_ok is True
    assert delivery.sms == SMS_SENT


# --- no SMS sender, or no backend credential ----------------------------------

def _report(notifier_inner, sms, tmp_path):
    received, on_delivery = _report_collector()
    notifier = SMSAlertNotifier(
        notifier_inner, sms, _directory(tmp_path, "09171234567"),
        SMS_EVENT_TYPES, on_delivery=on_delivery,
    )
    notifier.send_alert(_alert())
    assert _wait_until(lambda: len(received) == 1), "no delivery report arrived"
    return received[0][1]


def test_without_an_sms_sender_the_backend_result_is_still_reported(tmp_path):
    buffered = BufferedTelemetryClient(
        MockTelemetryClient(succeed=False), retry_interval_s=60.0,
    )
    try:
        delivery = _report(buffered, None, tmp_path)
    finally:
        buffered.close(drain_timeout_s=0.1)
    assert delivery == type(delivery)(backend_ok=False, sms=SMS_UNAVAILABLE)


def test_without_an_sms_sender_a_reached_backend_is_reported_as_reached(tmp_path):
    delivery = _report(MockTelemetryClient(succeed=True), None, tmp_path)
    assert delivery.backend_ok is True
    assert delivery.sms == SMS_UNAVAILABLE


def test_an_unprovisioned_unit_does_not_claim_the_dashboard_was_reached(tmp_path):
    buffered = BufferedTelemetryClient(
        NullTelemetryClient(), retry_interval_s=60.0, reaches_backend=False,
    )
    try:
        delivery = _report(
            buffered, MockSMSSender(fail_numbers={"+639171234567"}), tmp_path,
        )
    finally:
        buffered.close(drain_timeout_s=0.1)
    assert delivery.backend_ok is False
    assert delivery.sms == SMS_FAILED


# --- the three knobs ---------------------------------------------------------
#
# The SMS leg used to run to completion before anything was spoken, so
# three 30-second modem timeouts meant 90 seconds of silence after an
# emergency press — with the backend already succeeded a second in. The
# deadline bounds *telling the user*; the retry window bounds *trying*;
# retryability decides which failures are worth either.

class _Recording:
    """A sender whose outcome can change between rounds."""

    def __init__(self, results):
        # results: list of (sent, retryable) consumed per call, last repeats.
        self._results = list(results)
        self.calls = []

    def send(self, number, text):
        from indepensense.messaging.base import SMSResult
        self.calls.append(number)
        sent, retryable = (
            self._results.pop(0) if len(self._results) > 1 else self._results[0]
        )
        return SMSResult(number, sent, "" if sent else "nope", retryable=retryable)

    def close(self):
        pass


def _notifier(tmp_path, sender, received=None, **kwargs):
    kwargs.setdefault("report_deadline_s", 5.0)
    kwargs.setdefault("attempt_delays_s", (0.0,))
    kwargs.setdefault("retry_window_s", 0.0)
    kwargs.setdefault("retry_backoff_s", ())
    kwargs.setdefault("sleep", lambda _s: None)
    return SMSAlertNotifier(
        MockTelemetryClient(), sender, _directory(tmp_path, "09171234567"),
        SMS_EVENT_TYPES,
        on_delivery=(lambda e, d: received.append(d)) if received is not None else None,
        **kwargs,
    )


def test_a_modem_that_is_gone_is_not_retried(tmp_path):
    """`retryable=False` is the driver saying another attempt cannot
    help. Three attempts against an absent modem cost ninety seconds to
    learn what the first one already knew."""
    sender = _Recording([(False, False)])
    notifier = _notifier(tmp_path, sender, attempt_delays_s=(0.0, 0.0, 0.0))

    notifier.send_alert(_alert())

    assert _wait_until(lambda: notifier.sms_failed_count == 1)
    assert len(sender.calls) == 1, f"retried an absent modem: {sender.calls}"


def test_a_transient_failure_is_retried(tmp_path):
    """The distinction only earns its keep if the other side still is."""
    sender = _Recording([(False, True)])
    notifier = _notifier(tmp_path, sender, attempt_delays_s=(0.0, 0.0, 0.0))

    notifier.send_alert(_alert())

    assert _wait_until(lambda: notifier.sms_failed_count == 1)
    assert len(sender.calls) == 4, f"expected 4 attempts, got {sender.calls}"


def test_an_absent_modem_is_reported_as_its_own_state(tmp_path):
    """Not SMS_FAILED. The two need different things said: one is
    followed by a retry window the wearer is told about, the other is
    not, and promising a retry that will not happen is the lie this
    whole delivery report exists to remove."""
    received = []
    notifier = _notifier(tmp_path, _Recording([(False, False)]), received)

    notifier.send_alert(_alert())

    assert _wait_until(lambda: len(received) == 1)
    assert received[0].sms == SMS_NO_MODEM


def test_a_transient_failure_is_still_reported_as_failed(tmp_path):
    received = []
    notifier = _notifier(tmp_path, _Recording([(False, True)]), received)

    notifier.send_alert(_alert())

    assert _wait_until(lambda: len(received) == 1)
    assert received[0].sms == SMS_FAILED


def test_the_verdict_does_not_wait_for_the_retry_window(tmp_path):
    """The point of the whole change. The wearer hears the outcome on
    the deadline, and delivery carries on behind it."""
    received = []
    notifier = _notifier(
        tmp_path, _Recording([(False, True)]), received,
        retry_window_s=60.0, retry_backoff_s=(0.0, 0.0),
    )

    notifier.send_alert(_alert())

    assert _wait_until(lambda: len(received) == 1), "verdict waited for the window"


def test_delivery_keeps_being_attempted_after_the_verdict(tmp_path):
    """The messages promise "the system will keep retrying the text".
    Nothing honoured that until now — the fan-out returned and the alert
    was abandoned."""
    received = []
    sender = _Recording([(False, True)])
    notifier = _notifier(
        tmp_path, sender, received,
        retry_window_s=60.0, retry_backoff_s=(0.0, 0.0, 0.0),
    )

    notifier.send_alert(_alert())
    assert _wait_until(lambda: len(received) == 1)

    assert _wait_until(lambda: len(sender.calls) > 1), "gave up at the verdict"


def test_a_late_success_is_not_announced(tmp_path):
    """The wearer is mid-emergency and was told to seek help another
    way. A second announcement minutes later is noise; the guardian —
    who is the one that matters — has the text either way."""
    received = []
    sender = _Recording([(False, True), (True, True)])
    notifier = _notifier(
        tmp_path, sender, received,
        retry_window_s=60.0, retry_backoff_s=(0.0, 0.0),
    )

    notifier.send_alert(_alert())
    assert _wait_until(lambda: len(received) == 1)
    assert _wait_until(lambda: sender.calls.count("+639171234567") > 1)

    time.sleep(0.05)
    assert len(received) == 1, "spoke again after a late success"


def test_the_retry_window_is_bounded(tmp_path):
    """A text arriving forty minutes on describes a situation that has
    already resolved. The channel that retries indefinitely is the
    backend queue, not this one."""
    sender = _Recording([(False, True)])
    notifier = _notifier(
        tmp_path, sender, retry_window_s=0.0, retry_backoff_s=(0.0, 0.0, 0.0),
    )

    notifier.send_alert(_alert())
    assert _wait_until(lambda: notifier.sms_failed_count == 1)
    time.sleep(0.05)
    settled = len(sender.calls)
    time.sleep(0.05)

    assert len(sender.calls) == settled, "still retrying past the window"
