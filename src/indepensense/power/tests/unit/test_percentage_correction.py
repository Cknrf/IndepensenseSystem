"""Unit tests for the fuel-gauge percentage correction.

The HAT's gauge does not read 0 at empty. Measured on this unit across
three discharges: the Pi lost power, and reading immediately after
reconnecting the charger showed 59%.

That was not cosmetic. `LOW_BATTERY_PERCENT` (15) and
`CRITICAL_BATTERY_PERCENT` (5) both sit below a floor the gauge never
reaches, so neither alert had ever fired or could — the wearable gave no
warning and simply died.

`correct_percentage` is a free function so the mapping is asserted
directly rather than inferred from a mocked I²C bus.
"""
import pytest

from indepensense.config import (
    BATTERY_EMPTY_RAW_PERCENT,
    CRITICAL_BATTERY_PERCENT,
    LOW_BATTERY_PERCENT,
)
from indepensense.power.base import BatteryReading
from indepensense.power.waveshare_ups_e import correct_percentage

EMPTY = 60.0


# --- the mapping -------------------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    (100, 100),      # full stays full
    (60, 0),         # the measured floor is zero
    (80, 50),        # midpoint of the usable span
    (70, 25),
    (90, 75),
])
def test_the_raw_reading_is_rescaled_onto_the_usable_span(raw, expected):
    assert correct_percentage(raw, EMPTY) == expected


def test_one_raw_point_is_worth_about_two_and_a_half():
    """The span is 40 raw points mapped onto 100, so the gauge overstates
    remaining charge by ~2.5x in the region the warnings live in."""
    assert correct_percentage(61, EMPTY) == 2
    assert correct_percentage(62, EMPTY) == 5


def test_rounding_goes_down_and_never_alternates():
    """Understating remaining charge tells the user sooner than strictly
    necessary rather than later than is useful. The builtin `round` is
    banker's rounding — `round(2.5)` is 2 but `round(3.5)` is 4 — and a
    percentage that rounds in alternating directions is not something
    anyone should have to reason about."""
    assert correct_percentage(61, EMPTY) == 2       # 2.5 exactly
    assert correct_percentage(63, EMPTY) == 7       # 7.5 exactly
    assert correct_percentage(69, EMPTY) == 22      # 22.5 exactly


def test_below_the_floor_clamps_to_zero():
    """A pack reading under the floor is flat, not negative."""
    assert correct_percentage(57, EMPTY) == 0
    assert correct_percentage(0, EMPTY) == 0


def test_above_full_clamps_to_full():
    """A gauge reading over 100 is a fault, not a battery more than full."""
    assert correct_percentage(120, EMPTY) == 100


def test_no_calibration_passes_the_raw_value_through():
    """The driver default. A caller that has not measured its own pack
    gets the gauge's own number rather than a silent rescale against
    someone else's battery."""
    assert correct_percentage(73, 0.0) == 73


def test_a_misconfigured_floor_does_not_raise():
    """A wrong percentage is survivable; an exception on the battery path
    is not."""
    assert correct_percentage(73, 100.0) == 73
    assert correct_percentage(73, 150.0) == 73


# --- the thresholds are reachable again --------------------------------------

def test_both_alert_thresholds_now_fall_inside_the_gauges_range():
    """The bug this fixes, stated as an assertion: before the correction
    both thresholds sat below a floor the gauge never reaches, so neither
    could ever fire."""
    span = 100.0 - BATTERY_EMPTY_RAW_PERCENT

    for threshold in (LOW_BATTERY_PERCENT, CRITICAL_BATTERY_PERCENT):
        raw_needed = BATTERY_EMPTY_RAW_PERCENT + threshold / 100.0 * span
        assert BATTERY_EMPTY_RAW_PERCENT < raw_needed <= 100, threshold
        assert correct_percentage(round(raw_needed), BATTERY_EMPTY_RAW_PERCENT) \
            == pytest.approx(threshold, abs=2)


def test_the_configured_floor_is_at_or_above_what_was_measured():
    """Measured at 59. The error is asymmetric — setting this below the
    true floor warns early and costs nothing, setting it above reports
    charge remaining on a dead pack — so the constant must never be
    tuned down past the observation."""
    assert BATTERY_EMPTY_RAW_PERCENT >= 59.0


# --- the raw value stays available -------------------------------------------

def test_a_hand_built_reading_reports_its_own_percentage_as_raw():
    """Mocks and tests construct readings directly and have had no
    correction applied, so the two are genuinely the same number. The
    sentinel must not leak into a log as "the gauge reported -1"."""
    reading = BatteryReading(
        voltage_mv=15000, current_ma=-500, percentage=42, remaining_mah=2000,
        charging_state="discharging", cell_voltages_mv=(3750,) * 4,
        time_to_empty_min=60, time_to_full_min=0, timestamp=0.0,
    )
    assert reading.raw_percentage == 42


def test_an_explicit_raw_value_is_kept():
    """Without it a logged discharge cannot be re-analysed and the
    constant could never be improved."""
    reading = BatteryReading(
        voltage_mv=15000, current_ma=-500, percentage=5, remaining_mah=2000,
        charging_state="discharging", cell_voltages_mv=(3750,) * 4,
        time_to_empty_min=60, time_to_full_min=0, timestamp=0.0,
        raw_percentage=62,
    )
    assert (reading.percentage, reading.raw_percentage) == (5, 62)
