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
been sent, and its boolean is the inner client's own — for the buffered
client in production, "queued", not even the HTTP result. SMS outcomes
are logged and counted, never folded into that return value — an
unreachable backend and an unreachable cell network are different
failures and the caller's retry logic only governs the former.

Telling the wearer what actually happened
-----------------------------------------

That split used to end at the log file, and the wearable said "Emergency
alert sent to your guardian" on the strength of the HTTP leg alone. On a
unit whose modem was refusing every message, that sentence was false in
the one situation where being told the truth matters most — the person
believed help was coming and it was not.

`on_delivery` closes that gap. It fires once per alert, from the fan-out
thread, with both results in one `AlertDelivery`. The caller decides what
to say; this class only reports facts.

It is a callback rather than a return value because the two channels
finish at different times and the slow one is the modem. Waiting for it
before saying anything would leave someone who just pressed the emergency
button in silence for the length of a modem round trip. So the caller
acknowledges immediately ("Sending your emergency alert") and corrects
itself here only if a channel failed.
"""
import sys
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from indepensense.messaging.base import SMSSender
from indepensense.telemetry.base import AlertEvent, IntervalInformation, TelemetryClient
from indepensense.telemetry.buffered import BufferedTelemetryClient
from indepensense.telemetry.guardians import GuardianDirectory

# A (0.0, 0.0) fix means "no GPS lock", not a position off the coast of
# Africa. Sending a guardian a map link to the Gulf of Guinea during an
# emergency is worse than admitting we don't know where the user is.
_NO_FIX_EPSILON = 1e-6

# How long the fan-out thread waits for the HTTP leg before reporting
# without it. Only reached if the backend post outlives the entire modem
# round trip, which means the network is badly degraded — and at that
# point the honest thing is to report what we know rather than keep the
# wearer waiting for a result that may never come.
_BACKEND_WAIT_S = 20.0

# `AlertDelivery.sms` states.
SMS_SENT = "sent"             # at least one guardian's phone accepted it
SMS_FAILED = "failed"         # numbers existed, none of them went through
SMS_NO_NUMBER = "no_number"   # nobody to text — the directory is empty
SMS_UNAVAILABLE = "unavailable"  # this unit has no working SMS sender


@dataclass(frozen=True)
class AlertDelivery:
    """Which channels actually carried one alert.

    `sms` is a three-state string rather than a bool because "no guardian
    number is saved" is a different thing to tell the user than "the modem
    refused the message". The first is fixed by a guardian filling in the
    web form; the second is a fault on the device. Collapsing them would
    send the user chasing the wrong one.

    `sms == SMS_SENT` means *at least one* guardian was reached, not all
    of them. With several guardians a partial success is still a person
    who knows, and the wearer does not need a roll call — the per-number
    detail is in the log and in `sms_failed_count`.
    """
    backend_ok: bool
    sms: str


class _BackendOutcome:
    """One-shot cell publishing the HTTP result to the fan-out thread.

    The SMS fan-out deliberately starts *before* the HTTP post, so the
    modem is not left waiting behind a network call that may be timing
    out — in an emergency the text is the channel more likely to work.
    That ordering is why the two results need rejoining here instead of
    being read off one return value.
    """

    def __init__(self) -> None:
        self._done = threading.Event()
        self._ok = False

    def publish(self, ok: bool) -> None:
        self._ok = ok
        self._done.set()

    def wait(self, timeout_s: float) -> bool:
        """The backend result, or False if it never arrived in time.

        False on timeout is the safe direction: it reports the alert as
        not having reached the dashboard, which at worst tells the user to
        seek another channel for something that eventually got through.
        The opposite error — reporting success we never observed — is the
        bug this whole mechanism exists to remove.
        """
        self._done.wait(timeout_s)
        return self._ok


def compose_alert_sms(event: AlertEvent, now: datetime | None = None) -> str:
    """Build the message body.

    Kept short deliberately: a message over 160 characters is split into
    multiple parts, which costs more and can arrive out of order. The map
    link is the single most actionable thing a guardian can receive, so it
    goes in ahead of anything else optional.
    """
    # `.astimezone()` with no argument converts to the system's local
    # zone. `occurred_at` is tz-aware UTC (see the executor), and
    # formatting it directly printed UTC wall-clock — so an alert raised
    # at 13:05 in Manila reached the guardian stamped 05:05, eight hours
    # out. A guardian deciding whether an alert is happening now or is
    # hours stale is the one judgement this timestamp exists to support.
    #
    # A naive datetime passed as `now` is left alone: `astimezone` would
    # assume it is local and return it unchanged anyway, which is the
    # right reading for one constructed by a caller or a test.
    stamp = (now or event.occurred_at).astimezone().strftime("%d %b %H:%M")
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
        # None when the unit cannot text at all (SMS disabled, or no modem
        # at startup). The notifier is still built, so the backend result
        # is still reported to the wearer instead of being assumed.
        sms: SMSSender | None,
        guardians: GuardianDirectory,
        event_type_values: tuple[str, ...],
        # Called once per qualifying alert, from the fan-out thread, with
        # both channel results. None keeps the old behaviour: outcomes are
        # logged and nothing is spoken.
        on_delivery: Callable[[AlertEvent, AlertDelivery], None] | None = None,
    ):
        self._inner = inner
        self._sms = sms
        self._guardians = guardians
        self._event_type_values = event_type_values
        self._on_delivery = on_delivery

        # Observable counters, same spirit as the heartbeat sender's —
        # useful for a thesis-facing table of delivery success.
        self.sms_sent_count = 0
        self.sms_failed_count = 0

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        return self._inner.send_heartbeat(info)

    def send_alert(self, event: AlertEvent) -> bool:
        """Post the alert, and dispatch SMS off-thread if it qualifies.

        Returns the inner client's result unchanged — for the buffered
        client that only means "queued" — because fall detection calls this
        from the 100 Hz main loop and cannot wait for the network or a
        modem. What actually got through reaches the caller through
        `on_delivery`.
        """
        if event.event_type.value not in self._event_type_values:
            return self._inner.send_alert(event)

        backend = _BackendOutcome()
        self._dispatch_sms(event, backend)

        # The buffered client's True means "queued", not "delivered" — it
        # returns before any network call. Publishing that made backend_ok
        # permanently True in production, so an offline unit whose SMS
        # also failed told the wearer the dashboard had been reached. Its
        # first real attempt is the honest answer, so wait for that one.
        if isinstance(self._inner, BufferedTelemetryClient):
            return self._inner.send_alert(event, on_first_attempt=backend.publish)

        ok = self._inner.send_alert(event)
        backend.publish(ok)
        return ok

    # -------------------------------------------------------------- internals

    def _dispatch_sms(self, event: AlertEvent, backend: _BackendOutcome) -> None:
        """Start the fan-out thread, even with nobody to text.

        An empty directory still spawns the thread, because "no guardian
        number is saved" is a result the wearer needs to hear and
        returning early here would silently skip the report.
        """
        numbers = self._guardians.sms_numbers() if self._sms is not None else []
        if self._sms is not None and not numbers:
            print(
                "[sms] no guardian numbers known — nothing to notify. "
                "Check the guardian fetch succeeded at startup.",
                file=sys.stderr,
            )
        threading.Thread(
            target=self._send_all,
            args=(event, numbers, backend),
            name="sms-fanout",
            daemon=True,
        ).start()

    def _send_all(
        self,
        event: AlertEvent,
        numbers: list[str],
        backend: _BackendOutcome,
    ) -> None:
        if self._sms is None:
            state = SMS_UNAVAILABLE
        elif numbers:
            state = self._text_everyone(event, numbers)
        else:
            state = SMS_NO_NUMBER
        if self._on_delivery is None:
            return

        delivery = AlertDelivery(
            backend_ok=backend.wait(_BACKEND_WAIT_S), sms=state,
        )
        try:
            self._on_delivery(event, delivery)
        except Exception as exc:
            # The callback speaks, so it touches TTS and the announcer. A
            # failure there must not kill this thread before the counters
            # above are the only record left of what happened.
            print(f"[sms] delivery report failed: {exc}", file=sys.stderr)

    def _text_everyone(self, event: AlertEvent, numbers: list[str]) -> str:
        """Text every guardian with up to 3 attempts per number. `SMS_SENT` if any accepted.

        Each number is retried up to 3 times with delays (100ms, 500ms, 1s)
        on failure, giving the modem time to recover from transient glitches.
        One guardian's failure does not prevent others being notified.
        """
        import time
        text = compose_alert_sms(event)
        any_sent = False
        for number in numbers:
            # Retry delays in seconds: 100ms, 500ms, 1s
            delays = [0.1, 0.5, 1.0]
            result = None

            for attempt in range(1 + len(delays)):
                try:
                    result = self._sms.send(number, text)
                except Exception as exc:
                    # The protocol says senders don't raise, but a driver bug
                    # must not take the remaining recipients down with it.
                    if attempt < len(delays):
                        delay = delays[attempt]
                        print(
                            f"[sms] send to {number} attempt {attempt + 1} raised, "
                            f"retrying in {delay}s: {exc}",
                            file=sys.stderr,
                        )
                        time.sleep(delay)
                        continue
                    self.sms_failed_count += 1
                    print(
                        f"[sms] failed to send to {number} after {attempt + 1} attempts: {exc}",
                        file=sys.stderr,
                    )
                    break

                if result.sent:
                    any_sent = True
                    self.sms_sent_count += 1
                    print(f"[sms] sent to {number} on attempt {attempt + 1}", flush=True)
                    break
                elif attempt < len(delays):
                    delay = delays[attempt]
                    print(
                        f"[sms] send to {number} attempt {attempt + 1} failed, "
                        f"retrying in {delay}s: {result.detail}",
                        file=sys.stderr,
                    )
                    time.sleep(delay)
                else:
                    self.sms_failed_count += 1
                    print(
                        f"[sms] failed to send to {number} after {attempt + 1} attempts: "
                        f"{result.detail}",
                        file=sys.stderr,
                    )

        return SMS_SENT if any_sent else SMS_FAILED
