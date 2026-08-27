"""Battery / power interfaces.

Modeled on the Waveshare UPS HAT (E) — a 4S1P Li-ion pack (four 21700s
in series) with an I²C fuel gauge that reports voltage, current, per-cell
voltages, and a computed percentage. The dataclass here is deliberately
richer than what a hobby project usually needs because the underlying
chip already computes all of it — throwing away real data would be waste.

Consumers should mostly care about:
- `percentage` — the number the heartbeat carries
- `is_charging` — informational, useful for low-battery alert suppression
- `is_critical_low` — driver-derived flag for "shut down soon or damage cells"

The rest (cell voltages, time-to-empty) is available for logging and
future features (thesis chart of "battery over 8 hours of walking").
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class BatteryReading:
    voltage_mv: int
    # Waveshare convention: POSITIVE = charging (current flowing INTO the
    # battery), NEGATIVE = discharging (current flowing OUT to the load).
    # This matches the raw signed 16-bit value from register 0x20 after
    # two's-complement conversion.
    current_ma: int
    percentage: int                          # 0-100
    # Charge the gauge believes is left, in mAh. Read alongside
    # `percentage` because the two together say *how* the HAT estimates
    # state of charge: if `remaining_mah / percentage` stays constant the
    # gauge is scaling one fixed capacity (so `percentage` is really just
    # a voltage reading in disguise); if the ratio drifts, it is counting
    # coulombs against a learned capacity. We cannot see the MCU's
    # firmware, so this ratio is the only evidence available.
    remaining_mah: int
    charging_state: str                      # "idle" | "charging" | "fast_charging" | "discharging"
    cell_voltages_mv: tuple[int, int, int, int]
    time_to_empty_min: int                   # 0 when not discharging
    time_to_full_min: int                    # 0 when not charging
    timestamp: float                         # seconds since epoch (from time.time())

    @property
    def is_charging(self) -> bool:
        return self.charging_state in ("charging", "fast_charging")

    @property
    def is_discharging(self) -> bool:
        return self.charging_state == "discharging"

    @property
    def is_critical_low(self) -> bool:
        """True if any cell is below the safe cutoff AND not being charged.

        Battery cutoff for Li-ion is 3.0 V per cell; the Waveshare
        reference code triggers protection at 3.15 V, so we use the
        same threshold here for consistency with the hardware's own
        low-voltage protection. Once this is True for ~60 s the HAT
        will cut power on its own, so app-level graceful shutdown
        (drain telemetry, notify guardian) must happen quickly.

        We use the fuel-gauge-reported `charging_state` (authoritative)
        rather than the current sign — a briefly-idle moment during
        charging shouldn't trip the critical alarm.
        """
        cutoff_mv = 3150
        low_cell = any(v < cutoff_mv for v in self.cell_voltages_mv)
        return low_cell and not self.is_charging


class BatteryReader(Protocol):
    def read(self) -> BatteryReading | None:
        """Return a fresh reading, or None on transient I²C failure."""

    def close(self) -> None:
        ...
