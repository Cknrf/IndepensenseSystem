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

The script fires each motor on its own and then all three together,
which are the only two patterns the runtime uses.

**You are checking that each channel conducts, not that you can tell
them apart.** All three motors sit in the one cane handle and couple
through its shell, so the wearer feels the same buzz whichever fires —
what the device has is one vibrator with two intensity steps. This
docstring used to ask the tester to "identify which side of the
wearable each corresponds to", which was a property of the wiring
diagram and never a perception; navigation stopped encoding direction
this way and every turn instruction is now speech. Watch the printed
label to know which channel is live.
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
        print("Testing three vibration motors. Each should buzz in turn.")

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

        # The two patterns the runtime actually plays, from
        # `App._play_rhythm_pulse`: front alone is the obstacle warning,
        # all three together is danger inside OBSTACLE_DANGER_CM. The
        # second should feel noticeably stronger than the first — that
        # contrast is the whole signal, so if they feel the same, a
        # channel is not conducting.
        print("  Warning level — front alone")
        front.pulse(times=1, duration_s=0.4)
        time.sleep(0.6)

        print("  Danger level — all three together")
        for m in (front, right, left):
            m.on()
        time.sleep(0.4)
        for m in (front, right, left):
            m.off()

        print("Done.")
    finally:
        front.close()
        right.close()
        left.close()


if __name__ == "__main__":
    main()
