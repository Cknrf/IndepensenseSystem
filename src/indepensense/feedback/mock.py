"""Mock button for off-device development.

Callbacks are stored but never fired automatically — a test harness can
call `.press()` and `.release()` explicitly to simulate button events.
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
