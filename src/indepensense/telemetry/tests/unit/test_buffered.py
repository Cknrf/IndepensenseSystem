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


# --- first-attempt reporting -------------------------------------------------
#
# `send_alert` returns True on queueing, before any network call. A caller
# that has to tell a person whether the alert got through needs the result
# of the first real attempt instead — see SMSAlertNotifier.

def test_the_first_attempt_is_reported_once_even_across_retries():
    inner = _ScriptedTelemetryClient(script=[False, False, True])
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    outcomes = []
    try:
        assert buffered.send_alert(_make_alert(), on_first_attempt=outcomes.append)
        assert _wait_until(lambda: buffered.delivered_alerts == 1, timeout_s=3.0)
        assert outcomes == [False], "reported more than once, or the wrong result"
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_a_successful_first_attempt_is_reported_as_success():
    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    outcomes = []
    try:
        buffered.send_alert(_make_alert(), on_first_attempt=outcomes.append)
        assert _wait_until(lambda: outcomes == [True])
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_a_raising_attempt_callback_does_not_stop_the_worker():
    def _explode(_ok):
        raise RuntimeError("caller bug")

    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_alert(_make_alert(), on_first_attempt=_explode)
        buffered.send_heartbeat(_make_heartbeat())
        assert _wait_until(lambda: buffered.delivered_heartbeats == 1)
        assert buffered.delivered_alerts == 1
    finally:
        buffered.close(drain_timeout_s=1.0)


# --- head-of-line blocking ---------------------------------------------------
#
# A failed item used to go straight back to the front of the queue, so one
# the backend always refuses was retried forever and an alert queued while
# it was in flight was never attempted.

class _RefusingHeartbeats(_ScriptedTelemetryClient):
    """Heartbeats always fail, slowly enough for an alert to arrive mid-send."""

    def send_heartbeat(self, info):
        super().send_heartbeat(info)
        time.sleep(0.05)
        return False


def test_a_heartbeat_that_always_fails_does_not_block_an_alert():
    inner = _RefusingHeartbeats()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_heartbeat(_make_heartbeat())
        assert _wait_until(lambda: len(inner.heartbeats) == 1)  # now in flight
        buffered.send_alert(_make_alert())
        assert _wait_until(lambda: buffered.delivered_alerts == 1), (
            f"alert never delivered; calls: {inner.call_order}"
        )
    finally:
        buffered.close(drain_timeout_s=0.5)


class _RefusingOneAlert(_ScriptedTelemetryClient):
    """Refuses every send of one particular alert, slowly."""

    def __init__(self, refused):
        super().__init__()
        self.refused = refused

    def send_alert(self, event):
        super().send_alert(event)
        if event is self.refused:
            time.sleep(0.05)
            return False
        return True


def test_an_alert_that_always_fails_does_not_block_a_newer_one():
    stuck, newer = _make_alert(), _make_alert(EventType.EMERGENCY_ALERT)
    inner = _RefusingOneAlert(refused=stuck)
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_alert(stuck)
        assert _wait_until(lambda: len(inner.alerts) == 1)        # in flight
        buffered.send_alert(newer)
        assert _wait_until(lambda: newer in inner.alerts), "newer alert never attempted"
        assert _wait_until(lambda: buffered.delivered_alerts == 1)
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_a_failed_heartbeat_keeps_its_place_among_heartbeats():
    inner = _ScriptedTelemetryClient(script=[False])
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        first, second = _make_heartbeat(battery=1), _make_heartbeat(battery=2)
        buffered.send_heartbeat(first)
        buffered.send_heartbeat(second)
        assert _wait_until(lambda: buffered.delivered_heartbeats == 2, timeout_s=3.0)
        delivered = [h.battery_health for h in inner.heartbeats]
        assert delivered == [1, 1, 2], delivered    # failed, retried, then the next
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_a_client_that_cannot_reach_the_backend_reports_failure_without_retrying():
    """NullTelemetryClient returns True so undeliverable sends are not
    retried forever — but that True is "handled", not "delivered", and must
    not be reported to the wearer as the dashboard having been reached."""
    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(
        inner, retry_interval_s=0.02, reaches_backend=False,
    )
    outcomes = []
    try:
        buffered.send_alert(_make_alert(), on_first_attempt=outcomes.append)
        assert _wait_until(lambda: outcomes == [False])
        assert buffered.queue_depth() == 0
        assert len(inner.alerts) == 1, "an undeliverable alert was retried"
    finally:
        buffered.close(drain_timeout_s=0.5)


