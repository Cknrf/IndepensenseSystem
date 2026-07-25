"""Manual hardware test: verify a KY-004 style button on a GPIO pin.

Run on a Raspberry Pi 5 with the button wired to the pin configured by
`--pin` (defaults to `PTT_BUTTON_GPIO` from config).

Wiring for the KY-004 module:
    module VCC → Pi 3.3V (physical pin 1 or 17)
    module GND → Pi GND (physical pin 6, 9, 14, 20, 25, 30, 34, or 39)
    module OUT → Pi GPIO configured below

The module has an on-board 10 kΩ pull-down, so OUT reads LOW when the
button is released and HIGH when pressed.

Run from repo root:
    # default (PTT_BUTTON_GPIO)
    python -m indepensense.feedback.tests.manual.button_test

    # specify a different GPIO number
    python -m indepensense.feedback.tests.manual.button_test 24

Ctrl-C to stop.
"""
import sys
import time

from indepensense.config import PTT_BUTTON_GPIO
from indepensense.feedback.gpio_button import GPIOButton


def main():
    pin = int(sys.argv[1]) if len(sys.argv) > 1 else PTT_BUTTON_GPIO

    button = GPIOButton(gpio_pin=pin)
    press_count = 0

    def _on_press():
        nonlocal press_count
        press_count += 1
        print(f"  press #{press_count}  ({time.strftime('%H:%M:%S')})")

    def _on_release():
        print(f"  release          ({time.strftime('%H:%M:%S')})")

    button.on("pressed", _on_press)
    button.on("released", _on_release)

    print(f"Listening on GPIO {pin}. Press the button. Ctrl-C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\nStopped. Total presses: {press_count}")
    finally:
        button.close()


if __name__ == "__main__":
    main()
