"""Feedback / user-input interfaces.

The `feedback` package covers the physical I/O the wearable presents to
the user: buttons for input, buzzer + vibration motors for output. Three
vibration motors (front / right / left) provide directional cues that
don't require audio — critical for use in noisy environments and for
users with hearing impairment.

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


class Vibration(Protocol):
    """Single vibration motor driven through a transistor.

    Same shape as Buzzer but with longer default pulse widths — vibration
    needs ~150-300 ms to be reliably felt on the skin, whereas audible
    beeps register in ~50 ms. The default `duration_s=0.2` reflects that.

    A single wearable typically has multiple `Vibration` instances (one
    per direction: front, right, left). Application code decides which
    to fire for which cue.
    """

    def on(self) -> None:
        """Start vibrating continuously. Idempotent."""

    def off(self) -> None:
        """Stop vibrating. Idempotent."""

    def pulse(
        self,
        times: int = 1,
        duration_s: float = 0.2,
        gap_s: float = 0.15,
    ) -> None:
        """Emit `times` short pulses with `duration_s` on and `gap_s` between.

        Blocking, same threading contract as `Buzzer.beep`.
        """

    def close(self) -> None:
        ...
