"""Mock SMS sender for off-device development and unit tests."""
from indepensense.messaging.base import SMSResult


class MockSMSSender:
    """Records every message instead of sending it.

    `sent` is a public list of `(number, text)` tuples in send order, so a
    test can assert both who was texted and what they were told.

    `fail_numbers` makes specific recipients fail, which is how partial
    delivery is exercised — the case that matters, since one guardian's
    number being wrong must not stop the others being notified.
    """

    def __init__(self, fail_numbers: set[str] | None = None):
        self.sent: list[tuple[str, str]] = []
        self.attempts: list[str] = []
        self._fail_numbers = fail_numbers or set()
        self.closed = False

    def send(self, number: str, text: str) -> SMSResult:
        self.attempts.append(number)
        if number in self._fail_numbers:
            return SMSResult(number, False, "simulated failure")
        self.sent.append((number, text))
        return SMSResult(number, True)

    def close(self) -> None:
        self.closed = True
