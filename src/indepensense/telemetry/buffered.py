"""Buffered, retrying telemetry client for real-world network conditions.

Wraps any `TelemetryClient` (typically `NestJSTelemetryClient`) with:

- **A background worker thread** that drains a queue of pending sends.
- **Alert prioritisation.** Alerts jump the queue ahead of heartbeats. A
  single alert never waits behind a backlog of stale heartbeats.
- **Retry on failure.** If the inner client returns False for any send,
  the item is re-queued for retry after `retry_interval_s` seconds.
  Runs forever — the cellular link could be down for hours, and an alert
  is always retried before any heartbeat.
- **No head-of-line blocking.** A failed item goes back *behind every
  queued alert*, not to the very front. Putting it at the front meant an
  item the backend always refuses — a heartbeat answered 400, say — was
  retried forever while an alert queued behind it was never attempted at
  all. Several failing alerts now take turns instead. A failed alert also
  lets *one* heartbeat go before its retry, so an alert the backend keeps
  refusing cannot starve the heartbeats either; during an outage that
  costs one extra request per retry, and when the link returns at most
  one heartbeat lands ahead of the alert.
- **Bounded queue.** If the queue fills (long network outage), the
  OLDEST heartbeats are dropped first. Alerts are never dropped.
- **One pending emergency-button alert.** A press while an earlier
  emergency alert is still undelivered replaces it rather than queueing
  a second. The button is re-armed when nobody was reached precisely so
  the wearer can press again, and each press used to become its own
  alert — guardians got one per press once the link came back. The
  merged alert keeps the first press's time and the newest position.
  Falls are never merged: two falls are two events.

Semantics of the returned booleans:

- `send_alert(event)` — always returns True. Alerts are always accepted
  because they are safety-critical. That True means "queued", never
  "delivered" — a caller that has to tell a person whether the alert
  reached anyone passes `on_first_attempt` and hears the real outcome
  of the first try (see `SMSAlertNotifier`).
- `send_heartbeat(info)` — returns True when queued, False when the
  queue is at capacity AND contains no heartbeats to evict (i.e. the
  queue is saturated with alerts and this heartbeat is discarded).
- `close(drain_timeout_s)` — returns True if the queue drained fully
  before the timeout, False otherwise (worker abandons remaining items).

The bool return values differ subtly from the raw `NestJSTelemetryClient`
which returns "did the server accept this exact request." Here it means
"did we accept this for eventual delivery." Callers that need to know
about actual delivery need to inspect their own backend, not the return.

Retry schedule: uniform `retry_interval_s` (default 10 s). Simple and
easy to reason about. A production build would use exponential backoff;
that's a defensible thesis "future work" bullet.

**One exception.** A `DeviceCredentialRejected` (backend 401) cannot be
fixed by retrying — the credential is wrong or revoked and a human has to
re-provision the unit. Retrying that every 10 s would hammer the backend
forever with a request that can never succeed, so it switches to
`auth_retry_interval_s` (default 15 min) and sets `credential_rejected`
so the fault is distinguishable from "no network". Items stay queued
throughout: if the unit is un-revoked, the backlog delivers.

**Alerts survive a restart; heartbeats do not.** With `alert_store_path`
set, every undelivered alert is also kept in a JSON file, and a new
client re-queues whatever it finds there. The queue used to live in RAM
only, so the moments most likely to have an alert waiting — an offline
unit whose battery dies, or an app crash that systemd restarts — were the
moments it was lost. Heartbeats stay in memory: they are superseded every
interval, and writing one to the SD card every few seconds would wear it
for data nobody needs after a restart.

The file holds the complete set of undelivered alerts and is rewritten
whole each time it changes: when an alert is queued, merged or
delivered. It is written to a temp file, fsynced and renamed, so a power
cut leaves either the old set or the new one, never half of either.
Alerts are rare — one per fall, press or battery threshold — so the cost
is a few small writes per event, not a stream.

The write happens inside `send_alert`, on the caller's thread, so an
alert is on disk before `send_alert` returns. For a fall that thread is
the 100 Hz main loop, and the write blocks it for a few milliseconds. That
is accepted on purpose: the alternative, writing from the worker, leaves
the alert in RAM only while the worker is stuck in a 5 s network timeout,
which is exactly when the link is bad. One loop cycle is lost straight
after a fall has already been detected; nothing is lost from the alert.

Delivery is at least once, not exactly once. If the process dies after
the backend has stored an alert but before the file is rewritten, the
alert is sent again on restart and the guardian sees it twice. A second
copy of an emergency is a much smaller failure than none.

Shutdown semantics: `close()` signals the worker to stop after draining
what it can within the timeout. Alerts still queued when it expires stay
in the file and are sent by the next client; heartbeats are dropped.
"""
import dataclasses
import json
import os
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Callable, Union