class _RefusingAlerts(_ScriptedTelemetryClient):
    """The backend refuses every alert but accepts heartbeats."""

    def send_alert(self, event):
        super().send_alert(event)
        return False


def test_an_alert_that_is_always_refused_does_not_starve_heartbeats():
    inner = _RefusingAlerts()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    try:
        buffered.send_alert(_make_alert())
        assert _wait_until(lambda: len(inner.alerts) >= 1)
        buffered.send_heartbeat(_make_heartbeat(battery=1))
        buffered.send_heartbeat(_make_heartbeat(battery=2))
        assert _wait_until(lambda: buffered.delivered_heartbeats == 2, timeout_s=3.0), (
            f"heartbeats starved; calls: {inner.call_order}"
        )
        assert [h.battery_health for h in inner.heartbeats] == [1, 2]
    finally:
        buffered.close(drain_timeout_s=0.5)


# --- one pending emergency-button alert -------------------------------------
#
# The button re-arms when nobody was reached so the wearer can press again.
# Each press used to become its own queued alert, and guardians got one
# per press once the link came back.

def _emergency(minute: int, lat: float) -> AlertEvent:
    return AlertEvent(
        device_id="dev-test", event_type=EventType.EMERGENCY_ALERT,
        latitude=lat, longitude=121.0,
        occurred_at=_TIMESTAMP.replace(minute=minute),
    )


def _offline_then_online(inner_script):
    inner = _ScriptedTelemetryClient(script=inner_script)
    return inner, BufferedTelemetryClient(inner, retry_interval_s=0.3)


def test_repeated_emergency_presses_deliver_one_alert():
    # First attempt of the first press fails; everything after succeeds.
    inner, buffered = _offline_then_online([False])
    try:
        buffered.send_alert(_emergency(minute=1, lat=14.1))
        assert _wait_until(lambda: len(inner.alerts) == 1)      # failed once
        buffered.send_alert(_emergency(minute=2, lat=14.2))     # re-press
        assert _wait_until(lambda: buffered.delivered_alerts == 1, timeout_s=3.0)
        time.sleep(0.4)
        assert buffered.delivered_alerts == 1
        assert buffered.merged_emergency_alerts == 1
        delivered = inner.alerts[-1]
        # When it started, and where the wearer is now.
        assert delivered.occurred_at.minute == 1
        assert delivered.latitude == 14.2
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_falls_are_never_merged():
    inner, buffered = _offline_then_online([False])
    try:
        buffered.send_alert(_make_alert(EventType.FALL_DETECTION))
        assert _wait_until(lambda: len(inner.alerts) == 1)
        buffered.send_alert(_make_alert(EventType.FALL_DETECTION))
        assert _wait_until(lambda: buffered.delivered_alerts == 2, timeout_s=3.0)
        assert buffered.merged_emergency_alerts == 0
    finally:
        buffered.close(drain_timeout_s=0.5)


