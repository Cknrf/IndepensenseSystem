"""Mock battery reader for off-device development and testing.

`MockBatteryReader` returns a scripted sequence of `BatteryReading`s.
Tests use this to simulate battery draining, charging cycles, and I²C
failures without touching real hardware.
"""
import time
from itertools import cycle

from indepensense.power.base import BatteryReading


# Nominal pack capacity: the HAT is 4S1P, so pack mAh equals single-cell
# mAh — four 21700s in series store 4x the energy at 4x the voltage, not
# 4x the charge. Matches the ~4750 mAh divisor the real gauge was
# measured using. Only used to give the mock a plausible default; the
# real value comes off the HAT.
_NOMINAL_CAPACITY_MAH = 4750


def _make_reading(
    percentage: int = 100,
    voltage_mv: int = 16800,
    current_ma: int = 0,
    charging_state: str = "idle",
    cell_voltages_mv: tuple[int, int, int, int] = (4200, 4200, 4200, 4200),
    remaining_mah: int | None = None,
) -> BatteryReading:
    """Build a synthetic BatteryReading with sensible defaults.

    `remaining_mah` defaults to `percentage` scaled against a nominal
    pack capacity, so a scripted drain sequence stays self-consistent
    without every caller having to compute it.
    """
    if remaining_mah is None:
        remaining_mah = round(_NOMINAL_CAPACITY_MAH * percentage / 100)
    return BatteryReading(
        voltage_mv=voltage_mv,
        current_ma=current_ma,
        percentage=percentage,
        remaining_mah=remaining_mah,
        charging_state=charging_state,
        cell_voltages_mv=cell_voltages_mv,
        time_to_empty_min=0,
        time_to_full_min=0,
        timestamp=time.time(),
    )


class MockBatteryReader:
    """Battery reader that returns pre-scripted readings.

    Configure with `readings=[...]` — the reader cycles through the
    list, returning each in order. Once the list is exhausted, it
    repeats from the start. Pass `None` in the sequence to simulate a
    transient read failure.
    """

    def __init__(
        self,
        readings: list[BatteryReading | None] | None = None,
    ):
        if not readings:
            readings = [_make_reading()]
        self._iter = cycle(readings)
        self.closed = False

    def read(self) -> BatteryReading | None:
        return next(self._iter)

    def close(self) -> None:
        self.closed = True


# Convenience factory so tests read cleanly.
def make_reading(**kwargs) -> BatteryReading:
    """Public re-export of `_make_reading` for tests."""
    return _make_reading(**kwargs)