from indepensense.telemetry.base import (
    AlertEvent,
    DeviceCredentialRejected,
    EventType,
    IntervalInformation,
    TelemetryClient,
)


# Called once with whether the first delivery attempt of an alert succeeded.
_AttemptCallback = Callable[[bool], None]

# Internal queue item: ("alert", AlertEvent, callback-or-None) or
# ("heartbeat", IntervalInformation, None). The callback is dropped after
# it fires, so a retried alert does not report twice.
_QueueItem = tuple[str, Union[AlertEvent, IntervalInformation], _AttemptCallback | None]


class BufferedTelemetryClient:
    def __init__(
        self,
        inner: TelemetryClient,
        max_queue_size: int = 500,
        retry_interval_s: float = 10.0,
        auth_retry_interval_s: float = 900.0,
        # False when `inner` cannot reach the backend at all — the
        # unprovisioned unit's NullTelemetryClient, which returns True so
        # that undeliverable sends are not retried forever. Its True means
        # "handled", not "delivered", so `on_first_attempt` must not
        # report it as success.
        reaches_backend: bool = True,
        # Where undelivered alerts are kept across restarts. None keeps
        # them in memory only, which is what the unit tests want.
        alert_store_path: Path | None = None,
    ):
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be >= 1")
        self._inner = inner
        self._max_queue_size = max_queue_size
        self._retry_interval_s = retry_interval_s
        self._auth_retry_interval_s = auth_retry_interval_s
        self._reaches_backend = reaches_backend

        self._queue: deque[_QueueItem] = deque()
        self._lock = threading.Lock()
        self._alert_store_path = alert_store_path
        # The alert the worker is sending right now. It is out of the
        # queue while the request runs, and the store must still list it:
        # a crash mid-send would otherwise drop it from the file.
        self._in_flight: AlertEvent | None = None
        self._wakeup = threading.Event()
        self._shutdown = False

        # Counters exposed for tests + telemetry-about-telemetry (thesis chart material)
        self.dropped_heartbeats = 0
        self.delivered_heartbeats = 0
        self.delivered_alerts = 0
        # Emergency-button alerts folded into an earlier undelivered one.
        self.merged_emergency_alerts = 0

        # True once the backend has rejected our credential. A persistent
        # provisioning fault, not a connectivity one — `device.status` and
        # the startup log distinguish them so nobody spends an afternoon
        # debugging the cellular link over a revoked key.
        self.credential_rejected = False

        # Before the worker starts, so nothing races the reload.
        restored = _load_alerts(alert_store_path) if alert_store_path else []
        for event in restored:
            self._queue.append(("alert", event, None))
        if restored:
            print(
                f"[telemetry] {len(restored)} undelivered alert(s) from before "
                f"the restart — sending again.",
                flush=True,
            )

        self._worker = threading.Thread(target=self._run, name="telemetry-worker", daemon=True)
        self._worker.start()

    # ------- public API (matches TelemetryClient protocol) -----------------

    def send_alert(
        self,
        event: AlertEvent,
        on_first_attempt: _AttemptCallback | None = None,
    ) -> bool:
        """Queue an alert. Always accepted (never dropped, however full).

        `on_first_attempt`, if given, is called from the worker thread with
        the result of the first try to deliver this alert. Only the first:
        retries continue in the background, but the caller is deciding what
        to tell someone *now*, and "it did not get through yet" is the
        honest answer to that question.

        If the queue is at capacity, evicts the oldest HEARTBEAT to make
        room. If the queue is full of alerts (very rare — implies the
        network has been down for a long time and many alerts have
        stacked up), the queue is allowed to grow past `max_queue_size`
        so we never lose a safety event.
        """
        with self._lock:
            if event.event_type is EventType.EMERGENCY_ALERT:
                event, on_first_attempt = self._merge_pending_emergency_locked(
                    event, on_first_attempt,
                )
            if len(self._queue) >= self._max_queue_size:
                self._evict_oldest_heartbeat_locked()   # best-effort, may be a no-op
            # Alerts jump to the front.
            self._queue.appendleft(("alert", event, on_first_attempt))
            self._persist_alerts_locked()
        self._wakeup.set()
        return True

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        """Queue a heartbeat. May be dropped if the queue is saturated
        with alerts (no heartbeats to evict AND at capacity)."""
        with self._lock:
            if len(self._queue) >= self._max_queue_size:
                evicted = self._evict_oldest_heartbeat_locked()
                if not evicted:
                    # Queue is 100% alerts and at capacity — drop this heartbeat.
                    self.dropped_heartbeats += 1
                    return False
            self._queue.append(("heartbeat", info, None))
        self._wakeup.set()
        return True

    def close(self, drain_timeout_s: float = 5.0) -> bool:
        """Signal the worker to stop and drain what it can within
        `drain_timeout_s` seconds. Returns True if the queue drained
        fully, False otherwise. Idempotent — calling twice is fine."""
        self._shutdown = True
        self._wakeup.set()
        self._worker.join(timeout=drain_timeout_s)
        with self._lock:
            drained = len(self._queue) == 0
        return drained

    # ------- test-friendly introspection -----------------------------------

    def queue_depth(self) -> int:
        with self._lock:
            return len(self._queue)

    # ------- worker thread -------------------------------------------------

    def _run(self) -> None:
        while True:
            item = self._pop_next()

            if item is None:
                if self._shutdown:
                    return
                # Nothing to do — sleep until woken by a new item or shutdown.
                self._wakeup.wait(timeout=self._retry_interval_s)
                self._wakeup.clear()
                continue

            kind, payload, on_attempt = item
            retry_after = self._retry_interval_s
            try:
                if kind == "alert":
                    success = self._inner.send_alert(payload)
                else:
                    success = self._inner.send_heartbeat(payload)
            except DeviceCredentialRejected as exc:
                # Permanent until a human intervenes. Keep the item queued
                # so a re-provisioned unit delivers its backlog, but stop
                # asking every 10 seconds.
                if not self.credential_rejected:
                    print(
                        f"[telemetry-worker] {exc}. Backing off to "
                        f"{self._auth_retry_interval_s:.0f}s — this needs "
                        f"re-provisioning, not a retry.",
                        file=sys.stderr,
                    )
                self.credential_rejected = True
                success = False
                retry_after = self._auth_retry_interval_s
            except Exception as exc:
                # A raising inner client is a bug, but we still want the
                # queue to keep making progress instead of crashing the worker.
                print(f"[telemetry-worker] inner client raised: {exc}", file=sys.stderr)
                success = False

            if on_attempt is not None:
                self._report_attempt(on_attempt, success and self._reaches_backend)
                item = (kind, payload, None)

            if success:
                # A success after a rejection means the unit was
                # un-revoked or re-provisioned. Clear the latch so the
                # normal retry interval resumes.
                if self.credential_rejected:
                    print("[telemetry-worker] credential accepted again.", flush=True)
                    self.credential_rejected = False
                if kind == "alert":
                    self.delivered_alerts += 1
                    with self._lock:
                        self._in_flight = None
                        self._persist_alerts_locked()
                else:
                    self.delivered_heartbeats += 1
                continue

            # Failure: put the item back behind every queued alert, then
            # wait before retrying. For a heartbeat that is still the front
            # of the heartbeats, so they keep their order. A failed alert
            # goes one further, behind the first heartbeat, so a refused
            # alert cannot hold the heartbeats back forever.
            with self._lock:
                index = self._first_heartbeat_index_locked()
                if kind == "alert" and index < len(self._queue):
                    index += 1
                self._queue.insert(index, item)
                # Back in the queue, so the store's contents are unchanged
                # and there is nothing to rewrite.
                self._in_flight = None

            # If we're shutting down, don't wait for the full retry interval —
            # exit as soon as the caller's drain timeout hits.
            if self._shutdown:
                return
            self._wakeup.wait(timeout=retry_after)
            self._wakeup.clear()

    # ------- helpers -------------------------------------------------------

    @staticmethod
    def _report_attempt(callback: _AttemptCallback, success: bool) -> None:
        """Run a caller's callback without letting it kill the worker."""
        try:
            callback(success)
        except Exception as exc:
            print(f"[telemetry-worker] attempt callback raised: {exc}",
                  file=sys.stderr)

    def _pop_next(self) -> _QueueItem | None:
        """Pop the next item to send. Returns None if the queue is empty."""
        with self._lock:
            if not self._queue:
                return None
            item = self._queue.popleft()
            if item[0] == "alert":
                self._in_flight = item[1]
            return item

    def _merge_pending_emergency_locked(
        self, event: AlertEvent, on_first_attempt: _AttemptCallback | None,
    ) -> tuple[AlertEvent, _AttemptCallback | None]:
        """Fold a queued, undelivered emergency alert into `event`.

        Returns the alert to queue in its place: the first press's time,
        so the guardian sees when the emergency began, with this press's
        position, which is the fresher one. A pending callback from the
        earlier alert — never attempted yet — still fires, so its caller
        is not left waiting for a report that would otherwise never come.
        Assumes the lock is held.
        """
        for i, (kind, payload, callback) in enumerate(self._queue):
            if kind == "alert" and payload.event_type is EventType.EMERGENCY_ALERT:
                del self._queue[i]
                self.merged_emergency_alerts += 1
                merged = dataclasses.replace(event, occurred_at=payload.occurred_at)
                if callback is None:
                    return merged, on_first_attempt
                if on_first_attempt is None:
                    return merged, callback

                def both(ok: bool, first=callback, second=on_first_attempt) -> None:
                    self._report_attempt(first, ok)
                    second(ok)
                return merged, both
        return event, on_first_attempt

    def _persist_alerts_locked(self) -> None:
        """Rewrite the store with every undelivered alert. Lock held.

        Failure is logged, not raised: the alert is still queued in memory
        and will still be sent while this process lives. Refusing it over a
        full or read-only SD card would turn a durability problem into a
        lost emergency.
        """
        if self._alert_store_path is None:
            return
        pending = [] if self._in_flight is None else [self._in_flight]
        pending += [payload for kind, payload, _cb in self._queue if kind == "alert"]
        try:
            _write_alerts(self._alert_store_path, pending)
        except OSError as exc:
            print(
                f"[telemetry] could not save undelivered alerts to "
                f"{self._alert_store_path}: {exc}. They will still be sent, "
                f"but not if the device restarts first.",
                file=sys.stderr, flush=True,
            )

    def _first_heartbeat_index_locked(self) -> int:
        """Index just past the queued alerts. Assumes lock is held."""
        for i, (kind, _payload, _callback) in enumerate(self._queue):
            if kind == "heartbeat":
                return i
        return len(self._queue)

    def _evict_oldest_heartbeat_locked(self) -> bool:
        """Remove the oldest heartbeat from the queue. Assumes lock is held.
        Returns True if a heartbeat was evicted, False if none exist."""
        for i, (kind, _payload, _callback) in enumerate(self._queue):
            if kind == "heartbeat":
                del self._queue[i]
                self.dropped_heartbeats += 1
                return True
        return False


