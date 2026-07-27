"""Manual hardware test: cycle through the three vibration motors.

Run on a Raspberry Pi 5 with all three motors wired through their NPN
transistor drivers to the pins configured in `indepensense.config`.

Wiring per motor (see `docs/hardware.md` for the full description):
    Motor +     → Pi 5V rail
    Motor −     → NPN transistor collector
    NPN emitter → GND
    NPN base    → 1kΩ resistor → Pi GPIO (the pin below)
    Flyback diode across the motor (cathode to +, anode to −)

Run from repo root:
    python -m indepensense.feedback.tests.manual.vibration_test

The script exercises each motor individually and then a coordinated
pattern that could plausibly be the "turn left" cue in the app. You
should be able to feel each motor distinctly and identify which side
of the wearable each corresponds to — that's the whole point of having
three: directional cueing you can feel.
"""
import time

from indepensense.config import (
    VIBRATION_FRONT_GPIO,
    VIBRATION_LEFT_GPIO,
    VIBRATION_RIGHT_GPIO,
)
from indepensense.feedback.gpio_vibration import GPIOVibrationMotor


def main():
    front = GPIOVibrationMotor(gpio_pin=VIBRATION_FRONT_GPIO)
    right = GPIOVibrationMotor(gpio_pin=VIBRATION_RIGHT_GPIO)
    left = GPIOVibrationMotor(gpio_pin=VIBRATION_LEFT_GPIO)

    try:
        print("Testing three vibration motors. Feel each one.")

        for name, motor in (
            ("FRONT", front),
            ("RIGHT", right),
            ("LEFT",  left),
        ):
            print(f"  {name} — steady 1 s")
            motor.on()
            time.sleep(1.0)
            motor.off()
            time.sleep(0.5)

        for name, motor in (
            ("FRONT", front),
            ("RIGHT", right),
            ("LEFT",  left),
        ):
            print(f"  {name} — three short pulses")
            motor.pulse(times=3, duration_s=0.15, gap_s=0.1)
            time.sleep(0.5)

        # Composite cue that the app might use for "turn left ahead":
        # front pulse (warning) then left pulses (direction).
        print("  Composite: turn-left cue (front, then two left pulses)")
        front.pulse(times=1, duration_s=0.3)
        time.sleep(0.2)
        left.pulse(times=2, duration_s=0.2, gap_s=0.1)

        print("Done.")
    finally:
        front.close()
        right.close()
        left.close()


if __name__ == "__main__":
    main()
