"""Feedback / user-input interfaces.

The `feedback` package covers the physical I/O the wearable presents to
the user: buttons for input, buzzer + vibration motor for output. The
vibration motor lands later once the transistor / diode circuit for it is
on hand.

All drivers follow the same pattern used elsewhere: a Protocol here, a
real driver, a mock for off-device development, and one manual test.
"""
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


class Buzzer(Protocol):
    """Simple on/off audio annunciator (active buzzer)."""

    def on(self) -> None:
        """Start sounding a continuous tone. Idempotent."""

    def off(self) -> None:
        """Stop sounding. Idempotent."""

    def beep(
        self,
        times: int = 1,
        duration_s: float = 0.1,
        gap_s: float = 0.1,
    ) -> None:
        """Emit `times` short beeps with `duration_s` on and `gap_s` between.

        Blocking. If the wearable needs a non-blocking beep pattern (e.g. a
        continuous emergency tone while the polling loop runs), the caller
        is responsible for invoking this from a background thread.
        """

    def close(self) -> None:
        ...