# ------- alert store ------------------------------------------------------

def _alert_to_json(event: AlertEvent) -> dict:
    return {
        "device_id": event.device_id,
        "event_type": event.event_type.value,
        "latitude": event.latitude,
        "longitude": event.longitude,
        "occurred_at": event.occurred_at.isoformat(),
    }


def _alert_from_json(raw: dict) -> AlertEvent:
    return AlertEvent(
        device_id=raw["device_id"],
        event_type=EventType(raw["event_type"]),
        latitude=float(raw["latitude"]),
        longitude=float(raw["longitude"]),
        occurred_at=datetime.fromisoformat(raw["occurred_at"]),
    )


def _write_alerts(path: Path, alerts: list[AlertEvent]) -> None:
    """Replace the store with `alerts`, or remove it when there are none.

    Removed rather than left as `[]`, so an empty store and no store mean
    the same thing and a unit with nothing pending has nothing on disk.

    Temp file, fsync, rename, then fsync the directory. The rename is what
    makes the swap atomic; the two fsyncs are what make it survive a power
    cut, since without them ext4 can keep both the new contents and the
    rename in cache for several seconds after `os.replace` returns.
    """
    if not alerts:
        path.unlink(missing_ok=True)
        return

    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(temp, "w") as f:
            json.dump([_alert_to_json(a) for a in alerts], f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    except OSError:
        temp.unlink(missing_ok=True)
        raise

    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _load_alerts(path: Path) -> list[AlertEvent]:
    """Every alert in the store, oldest first, or none.

    Never raises: a store that cannot be read must not stop the device
    starting — fall detection matters more than a backlog. An unreadable
    file is moved aside rather than overwritten, because what is in it
    may be a real emergency someone has to recover by hand.
    """
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, list):
            raise ValueError(f"expected a list, got {type(raw).__name__}")
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        aside = path.with_suffix(path.suffix + ".corrupt")
        print(
            f"[telemetry] could not read undelivered alerts from {path}: "
            f"{exc}. Moved to {aside} for inspection.",
            file=sys.stderr, flush=True,
        )
        try:
            os.replace(path, aside)
        except OSError:
            pass
        return []

    alerts = []
    for entry in raw:
        try:
            alerts.append(_alert_from_json(entry))
        except (TypeError, KeyError, ValueError) as exc:
            # One malformed entry must not cost the others.
            print(f"[telemetry] skipping malformed stored alert {entry!r}: {exc}",
                  file=sys.stderr, flush=True)
    return alerts
