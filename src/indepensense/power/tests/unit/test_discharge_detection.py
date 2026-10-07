"""Is the pack being drained?

The low-battery warning is gated on `is_discharging`, and it answered
"no" on a pack losing 377 mA — so the warning could not fire at any
percentage, and the first bench test to reach 27% found nothing but
silence in the journal.

The cause was a fall-through. `_parse_status` returns `"idle"` for a
status byte with no recognised bit set, and the assembled HAT never sets
its discharging bit, so `"idle"` meant "I don't know" while being read
as "nothing is happening". The current sign knew all along.
"""
from indepensense.power.base import DISCHARGE_CURRENT_MA, BatteryReading


def _reading(charging_state="idle", current_ma=0, percentage=50):
    return BatteryReading(
        voltage_mv=13928,
        current_ma=current_ma,
        percentage=percentage,
        remaining_mah=1200,
        charging_state=charging_state,
        cell_voltages_mv=(3455, 3530, 3495, 3447),
        time_to_empty_min=0,
        time_to_full_min=0,
        timestamp=0.0,
    )


# --- the field failure --------------------------------------------------------

def test_an_idle_gauge_losing_current_is_discharging():
    """The exact reading from the bench: 'idle' at -377 mA, 27%."""
    assert _reading(charging_state="idle", current_ma=-377).is_discharging


def test_the_status_bit_is_still_honoured_when_it_is_set():
    """A gauge that reports properly must keep working — the current
    signal is a fallback, not a replacement."""
    assert _reading(charging_state="discharging", current_ma=0).is_discharging


# --- what must NOT count ------------------------------------------------------

def test_a_genuinely_idle_pack_is_not_discharging():
    """The driver's own caution: current flickers near zero during idle
    transitions. A bench unit sitting still must not warn about its
    battery."""
    assert not _reading(charging_state="idle", current_ma=-5).is_discharging


def test_the_threshold_itself_counts_as_discharging():
    assert _reading(current_ma=DISCHARGE_CURRENT_MA).is_discharging
    assert not _reading(current_ma=DISCHARGE_CURRENT_MA + 1).is_discharging


def test_a_charging_pack_is_not_discharging():
    """Positive current is flowing into the pack."""
    assert not _reading(charging_state="charging", current_ma=800).is_discharging
    assert not _reading(charging_state="fast_charging", current_ma=1500).is_discharging


def test_charging_is_unaffected():
    """Only the discharge signal was wrong; `is_charging` still reads the
    state alone and must not start guessing from current."""
    assert _reading(charging_state="charging", current_ma=800).is_charging
    assert not _reading(charging_state="idle", current_ma=-377).is_charging


# --- what it unblocks ---------------------------------------------------------

def test_a_low_pack_on_an_idle_gauge_now_passes_the_alert_gate():
    """`app._check_battery_and_alert` fires on `pct < threshold and
    is_discharging`. This is the half that was always False."""
    reading = _reading(charging_state="idle", current_ma=-377, percentage=27)

    assert reading.percentage < 30 and reading.is_discharging


def test_a_charging_pack_at_the_same_percentage_stays_silent():
    """The reason the gate was kept rather than removed: a guardian must
    not get a low-battery SMS about a pack that is filling up."""
    reading = _reading(charging_state="charging", current_ma=900, percentage=27)

    assert reading.percentage < 30 and not reading.is_discharging
