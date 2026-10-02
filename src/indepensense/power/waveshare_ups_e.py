"""Driver for the Waveshare UPS HAT (E).

Ports the reference `ups.py` Waveshare ships into the project structure.
Same I²C register map, same math — just structured as a class with a
lock so multiple threads (heartbeat sender, main-loop alert check) can
share one reader without racing on the I²C bus.

Chip: Waveshare-proprietary fuel gauge / power controller at address
`0x2D` on I²C bus 1. Not an INA219 despite what generic tutorials
sometimes say — the register map differs.

Register map (read only, all little-endian):

  0x02 (1 byte)   status:
                    0x40 = fast charging
                    0x80 = charging (regular)
                    0x20 = discharging
                    (otherwise) = idle

  0x10 (6 bytes)  VBUS (USB-C input) info:
                    voltage_mv, current_ma, power_mw

  0x20 (12 bytes) battery info:
                    voltage_mv, current_ma (signed),
                    percentage, remaining_mah,
                    time_to_empty_min, time_to_full_min

  0x30 (8 bytes)  per-cell voltages (mV): cell1..4

Register `0x01` accepts a `0x55` write — this tells the HAT to cut
power. We do NOT invoke that from the driver; graceful shutdown is
the application's job (the app writes final telemetry, then invokes
`request_power_off()` explicitly). Hardware-level protection kicks in
on its own if the app fails to react to `is_critical_low`.

The reported percentage is not a percentage
-------------------------------------------

The gauge does not read 0 at empty. Measured on this unit across three
discharges: the Pi lost power, and reading immediately after reconnecting
the charger showed 59%. The usable span is therefore ~41 raw points, not
100, and the raw figure overstates remaining charge by roughly 2.4× in
the region that matters.

That was not cosmetic. `LOW_BATTERY_PERCENT` (15) and
`CRITICAL_BATTERY_PERCENT` (5) both sit below a floor the gauge never
reaches, so neither alert had ever fired or could — the wearable gave no
warning and simply died.

`read()` therefore rescales onto 0-100 against `empty_raw_percent` and
reports the original alongside as `raw_percentage`. The correction lives
here rather than in each caller because this is the layer that already
turns raw registers into clean values — the same job as the
two's-complement conversion below it. The *constant* lives in
`config.py`, because it is a property of this battery pack rather than of
the chip.

Linear between the measured floor and 100. One endpoint is measured and
the other assumed; the middle is not verified. See
`tests/manual/single_ups_test.py`, which exists to characterise exactly
this and whose `mah_per_pct` column settles whether the gauge is a
voltage reading in disguise.
"""
import math
import threading
import time

from indepensense.power.base import BatteryReading


_ADDR = 0x2D

_STATUS_FAST_CHARGING = 0x40
_STATUS_CHARGING = 0x80
_STATUS_DISCHARGING = 0x20


def correct_percentage(raw: int, empty_raw_percent: float) -> int:
    """Rescale a raw gauge reading onto a real 0-100. See the module docstring.

    A free function because it is arithmetic over two numbers with no
    device involved, which is what lets the mapping be asserted directly
    rather than inferred from a mocked I²C bus.

    Clamped at both ends. Below the floor is a pack already flat — the
    gauge reading 57 when empty is 60 says "dead", not "minus seven" —
    and above 100 would be a gauge fault, not a battery that is more than
    full. An `empty_raw_percent` of 100 or more is a misconfiguration;
    the raw value passes through unchanged rather than dividing by zero,
    because a wrong percentage is survivable and an exception on the
    battery path is not.

    Rounds **down**, via `floor` rather than `round`. Two reasons, and
    the first is the one that matters: understating remaining charge is
    the safe error for a battery warning — the user is told sooner than
    strictly necessary rather than later than is useful. The second is
    that the builtin `round` is banker's rounding, so `round(2.5)` is 2
    while `round(3.5)` is 4; a percentage that rounds in alternating
    directions is not something anyone should have to reason about. The
    same trap is documented in `messages.round_speech_distance`.
    """
    span = 100.0 - empty_raw_percent
    if span <= 0:
        return max(0, min(100, raw))
    scaled = (raw - empty_raw_percent) / span * 100.0
    return int(max(0, min(100, math.floor(scaled))))


