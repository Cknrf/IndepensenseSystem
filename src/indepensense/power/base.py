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
    # Corrected state of charge, 0-100, and the number every consumer
    # should use. NOT what the gauge reported — see `raw_percentage`.
    percentage: int
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

    # Exactly what the fuel gauge said, before correction.
    #
    # Kept because `percentage` is a calibration against one pack and may
    # be wrong: without the raw figure a logged discharge cannot be
    # re-analysed and the constant could never be improved. It is also
    # the only way to notice the gauge drifting as the pack ages.
    #
    # Last, with a default, because only the real driver has a raw value
    # to report — mocks and tests construct readings directly and should
    # not have to invent one.
    raw_percentage: int = -1

    def __post_init__(self) -> None:
        """Default `raw_percentage` to `percentage` when it was not given.

        A hand-built reading has had no correction applied, so the two are
        genuinely the same number. The alternative — leaving the sentinel
        in place — would have a mock claim the gauge reported -1, which a
        log reader would have to know to ignore.

        `object.__setattr__` because the dataclass is frozen; this runs
        during construction, before anything can observe the old value.
        """
        if self.raw_percentage < 0:
            object.__setattr__(self, "raw_percentage", self.percentage)

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

        Implausible cell readings are ignored rather than believed. A
        cell at 0 mV is a bad I²C read, not a flat cell: a 4S pack with a
        genuinely dead cell could not be powering the Pi that is asking
        the question, and the BMS would have cut long before. Without
        this the first garbled read would tell the wearer their device is
        about to die — and now that `app.py` acts on this, that warning
        is spoken and preempts whatever else is being said.
        """
        cutoff_mv = 3150
        # Below this a reading is a fault, not a measurement. Li-ion is
        # damaged under ~2.5 V and the BMS disconnects well above that,
        # so nothing between 0 and here is a state a running pack can be
        # in. Deliberately far below `cutoff_mv`, so a real cell sagging
        # under load is still believed.
        implausible_mv = 2000
        measured = [v for v in self.cell_voltages_mv if v >= implausible_mv]
        if not measured:
            return False
        return min(measured) < cutoff_mv and not self.is_charging


class BatteryReader(Protocol):
    def read(self) -> BatteryReading | None:
        """Return a fresh reading, or None on transient I²C failure."""

    def close(self) -> None:
        ...
