"""GPIO vibration-motor driver.

Wraps `gpiozero.DigitalOutputDevice` — driving the GPIO HIGH energises
the NPN transistor that gates the motor's power. The Pi's GPIO alone
cannot source enough current for a vibration motor (60-100 mA typical),
so an external transistor is mandatory. See `docs/hardware.md` for the
exact circuit.

Wiring per motor:
    Motor +     → 5V rail (Pi pin 2 or 4)
    Motor −     → NPN transistor collector (e.g. 2N2222, 2N3904)
    NPN emitter → GND rail
    NPN base    → 1 kΩ resistor → Pi GPIO (the pin passed to this driver)
    Flyback diode (1N4001) across the motor:
        cathode (striped end) → Motor +
        anode                 → Motor −

The flyback diode is critical — a spinning motor generates a voltage
spike (back-EMF) when de-energised, and without the diode that spike
can damage the transistor or, in the worst case, the Pi.
"""
import time


class GPIOVibrationMotor:
    def __init__(self, gpio_pin: int):
        from gpiozero import DigitalOutputDevice as _GZOut  # lazy: only on the Pi

        self._motor = _GZOut(gpio_pin)

    def on(self) -> None:
        self._motor.on()

    def off(self) -> None:
        self._motor.off()

    def pulse(
        self,
        times: int = 1,
        duration_s: float = 0.2,
        gap_s: float = 0.15,
    ) -> None:
        # Same explicit on/off/sleep pattern as GPIOBuzzer.beep so mock
        # and real driver have identical timing behaviour.
        for i in range(times):
            self._motor.on()
            time.sleep(duration_s)
            self._motor.off()
            if i < times - 1:
                time.sleep(gap_s)

    def close(self) -> None:
        self._motor.close()
