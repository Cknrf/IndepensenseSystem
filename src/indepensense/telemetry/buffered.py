"""Buffered, retrying telemetry client for real-world network conditions.

Wraps any `TelemetryClient` (typically `NestJSTelemetryClient`) with:

- **A background worker thread** that drains a queue of pending sends.
- **Alert prioritisation.** Alerts jump the queue ahead of heartbeats. A
  single alert never waits behind a backlog of stale heartbeats.
- **Retry on failure.** If the inner client returns False for any send,
  the item is re-queued for retry after `retry_interval_s` seconds.
  Runs forever — the cellular link could be down for hours and the
  first alert to succeed after reconnection is guaranteed to be the
  oldest alert, not the newest heartbeat.
- **Bounded queue.** If the queue fills (long network outage), the
  OLDEST heartbeats are dropped first. Alerts are never dropped.

Semantics of the returned booleans:

- `send_alert(event)` — always returns True. Alerts are always accepted
  because they are safety-critical.
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
import sys
import threading
from collections import deque
from typing import Union

from indepensense.telemetry.base import (
    AlertEvent,
    DeviceCredentialRejected,
    IntervalInformation,
    TelemetryClient,
)


# Internal queue item: either ("alert", AlertEvent) or ("heartbeat", IntervalInformation)
_QueueItem = tuple[str, Union[AlertEvent, IntervalInformation]]


class BufferedTelemetryClient:
    def __init__(
        self,
        inner: TelemetryClient,
        max_queue_size: int = 500,
        retry_interval_s: float = 10.0,
        auth_retry_interval_s: float = 900.0,
    ):
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be >= 1")
        self._inner = inner
        self._max_queue_size = max_queue_size
        self._retry_interval_s = retry_interval_s
        self._auth_retry_interval_s = auth_retry_interval_s

        self._queue: deque[_QueueItem] = deque()
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._shutdown = False

        # Counters exposed for tests + telemetry-about-telemetry (thesis chart material)
        self.dropped_heartbeats = 0
        self.delivered_heartbeats = 0
        self.delivered_alerts = 0

        # True once the backend has rejected our credential. A persistent
        # provisioning fault, not a connectivity one — `device.status` and
        # the startup log distinguish them so nobody spends an afternoon
        # debugging the cellular link over a revoked key.
        self.credential_rejected = False

        self._worker = threading.Thread(target=self._run, name="telemetry-worker", daemon=True)
        self._worker.start()

    # ------- public API (matches TelemetryClient protocol) -----------------

    def send_alert(self, event: AlertEvent) -> bool:
        """Queue an alert. Always accepted (never dropped, however full).

        If the queue is at capacity, evicts the oldest HEARTBEAT to make
        room. If the queue is full of alerts (very rare — implies the
        network has been down for a long time and many alerts have
        stacked up), the queue is allowed to grow past `max_queue_size`
        so we never lose a safety event.
        """
        with self._lock:
            if len(self._queue) >= self._max_queue_size:
                self._evict_oldest_heartbeat_locked()   # best-effort, may be a no-op
            # Alerts jump to the front.
            self._queue.appendleft(("alert", event))
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
            self._queue.append(("heartbeat", info))
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

            kind, payload = item
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

            # Failure: put the item back and wait before retrying.
            # Alerts go back to the head; heartbeats go back too (they were
            # popped from the head, they belong at the head).
            with self._lock:
                if kind == "alert":
                    self._queue.appendleft(item)
                else:
                    self._queue.appendleft(item)

            # If we're shutting down, don't wait for the full retry interval —
            # exit as soon as the caller's drain timeout hits.
            if self._shutdown:
                return
            self._wakeup.wait(timeout=retry_after)
            self._wakeup.clear()

    # ------- helpers -------------------------------------------------------

    def _pop_next(self) -> _QueueItem | None:
        """Pop the next item to send. Returns None if the queue is empty."""
        with self._lock:
            if not self._queue:
                return None
            return self._queue.popleft()

    def _evict_oldest_heartbeat_locked(self) -> bool:
        """Remove the oldest heartbeat from the queue. Assumes lock is held.
        Returns True if a heartbeat was evicted, False if none exist."""
        for i, (kind, _payload) in enumerate(self._queue):
            if kind == "heartbeat":
                del self._queue[i]
                self.dropped_heartbeats += 1
                return True
        return False
