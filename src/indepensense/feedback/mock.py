"""Mocks for off-device development.

- `MockButton` stores callbacks; a test harness fires them via `.press()`
  and `.release()`.
- `MockBuzzer` records every on/off/beep call to a public `events` list
  so tests can assert on what happened without producing sound.
- `MockVibrationMotor` mirrors `MockBuzzer` but for a vibration motor —
  same event-list contract, different semantic verb (`pulse` vs `beep`).
"""
from typing import Callable

from indepensense.feedback.base import ButtonEvent


class MockButton:
    def __init__(self) -> None:
        self._handlers: dict[ButtonEvent, Callable[[], None]] = {}

    def on(self, event: ButtonEvent, handler: Callable[[], None]) -> None:
        self._handlers[event] = handler

    def press(self) -> None:
        """Simulate a physical press. For test-harness use only."""
        handler = self._handlers.get("pressed")
        if handler is not None:
            handler()

    def release(self) -> None:
        """Simulate a physical release. For test-harness use only."""
        handler = self._handlers.get("released")
        if handler is not None:
            handler()

    def close(self) -> None:
        self._handlers.clear()


class MockBuzzer:
    """Buzzer that records every call to a list instead of making sound.

    `events` is a public list of tuples describing what happened, in order:
      - ("on",)
      - ("off",)
      - ("beep", times, duration_s, gap_s)
      - ("close",)

    Tests can assert on this list to verify feedback behaviour without
    running any hardware.
    """

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self._is_on = False

    def on(self) -> None:
        self.events.append(("on",))
        self._is_on = True

    def off(self) -> None:
        self.events.append(("off",))
        self._is_on = False

    def beep(
        self,
        times: int = 1,
        duration_s: float = 0.1,
        gap_s: float = 0.1,
    ) -> None:
        self.events.append(("beep", times, duration_s, gap_s))

    def close(self) -> None:
        self.events.append(("close",))
        self._is_on = False

    @property
    def is_on(self) -> bool:
        """Latest on/off state after the most recent call."""
        return self._is_on


class MockVibrationMotor:
    """Vibration motor that records every call to a list instead of vibrating.

    `events` is a public list of tuples describing what happened, in order:
      - ("on",)
      - ("off",)
      - ("pulse", times, duration_s, gap_s)
      - ("close",)

    Same shape as `MockBuzzer` — a test that inspects one can inspect the
    other with almost identical assertions.
    """

    def __init__(self) -> None:
        self.events: list[tuple] = []
        self._is_on = False

    def on(self) -> None:
        self.events.append(("on",))
        self._is_on = True

    def off(self) -> None:
        self.events.append(("off",))
        self._is_on = False

    def pulse(
        self,
        times: int = 1,
        duration_s: float = 0.2,
        gap_s: float = 0.15,
    ) -> None:
        self.events.append(("pulse", times, duration_s, gap_s))

    def close(self) -> None:
        self.events.append(("close",))
        self._is_on = False

    @property
    def is_on(self) -> bool:
        return self._is_on
