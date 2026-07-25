"""GPIO active-buzzer driver.

Wraps `gpiozero.Buzzer`. An active buzzer contains its own oscillator, so
driving the pin HIGH produces a tone at the buzzer's factory-tuned
frequency (usually ~2-4 kHz). No PWM required.

Wiring:
    buzzer + → Pi GPIO pin (default GPIO 18, physical pin 12)
    buzzer - → any Pi GND

Current draw considerations: most hobby active buzzers pull 15-25 mA at
3.3 V, which is at the edge of what a single Pi GPIO can safely source
(~16 mA per pin). Most buzzers work directly from GPIO in practice; if
the Pi shows undervoltage warnings (`vcgencmd get_throttled` non-zero)
after adding the buzzer, drive it through an NPN transistor instead. The
Buzzer protocol is unchanged either way — only the wiring differs.
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
