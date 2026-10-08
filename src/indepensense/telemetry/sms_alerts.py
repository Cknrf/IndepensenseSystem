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
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from indepensense.config import (
    SMS_ATTEMPT_DELAYS_S,
    SMS_REPORT_DEADLINE_S,
    SMS_RETRY_BACKOFF_S,
    SMS_RETRY_WINDOW_S,
)
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
SMS_NO_MODEM = "no_modem"     # numbers existed, ModemManager sees no modem

# Distinct from SMS_FAILED because the two need different things said.
# A failure that might clear is followed by a retry window the user is
# told about; a modem ModemManager cannot see at all will not be
# retried, so promising one would be a lie. The device spent a while
# making exactly that promise — see `emergency.delivery.sms_failed`.


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
        # The three knobs, injected rather than read from config, so a
        # test can collapse five minutes of waiting into nothing. The
        # defaults are the shipped values.
        report_deadline_s: float | None = None,
        attempt_delays_s: tuple[float, ...] | None = None,
        retry_window_s: float | None = None,
        retry_backoff_s: tuple[float, ...] | None = None,
        # Injected for the same reason. A unit test that sleeps through a
        # real backoff is a unit test that costs seconds to assert what a
        # counter already knows — the same objection `CLAUDE.md` makes to
        # tests that touch the network, with a different clock.
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._inner = inner
        self._sms = sms
        self._guardians = guardians
        self._event_type_values = event_type_values
        self._on_delivery = on_delivery
        # Resolved here rather than as argument defaults, which bind at
        # import time and cannot then be patched for a test that must not
        # spend five real minutes proving a retry window exists.
        self._report_deadline_s = (
            SMS_REPORT_DEADLINE_S if report_deadline_s is None else report_deadline_s
        )
        self._attempt_delays_s = (
            SMS_ATTEMPT_DELAYS_S if attempt_delays_s is None else attempt_delays_s
        )
        self._retry_window_s = (
            SMS_RETRY_WINDOW_S if retry_window_s is None else retry_window_s
        )
        self._retry_backoff_s = (
            SMS_RETRY_BACKOFF_S if retry_backoff_s is None else retry_backoff_s
        )
        self._sleep = sleep

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
        pending: dict[str, str] = {}
        if self._sms is None:
            state = SMS_UNAVAILABLE
        elif numbers:
            state, pending = self._text_everyone(event, numbers)
        else:
            state = SMS_NO_NUMBER

        if self._on_delivery is not None:
            delivery = AlertDelivery(
                backend_ok=backend.wait(_BACKEND_WAIT_S), sms=state,
            )
            try:
                self._on_delivery(event, delivery)
            except Exception as exc:
                self._report_failed(exc)

        # Only now, with the wearer told. Same thread: the fan-out thread
        # has nothing else to do, and spawning a second one to wait out a
        # five-minute window would add a thread whose whole job is
        # sleeping. See `_keep_trying` for why this is bounded.
        if pending:
            self._keep_trying(pending, compose_alert_sms(event))

    @staticmethod
    def _report_failed(exc: Exception) -> None:
        """The delivery callback raised.

        It speaks, so it touches TTS and the announcer. A failure there
        must not kill this thread: the counters and this line are then
        the only record of what happened, and the background retry still
        has work to do.
        """
        print(f"[sms] delivery report failed: {exc}", file=sys.stderr)

    def _attempt_round(self, pending: dict[str, str], text: str) -> tuple[bool, list[str]]:
        """One send attempt per still-pending recipient.

        Mutates nothing. Returns `(anything_sent, numbers_worth_retrying)` —
        a number drops out of the second list when it succeeded or when
        the driver said retrying cannot help.
        """
        sent_any = False
        retryable: list[str] = []
        for number in list(pending):
            try:
                result = self._sms.send(number, text)
            except Exception as exc:
                # The protocol says senders don't raise, but a driver bug
                # must not take the remaining recipients down with it.
                pending[number] = f"raised: {exc}"
                retryable.append(number)
                continue
            if result.sent:
                sent_any = True
                self.sms_sent_count += 1
                pending.pop(number)
                print(f"[sms] sent to {number}", flush=True)
                continue
            pending[number] = result.detail
            if result.retryable:
                retryable.append(number)
        return sent_any, retryable

    def _text_everyone(self, event: AlertEvent, numbers: list[str]) -> tuple[str, dict]:
        """Text every guardian, bounded by `SMS_REPORT_DEADLINE_S`.

        Returns `(state, still_pending)` — the verdict to speak, and the
        recipients worth another try once the wearer has been told.

        **The deadline is on telling the user, not on trying.** This used
        to run to completion before anything was spoken: three 30-second
        modem timeouts meant 90 seconds of silence after an emergency
        press, while the backend leg had already succeeded a second in.
        The information existed immediately and was withheld to give a
        dead modem two more chances. Now the verdict goes out on time and
        `_keep_trying` carries on behind it.

        A recipient the driver marked non-retryable is dropped rather than
        re-attempted — see `SMSResult.retryable`. With the modem
        physically gone, three attempts cost ninety seconds to learn what
        the first one already knew.
        """
        text = compose_alert_sms(event)
        pending = {number: "" for number in numbers}
        deadline = time.monotonic() + self._report_deadline_s
        any_sent = False
        saw_retryable = True

        for index, delay in enumerate((0.0, *self._attempt_delays_s)):
            if index:
                self._sleep(delay)
            if time.monotonic() >= deadline:
                break
            sent_any, retryable = self._attempt_round(pending, text)
            any_sent = any_sent or sent_any
            saw_retryable = bool(retryable)
            if not pending or not retryable:
                break                      # done, or nothing that could work

        for number, detail in pending.items():
            self.sms_failed_count += 1
            print(f"[sms] could not reach {number}: {detail}", file=sys.stderr)

        if any_sent:
            return SMS_SENT, {}
        if not saw_retryable:
            return SMS_NO_MODEM, {}
        return SMS_FAILED, pending

    def _keep_trying(self, pending: dict[str, str], text: str) -> None:
        """Carry on after the verdict, silently. Never raises.

        The wearer has already been told the text did not get through and
        that the device will keep trying — a promise `emergency.delivery.*`
        was making while nothing in the code honoured it. This is what
        makes it true.

        Silent on success by design. The wearer is mid-emergency and was
        told to seek help another way; a second announcement four minutes
        later is noise, and the guardian — who is the one that matters —
        has the text either way. The journal records it.

        Bounded by `SMS_RETRY_WINDOW_S`, not endless. A text arriving
        forty minutes late describes a situation that has already
        resolved, and two overlapping alerts can land out of order. The
        channel that retries indefinitely is the backend queue.
        """
        deadline = time.monotonic() + self._retry_window_s
        for delay in self._retry_backoff_s:
            if not pending or time.monotonic() >= deadline:
                break
            self._sleep(delay)
            if time.monotonic() >= deadline:
                break
            try:
                sent_any, retryable = self._attempt_round(pending, text)
            except Exception as exc:
                print(f"[sms] background retry failed: {exc}", file=sys.stderr)
                return
            if sent_any:
                print("[sms] a later attempt got through.", flush=True)
            if not retryable:
                break
        if pending:
            print(
                f"[sms] giving up on {', '.join(pending)} after "
                f"{self._retry_window_s:.0f}s.",
                file=sys.stderr,
            )
