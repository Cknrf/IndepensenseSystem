"""Telemetry decorator that also texts the guardians when an alert fires.

Why a decorator
---------------

Alerts are raised from three places — fall detection and low battery in
`app.py`, and the emergency intent in `intents/executor.py` (which serves
both the voice command and the emergency button). All three already go
through a `TelemetryClient`, so wrapping that interface adds SMS to every
one of them without touching a single call site, and makes it impossible
to add a fourth alert path that silently forgets to text anyone.

It also composes with what is already there. The runtime builds

    SMSAlertNotifier(BufferedTelemetryClient(NestJSTelemetryClient(...)))

which reads in the order the data flows: buffer and retry the HTTP post,
and independently push an SMS out the cellular control channel.

Heartbeats pass straight through untouched — texting a guardian every 30
seconds would be both useless and expensive.

Threading
---------

A modem round trip takes seconds, and `send_alert` is called from the
100 Hz main loop (fall detection). Blocking there would stall obstacle
and fall detection for the duration, so each alert's SMS fan-out runs on
its own short-lived daemon thread. This mirrors the existing per-event
warning-pattern threads in `app.py` rather than introducing a new
long-lived one: alerts are rare, the thread exists for a few seconds and
exits.

The consequence, stated plainly: `send_alert` returns before the SMS has
been sent, and its boolean reflects only the HTTP result. SMS outcomes
are logged and counted, never folded into that return value — an
unreachable backend and an unreachable cell network are different
failures and the caller's retry logic only governs the former.
"""
import sys
import threading
from datetime import datetime

from indepensense.messaging.base import SMSSender
from indepensense.telemetry.base import AlertEvent, IntervalInformation, TelemetryClient
from indepensense.telemetry.guardians import GuardianDirectory

# A (0.0, 0.0) fix means "no GPS lock", not a position off the coast of
# Africa. Sending a guardian a map link to the Gulf of Guinea during an
# emergency is worse than admitting we don't know where the user is.
_NO_FIX_EPSILON = 1e-6


def compose_alert_sms(event: AlertEvent, now: datetime | None = None) -> str:
    """Build the message body.

    Kept short deliberately: a message over 160 characters is split into
    multiple parts, which costs more and can arrive out of order. The map
    link is the single most actionable thing a guardian can receive, so it
    goes in ahead of anything else optional.
    """
    stamp = (now or event.occurred_at).strftime("%d %b %H:%M")
    if abs(event.latitude) < _NO_FIX_EPSILON and abs(event.longitude) < _NO_FIX_EPSILON:
        location = "Location unavailable (no GPS fix)"
    else:
        location = (
            f"https://maps.google.com/?q={event.latitude:.6f},{event.longitude:.6f}"
        )
    return f"IndepenSense {event.event_type.value}: {location} ({stamp})"


class SMSAlertNotifier:
    """`TelemetryClient` that mirrors alerts to guardian phones."""

    def __init__(
        self,
        inner: TelemetryClient,
        sms: SMSSender,
        guardians: GuardianDirectory,
        event_type_values: tuple[str, ...],
    ):
        self._inner = inner
        self._sms = sms
        self._guardians = guardians
        self._event_type_values = event_type_values

        # Observable counters, same spirit as the heartbeat sender's —
        # useful for a thesis-facing table of delivery success.
        self.sms_sent_count = 0
        self.sms_failed_count = 0

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        return self._inner.send_heartbeat(info)

    def send_alert(self, event: AlertEvent) -> bool:
        """Post the alert, and dispatch SMS off-thread if it qualifies."""
        if event.event_type.value in self._event_type_values:
            self._dispatch_sms(event)
        return self._inner.send_alert(event)

    # -------------------------------------------------------------- internals

    def _dispatch_sms(self, event: AlertEvent) -> None:
        numbers = self._guardians.sms_numbers()
        if not numbers:
            print(
                "[sms] no guardian numbers known — nothing to notify. "
                "Check the guardian fetch succeeded at startup.",
                file=sys.stderr,
            )
            return
        threading.Thread(
            target=self._send_all,
            args=(event, numbers),
            name="sms-fanout",
            daemon=True,
        ).start()

    def _send_all(self, event: AlertEvent, numbers: list[str]) -> None:
        text = compose_alert_sms(event)
        for number in numbers:
            # One guardian's number being wrong must not stop the rest
            # being told, so failures are logged and the loop continues.
            try:
                result = self._sms.send(number, text)
            except Exception as exc:
                # The protocol says senders don't raise, but a driver bug
                # must not take the remaining recipients down with it.
                self.sms_failed_count += 1
                print(f"[sms] sender raised for {number}: {exc}", file=sys.stderr)
                continue

            if result.sent:
                self.sms_sent_count += 1
                print(f"[sms] sent to {number}", flush=True)
            else:
                self.sms_failed_count += 1
                print(f"[sms] failed for {number}: {result.detail}", file=sys.stderr)
