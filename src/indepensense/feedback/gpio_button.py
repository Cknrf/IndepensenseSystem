"""GPIO push-button driver.

Wraps gpiozero.Button to emit named events. Configured for the KY-004
style breakout module used on the wearable, which has an on-board 10 kΩ
pull-down and drives the OUT pin HIGH when pressed. That is the opposite
of a bare tactile switch (which relies on an internal pull-up and reads
LOW when pressed).

We pass `pull_up=False` to gpiozero. On the Pi 5 this both enables the
internal pull-down resistor (redundant with the KY-004's external one,
but harmless — two pull-downs in parallel just pull a bit harder) AND
implicitly sets `active_state=True`, so the button reads "pressed" on
GPIO HIGH. gpiozero rejects passing `active_state=True` explicitly here
because in combination with `pull_up=False` it would be over-specified
("pin is not floating, but active_state is not None").

gpiozero handles debouncing internally with the `bounce_time` parameter.
50 ms is plenty for a mechanical tact switch — a well-made switch settles
in ~10 ms, cheap ones ~30 ms.

The driver spawns background threads under the hood (gpiozero uses one
per active pin). Application code must eventually call `close()` to
release the GPIO lines cleanly on shutdown.
"""
from typing import Callable

from indepensense.feedback.base import ButtonEvent


class GPIOButton:
    def __init__(self, gpio_pin: int, bounce_time_s: float = 0.05):
        from gpiozero import Button as _GZButton  # lazy: only importable on Pi

        # pull_up=False enables the internal pull-down and implies
        # active-high input (HIGH = pressed). Matches KY-004 wiring.
        self._button = _GZButton(
            gpio_pin,
            pull_up=False,
            bounce_time=bounce_time_s,
        )

    def on(self, event: ButtonEvent, handler: Callable[[], None]) -> None:
        if event == "pressed":
            self._button.when_pressed = handler
        elif event == "released":
            self._button.when_released = handler
        else:
            raise ValueError(
                f"Unknown ButtonEvent {event!r}. Use 'pressed' or 'released'."
            )

    def close(self) -> None:
        self._button.close()
