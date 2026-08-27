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
"""
import threading
import time

from indepensense.power.base import BatteryReading


_ADDR = 0x2D

_STATUS_FAST_CHARGING = 0x40
_STATUS_CHARGING = 0x80
_STATUS_DISCHARGING = 0x20


class WaveshareUPSHatE:
    def __init__(self, bus_number: int = 1):
        import smbus2  # lazy: pi-only

        self._bus = smbus2.SMBus(bus_number)
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
        percentage = bat[4] | (bat[5] << 8)
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
            percentage=percentage,
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
