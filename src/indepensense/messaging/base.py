"""Types and protocol for outbound SMS.

SMS is the wearable's fallback notification path. HTTP alerts to the
backend need a working data connection; SMS rides the cellular control
channel and gets through in marginal-signal conditions where a POST
times out. See `config.SMS_ENABLED` for why we always send rather than
sending only when the data path looks bad.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class SMSResult:
    """Outcome of one send attempt to one recipient.

    `detail` carries the failure reason for logging — a modem error
    string, a timeout note. Empty on success.
    """
    number: str
    sent: bool
    detail: str = ""


class SMSSender(Protocol):
    def send(self, number: str, text: str) -> SMSResult:
        """Send one message. Must not raise — report failure in the result.

        Implementations are expected to be slow (a modem round trip is
        seconds, not milliseconds), so callers must not invoke this from
        the main loop.
        """

    def close(self) -> None:
        ...
