"""Feedback / user-input interfaces.

The `feedback` package covers the physical I/O the wearable presents to the
user: buttons for input, buzzer + vibration motor for output. Buzzer and
motor land later once the transistor circuit for the motor is on hand.

All drivers follow the same pattern used elsewhere: a Protocol here, a real
driver, a mock for off-device development, and one manual test.
"""
from dataclasses import dataclass
from typing import Callable, Protocol


ButtonEvent = str
"""Named events a button can emit.

Two events matter for the wearable:
- "pressed": the user just pushed the button down (button state changed
  from released to pressed).
- "released": the user let go (button state changed back to released).

The application layer decides what these events mean — a PTT button
toggles recording on `pressed` and ignores `released`; an emergency
button fires immediately on `pressed`.
"""


class Button(Protocol):
    def on(self, event: ButtonEvent, handler: Callable[[], None]) -> None:
        """Register a callback for the named event.

        The handler is called with no arguments from a background thread the
        driver manages internally. If the same event is registered twice
        the second registration wins.
        """

    def close(self) -> None:
        ...
