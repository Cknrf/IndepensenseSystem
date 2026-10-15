"""GPIO active-buzzer driver.

Wraps `gpiozero.Buzzer`. An active buzzer contains its own oscillator, so
driving the pin HIGH produces a tone at the buzzer's factory-tuned
frequency (usually ~2-4 kHz). No PWM required.

Wiring (default GPIO 20, physical pin 38):
    Pi GPIO     → 1 kΩ resistor → NPN base
    buzzer +    → supply rail
    buzzer -    → NPN transistor collector
    NPN emitter → GND

The buzzer is driven through a transistor, the same as the vibration
motors. This docstring described direct GPIO drive until 2026-10-15,
which was wrong about the assembled unit: a hobby active buzzer pulls
15-25 mA against the Pi's ~16 mA per-pin limit, so the transistor was
always the right call and the build had one. See `docs/hardware.md` for
the circuit and the two weaknesses it shares with the motor channels.
The Buzzer protocol is unaffected either way; only the wiring differs.
"""
import time


class GPIOBuzzer:
    def __init__(self, gpio_pin: int):
        from gpiozero import Buzzer as _GZBuzzer  # lazy: only on the Pi

        self._buzzer = _GZBuzzer(gpio_pin)

    def on(self) -> None:
        self._buzzer.on()

    def off(self) -> None:
        self._buzzer.off()

    def beep(
        self,
        times: int = 1,
        duration_s: float = 0.1,
        gap_s: float = 0.1,
    ) -> None:
        # Implemented with explicit on/off + sleep rather than gpiozero's
        # own .beep() so the mock and the real driver behave identically —
        # both take exactly `times * (duration_s + gap_s)` seconds. The
        # small extra Python overhead per iteration (<1 ms) is invisible
        # compared to the beep durations.
        for i in range(times):
            self._buzzer.on()
            time.sleep(duration_s)
            self._buzzer.off()
            if i < times - 1:
                time.sleep(gap_s)

    def close(self) -> None:
        self._buzzer.close()