class WaveshareUPSHatE:
    def __init__(self, bus_number: int = 1, empty_raw_percent: float = 0.0):
        """Open the HAT.

        `empty_raw_percent` is what the gauge reads on a flat pack, from
        `config.BATTERY_EMPTY_RAW_PERCENT`. Defaults to 0.0 — no
        correction — so a caller that has not measured its own pack gets
        the gauge's own number rather than a silent rescale against
        someone else's battery.
        """
        import smbus2  # lazy: pi-only

        self._bus = smbus2.SMBus(bus_number)
        self._empty_raw_percent = empty_raw_percent
        # I²C reads must be serialised — heartbeat sender + main loop
        # both read this. smbus is not thread-safe.
        self._lock = threading.Lock()

    def read(self) -> BatteryReading | None:
        try:
            with self._lock:
                status = self._bus.read_i2c_block_data(_ADDR, 0x02, 1)[0]
                bat = self._bus.read_i2c_block_data(_ADDR, 0x20, 0x0C)
                cells = self._bus.read_i2c_block_data(_ADDR, 0x30, 0x08)
        except OSError:
            return None

        charging_state = self._parse_status(status)

        voltage_mv = bat[0] | (bat[1] << 8)
        current_ma = bat[2] | (bat[3] << 8)
        # Battery current field is signed 16-bit — the HAT reports
        # negative as two's complement above 0x7FFF. Positive = charging,
        # negative = discharging.
        if current_ma > 0x7FFF:
            current_ma -= 0x10000
        raw_percentage = bat[4] | (bat[5] << 8)
        remaining_mah = bat[6] | (bat[7] << 8)

        # Time-to-empty/full share bytes 8-11 depending on state; only
        # one is meaningful at a time. Use the fuel-gauge-reported
        # `charging_state` (authoritative) to decide which is valid,
        # rather than deriving from the current sign (which can flicker
        # near zero during idle transitions).
        time_to_empty_min = bat[8] | (bat[9] << 8)
        time_to_full_min = bat[10] | (bat[11] << 8)
        is_discharging = charging_state == "discharging"
        is_charging = charging_state in ("charging", "fast_charging")

        cell_voltages_mv = (
            cells[0] | (cells[1] << 8),
            cells[2] | (cells[3] << 8),
            cells[4] | (cells[5] << 8),
            cells[6] | (cells[7] << 8),
        )

        return BatteryReading(
            voltage_mv=voltage_mv,
            current_ma=current_ma,
            percentage=correct_percentage(raw_percentage, self._empty_raw_percent),
            raw_percentage=raw_percentage,
            remaining_mah=remaining_mah,
            charging_state=charging_state,
            cell_voltages_mv=cell_voltages_mv,
            time_to_empty_min=time_to_empty_min if is_discharging else 0,
            time_to_full_min=time_to_full_min if is_charging else 0,
            timestamp=time.time(),
        )

    def request_power_off(self) -> bool:
        """Tell the HAT to cut power to the Pi.

        Writes 0x55 to register 0x01 — this signals the HAT to enter
        a shutdown state. The caller is responsible for the OS-side
        shutdown (`sudo poweroff`) before or after this call; otherwise
        the Pi will lose power mid-write.

        Returns True on success, False on I²C failure.
        """
        try:
            with self._lock:
                self._bus.write_byte_data(_ADDR, 0x01, 0x55)
            return True
        except OSError:
            return False

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass

    @staticmethod
    def _parse_status(status: int) -> str:
        if status & _STATUS_FAST_CHARGING:
            return "fast_charging"
        if status & _STATUS_CHARGING:
            return "charging"
        if status & _STATUS_DISCHARGING:
            return "discharging"
        return "idle"
