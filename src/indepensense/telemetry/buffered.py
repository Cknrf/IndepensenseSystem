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

Shutdown semantics: `close()` signals the worker to stop after draining
what it can within the timeout. Anything still queued when the timeout
expires is lost (data on RAM only; not persisted to disk). For a wearable
this is acceptable — real losses come from SD wear, not from planned
shutdowns.
"""
import dataclasses
import sys
import threading
from collections import deque
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
            return self._queue.popleft()

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
