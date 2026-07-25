"""Manual hardware test: cycle through common beep patterns.

Run on a Raspberry Pi 5 with an active buzzer wired to `BUZZER_GPIO`.

Wiring:
    buzzer + → Pi physical pin 12 (GPIO 18)   — configurable via --pin
    buzzer - → any Pi GND (physical pin 6, 9, 14, 20, 25, 30, 34, or 39)

Run from repo root:
    # default (BUZZER_GPIO from config)
    python -m indepensense.feedback.tests.manual.buzzer_test

    # specify a different GPIO number
    python -m indepensense.feedback.tests.manual.buzzer_test 21

The script plays four patterns with a short pause between each, then
exits. Listen for:
    1. Single short beep — button-acknowledgement style
    2. Three fast beeps — obstacle-warning style
    3. Long steady tone (1 second) — attention-getting
    4. Rapid stutter — emergency-alarm style
"""
import sys
import time

from indepensense.config import BUZZER_GPIO
from indepensense.feedback.gpio_buzzer import GPIOBuzzer


def main():
    pin = int(sys.argv[1]) if len(sys.argv) > 1 else BUZZER_GPIO

    buzzer = GPIOBuzzer(gpio_pin=pin)
    try:
        print(f"Buzzer on GPIO {pin}. Running through beep patterns.")

        print("  1. Single short beep")
        buzzer.beep()
        time.sleep(1.0)

        print("  2. Three fast beeps (obstacle warning)")
        buzzer.beep(times=3, duration_s=0.1, gap_s=0.1)
        time.sleep(1.0)

        print("  3. One second steady tone")
        buzzer.on()
        time.sleep(1.0)
        buzzer.off()
        time.sleep(1.0)

        print("  4. Rapid stutter (emergency)")
        buzzer.beep(times=8, duration_s=0.05, gap_s=0.05)

        print("Done.")
    finally:
        buzzer.close()


if __name__ == "__main__":
    main()
