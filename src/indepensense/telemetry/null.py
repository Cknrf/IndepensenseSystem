"""Telemetry sink for a device with no usable backend credential.

Not a test double — this is the production path for an unprovisioned unit,
or one whose credential file is missing or malformed. `mock.py` is for
tests; this ships.

Why it exists: alerts must still reach guardians over SMS when the backend
is unreachable, and SMS is exactly the channel that works when data does
not. `SMSAlertNotifier` decorates a `TelemetryClient`, so it needs
something underneath even when there is nothing to talk to. Passing `None`
would mean branching at every alert site — the opposite of why the
decorator exists.

Accepting and discarding rather than queuing is deliberate. A missing
credential is not transient: queuing would fill the buffer with
heartbeats that can never be delivered and, worse, evict real alerts to
make room for them.

One caveat for anyone reading the numbers: `BufferedTelemetryClient`
counts these as `delivered_heartbeats`, because from its side the send
succeeded. In this mode that counter means "handed off", not "reached the
backend". The startup log says loudly which mode the unit is in.
"""
import sys

from indepensense.telemetry.base import AlertEvent, IntervalInformation


class NullTelemetryClient:
    """Accepts everything, sends nothing, counts what it swallowed.

    The counters are the point: they let `device.status` and the thesis
    evaluation distinguish "no telemetry was generated" from "telemetry
    was generated and thrown away because this unit is unprovisioned".
    """

    def __init__(self) -> None:
        self.discarded_heartbeats = 0
        self.discarded_alerts = 0
        self._warned = False

    def send_heartbeat(self, info: IntervalInformation) -> bool:
        self.discarded_heartbeats += 1
        self._warn_once()
        return True

    def send_alert(self, event: AlertEvent) -> bool:
        self.discarded_alerts += 1
        # Always logged, not once: an alert going nowhere is worth a line
        # every time, unlike a heartbeat every 30 seconds.
        print(
            f"[telemetry] discarded {event.event_type.value} — no device "
            f"credential, so the guardian dashboard cannot be reached. "
            f"SMS is unaffected.",
            file=sys.stderr,
        )
        return True

    def _warn_once(self) -> None:
        if self._warned:
            return
        self._warned = True
        print(
            "[telemetry] no device credential — heartbeats are being "
            "discarded. Provision this unit to restore the dashboard.",
            file=sys.stderr,
        )