def test_a_merged_alert_still_reports_to_both_callers():
    """Two presses queued before the worker reaches either: the first
    caller must still hear an outcome, or its notifier waits out its 20 s
    timeout and reports a failure that never happened."""
    gate = threading.Event()

    class _Gated(_ScriptedTelemetryClient):
        def send_heartbeat(self, info):
            gate.wait(timeout=2.0)                # hold the worker busy
            return super().send_heartbeat(info)

    inner = _Gated()
    buffered = BufferedTelemetryClient(inner, retry_interval_s=0.02)
    first, second = [], []
    try:
        buffered.send_heartbeat(_make_heartbeat())
        time.sleep(0.05)                          # worker now blocked on it
        buffered.send_alert(_emergency(minute=1, lat=14.1), on_first_attempt=first.append)
        buffered.send_alert(_emergency(minute=2, lat=14.2), on_first_attempt=second.append)
        gate.set()
        assert _wait_until(lambda: first == [True] and second == [True])
        assert buffered.delivered_alerts == 1
    finally:
        buffered.close(drain_timeout_s=0.5)


# --- surviving a restart -----------------------------------------------------
#
# The queue used to be RAM only, so an offline unit whose battery died, or
# whose app crashed and was restarted by systemd, silently lost every alert
# it was still holding. These pin the replacement: an accepted alert is on
# disk until the backend has it, and a new client picks it up.

class _GatedTelemetryClient(_ScriptedTelemetryClient):
    """Holds every alert send open until `release` is set — a request
    stuck on a dead link, observable from the test."""

    def __init__(self):
        super().__init__()
        self.sending = threading.Event()
        self.release = threading.Event()

    def send_alert(self, event: AlertEvent) -> bool:
        self.sending.set()
        self.release.wait(timeout=5.0)
        return super().send_alert(event)


def _stored(path) -> list[dict]:
    import json

    return json.loads(path.read_text()) if path.exists() else []


def test_an_accepted_alert_is_on_disk_before_send_alert_returns(tmp_path):
    """The guarantee the store exists for. Checked while the worker is
    still stuck sending, so the file cannot have been written by
    anything but `send_alert` itself."""
    store = tmp_path / "pending_alerts.json"
    inner = _GatedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, alert_store_path=store)
    try:
        buffered.send_alert(_make_alert())
        assert [a["event_type"] for a in _stored(store)] == ["Fall Detection"]
    finally:
        inner.release.set()
        buffered.close(drain_timeout_s=1.0)


def test_an_alert_stays_stored_while_it_is_being_sent(tmp_path):
    """The worker takes the alert out of the queue to send it. A crash
    during that request must not be the one moment it is nowhere."""
    store = tmp_path / "pending_alerts.json"
    inner = _GatedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, alert_store_path=store)
    try:
        buffered.send_alert(_make_alert())
        assert inner.sending.wait(timeout=2.0)
        buffered.send_alert(_make_alert(EventType.LOW_BATTERY))   # rewrites the store
        assert sorted(a["event_type"] for a in _stored(store)) == [
            "Fall Detection", "Low Battery",
        ]
    finally:
        inner.release.set()
        buffered.close(drain_timeout_s=1.0)


def test_a_delivered_alert_leaves_nothing_on_disk(tmp_path):
    store = tmp_path / "pending_alerts.json"
    buffered = BufferedTelemetryClient(
        _ScriptedTelemetryClient(), retry_interval_s=0.01, alert_store_path=store,
    )
    try:
        buffered.send_alert(_make_alert())
        assert _wait_until(lambda: buffered.delivered_alerts == 1)
        assert _wait_until(lambda: not store.exists())
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_an_alert_queued_offline_is_sent_after_a_restart(tmp_path):
    """The scenario end to end: pressed with no network, the device
    restarts, and the alert reaches the backend once it is online —
    stamped with when it was pressed, not when it finally arrived."""
    store = tmp_path / "pending_alerts.json"
    offline = _ScriptedTelemetryClient(script=[False] * 1000)
    before = BufferedTelemetryClient(
        offline, retry_interval_s=0.01, alert_store_path=store,
    )
    before.send_alert(_emergency(minute=7, lat=14.5))
    assert _wait_until(lambda: len(offline.alerts) >= 1)
    before.close(drain_timeout_s=0.2)

    online = _ScriptedTelemetryClient()
    after = BufferedTelemetryClient(
        online, retry_interval_s=0.01, alert_store_path=store,
    )
    try:
        assert _wait_until(lambda: after.delivered_alerts == 1)
        delivered = online.alerts[0]
        assert delivered.event_type is EventType.EMERGENCY_ALERT
        assert delivered.occurred_at == _emergency(minute=7, lat=14.5).occurred_at
        assert delivered.latitude == 14.5
        assert _wait_until(lambda: not store.exists())
    finally:
        after.close(drain_timeout_s=1.0)


