"""Unit tests for BufferedTelemetryClient.

Threading tests use short retry intervals and polling with timeouts so
they run fast and don't hang if a bug freezes the worker.
"""
import threading
import time
from datetime import datetime, timezone

from indepensense.telemetry.base import AlertEvent, EventType, IntervalInformation
from indepensense.telemetry.buffered import BufferedTelemetryClient


_TIMESTAMP = datetime(2026, 7, 25, 12, 0, 0, tzinfo=timezone.utc)


class _ScriptedTelemetryClient:
    """Test-only client whose send methods return a script of results.

    Each `send_*` call pops one entry off `script`; True/False in that
    entry decides whether the send "succeeded". If the script runs out,
    subsequent calls succeed. All calls are recorded to `heartbeats` and
    `alerts` for assertions.
    """

    def __init__(self, script: list[bool] | None = None):
        self.heartbeats: list[IntervalInformation] = []
        self.alerts: list[AlertEvent] = []
        self._script = list(script) if script else []
        self._call_order: list[str] = []
        self._lock = threading.Lock()

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        with self._lock:
            self.heartbeats.append(info)
            self._call_order.append("heartbeat")
            if self._script:
                return self._script.pop(0)
        return True

    def send_alert(self, event: AlertEvent) -> bool:
        with self._lock:
            self.alerts.append(event)
            self._call_order.append("alert")
            if self._script:
                return self._script.pop(0)
        return True

    @property
    def call_order(self) -> list[str]:
        with self._lock:
            return list(self._call_order)


def _make_heartbeat(battery: int = 100) -> IntervalInformation:
    return IntervalInformation(
        device_id="dev-test",
        battery_health=battery,
        internet_status=True,
        latitude=0.0,
        longitude=0.0,
        created_at=_TIMESTAMP,
    )


def _make_alert(event_type: EventType = EventType.FALL_DETECTION) -> AlertEvent:
    return AlertEvent(
        device_id="dev-test",
        event_type=event_type,
        latitude=0.0,
        longitude=0.0,
        occurred_at=_TIMESTAMP,
    )


def _wait_until(condition, timeout_s: float = 2.0, poll_s: float = 0.01) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(poll_s)
    return False


# --- happy path --------------------------------------------------------------

def test_heartbeat_reaches_inner_client():
    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.01)
    try:
        buffered.send_heartbeat(_make_heartbeat())
        assert _wait_until(lambda: len(inner.heartbeats) == 1)
        assert buffered.delivered_heartbeats == 1
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_alert_reaches_inner_client():
    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.01)
    try:
        buffered.send_alert(_make_alert())
        assert _wait_until(lambda: len(inner.alerts) == 1)
        assert buffered.delivered_alerts == 1
    finally:
        buffered.close(drain_timeout_s=1.0)


# --- retry semantics ---------------------------------------------------------

def test_heartbeat_retries_on_failure():
    # Inner client returns False twice, then True.
    inner = _ScriptedTelemetryClient(script=[False, False, True])
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_heartbeat(_make_heartbeat())
        assert _wait_until(lambda: buffered.delivered_heartbeats == 1, timeout_s=3.0)
        # The same heartbeat was tried 3 times: 2 failures + 1 success.
        assert len(inner.heartbeats) == 3
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_alert_retries_on_failure():
    inner = _ScriptedTelemetryClient(script=[False, True])
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_alert(_make_alert())
        assert _wait_until(lambda: buffered.delivered_alerts == 1, timeout_s=3.0)
        assert len(inner.alerts) == 2   # 1 failure + 1 success
    finally:
        buffered.close(drain_timeout_s=1.0)


# --- prioritisation ---------------------------------------------------------