def test_heartbeats_are_never_written_to_disk(tmp_path):
    """Superseded every interval; persisting them would wear the SD card
    for data nobody needs after a restart."""
    store = tmp_path / "pending_alerts.json"
    buffered = BufferedTelemetryClient(
        _ScriptedTelemetryClient(script=[False] * 1000),
        retry_interval_s=0.01, alert_store_path=store,
    )
    try:
        buffered.send_heartbeat(_make_heartbeat())
        time.sleep(0.05)
        assert not store.exists()
    finally:
        buffered.close(drain_timeout_s=0.2)


def test_repeated_presses_are_stored_as_one_alert(tmp_path):
    """The merge has to reach the file too, or a restart would bring
    back every press as its own alert."""
    store = tmp_path / "pending_alerts.json"
    inner = _GatedTelemetryClient()
    buffered = BufferedTelemetryClient(inner, alert_store_path=store)
    try:
        buffered.send_alert(_make_alert())                   # occupies the worker
        assert inner.sending.wait(timeout=2.0)
        buffered.send_alert(_emergency(minute=1, lat=14.1))
        buffered.send_alert(_emergency(minute=2, lat=14.2))
        emergencies = [a for a in _stored(store) if a["event_type"] == "Emergency Alert"]
        assert len(emergencies) == 1
        assert emergencies[0]["latitude"] == 14.2
    finally:
        inner.release.set()
        buffered.close(drain_timeout_s=1.0)


def test_an_unreadable_store_is_moved_aside_not_lost(tmp_path):
    """It may hold a real emergency, so it is kept for a human to
    recover — and it must not stop the device starting."""
    store = tmp_path / "pending_alerts.json"
    store.write_text("{not json")
    buffered = BufferedTelemetryClient(_ScriptedTelemetryClient(), alert_store_path=store)
    try:
        assert buffered.queue_depth() == 0
        aside = tmp_path / "pending_alerts.json.corrupt"
        assert aside.read_text() == "{not json"
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_one_malformed_stored_alert_does_not_cost_the_others(tmp_path):
    import json

    store = tmp_path / "pending_alerts.json"
    good = {"device_id": "dev-test", "event_type": "Fall Detection",
            "latitude": 1.0, "longitude": 2.0,
            "occurred_at": _TIMESTAMP.isoformat()}
    store.write_text(json.dumps([{"event_type": "Nonsense"}, good]))
    online = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(
        online, retry_interval_s=0.01, alert_store_path=store,
    )
    try:
        assert _wait_until(lambda: buffered.delivered_alerts == 1)
        assert online.alerts[0].latitude == 1.0
    finally:
        buffered.close(drain_timeout_s=1.0)


def test_a_store_that_cannot_be_written_does_not_stop_the_alert(tmp_path):
    """A full or read-only SD card is a durability problem, not a reason
    to refuse an emergency."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("")
    inner = _ScriptedTelemetryClient()
    buffered = BufferedTelemetryClient(
        inner, retry_interval_s=0.01,
        alert_store_path=blocker / "pending_alerts.json",
    )
    try:
        assert buffered.send_alert(_make_alert()) is True
        assert _wait_until(lambda: buffered.delivered_alerts == 1)
    finally:
        buffered.close(drain_timeout_s=1.0)