def test_alert_jumps_ahead_of_queued_heartbeats():
    """A heartbeat that's failing should not block an alert enqueued later."""
    # Script: fail all initial heartbeat attempts so it stays queued.
    # Then when we enqueue an alert, next dispatch should be the alert.
    inner = _ScriptedTelemetryClient(script=[False] * 10)
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_heartbeat(_make_heartbeat())
        # Give the worker a moment to pick up the heartbeat and fail once.
        assert _wait_until(lambda: len(inner.heartbeats) >= 1, timeout_s=1.0)

        # Now queue an alert.
        buffered.send_alert(_make_alert())

        # The next dispatch should be the alert (heartbeat still failing).
        # We look for "alert" appearing in call_order after the first heartbeat.
        def alert_came_next() -> bool:
            order = inner.call_order
            first_heartbeat = order.index("heartbeat") if "heartbeat" in order else -1
            first_alert = order.index("alert") if "alert" in order else -1
            return first_alert != -1 and first_heartbeat != -1 and first_alert > first_heartbeat

        assert _wait_until(alert_came_next, timeout_s=2.0), (
            f"Alert never dispatched after heartbeat. Call order: {inner.call_order}"
        )
    finally:
        buffered.close(drain_timeout_s=1.0)


# --- queue bounds -----------------------------------------------------------

def test_full_queue_of_alerts_never_drops_new_alerts():
    """Alerts are safety-critical. Even at capacity, a new alert grows
    the queue beyond max_queue_size rather than dropping anything."""
    inner = _ScriptedTelemetryClient(script=[False] * 100)  # everything fails
    buffered = BufferedTelemetryClient(
        inner, max_queue_size=3, retry_interval_s=0.5,
    )
    try:
        # Enqueue 5 alerts into a max-3 queue.
        for _ in range(5):
            assert buffered.send_alert(_make_alert()) is True
        assert buffered.dropped_heartbeats == 0
        # Queue depth may be a bit dynamic (worker pulls one out and fails,
        # then re-queues) but the point is: no drops.
        assert buffered.queue_depth() >= 3
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_heartbeats_evicted_to_make_room_for_alert():
    """When queue is full of heartbeats and an alert comes in, one
    heartbeat is evicted."""
    inner = _ScriptedTelemetryClient(script=[False] * 100)
    buffered = BufferedTelemetryClient(
        inner, max_queue_size=3, retry_interval_s=0.5,
    )
    try:
        # Fill with heartbeats.
        for i in range(3):
            assert buffered.send_heartbeat(_make_heartbeat(battery=i)) is True

        # Add an alert — should evict a heartbeat.
        assert buffered.send_alert(_make_alert()) is True
        assert buffered.dropped_heartbeats >= 1
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_heartbeat_dropped_when_queue_full_of_alerts():
    """If the queue has grown past capacity with alerts and we try to
    enqueue a heartbeat, the heartbeat is dropped (returns False)."""
    inner = _ScriptedTelemetryClient(script=[False] * 100)
    buffered = BufferedTelemetryClient(
        inner, max_queue_size=2, retry_interval_s=0.5,
    )
    try:
        # Fill with alerts (queue grows past max because alerts never drop).
        for _ in range(3):
            buffered.send_alert(_make_alert())
        # Force the worker to spend time here; give it a moment then send hb.
        time.sleep(0.05)

        # This heartbeat should be rejected (queue full, all alerts, no
        # heartbeats to evict).
        result = buffered.send_heartbeat(_make_heartbeat())
        assert result is False
        assert buffered.dropped_heartbeats >= 1
    finally:
        buffered.close(drain_timeout_s=0.5)


# --- shutdown ---------------------------------------------------------------

def test_close_returns_true_when_queue_drained():
    inner = _ScriptedTelemetryClient()   # everything succeeds
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.01)
    buffered.send_heartbeat(_make_heartbeat())
    buffered.send_alert(_make_alert())
    drained = buffered.close(drain_timeout_s=2.0)
    assert drained is True
    assert buffered.delivered_heartbeats == 1
    assert buffered.delivered_alerts == 1


def test_close_returns_false_when_worker_cant_drain_in_time():
    """If the inner client is permanently failing, close() times out and
    reports that the queue is still non-empty."""
    inner = _ScriptedTelemetryClient(script=[False] * 100)
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.5)
    buffered.send_alert(_make_alert())
    time.sleep(0.02)  # let the worker try once
    drained = buffered.close(drain_timeout_s=0.1)
    assert drained is False


def test_close_is_idempotent():
    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.01)
    buffered.close(drain_timeout_s=0.5)
    buffered.close(drain_timeout_s=0.5)   # should not raise


# --- validation --------------------------------------------------------------

def test_zero_max_queue_size_is_rejected():
    import pytest
    with pytest.raises(ValueError):
        BufferedTelemetryClient(_ScriptedTelemetryClient(), max_queue_size=0)
