"""Unit tests for low-battery alerting and its hysteresis latch.

This logic now costs money: SMS fans out to every guardian on a
`LOW_BATTERY` alert, so an unlatched or flapping alert texts the whole
contact list repeatedly. The latch was already correct when I read it —
these tests are here so it stays that way.
"""
import time

import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.config import (
    BATTERY_CHECK_INTERVAL_S,
    CRITICAL_BATTERY_PERCENT,
    CRITICAL_BATTERY_RECOVERY_PERCENT,
    LOW_BATTERY_PERCENT,
    LOW_BATTERY_RECOVERY_PERCENT,
)
from indepensense.power.base import BatteryReading
from indepensense.telemetry.base import EventType
from indepensense.telemetry.mock import MockTelemetryClient


def _reading(percentage: int, charging: bool = False) -> BatteryReading:
    return BatteryReading(
        voltage_mv=3700,
        current_ma=500 if charging else -500,
        percentage=percentage,
        remaining_mah=30 * percentage,
        charging_state="charging" if charging else "discharging",
        cell_voltages_mv=(3700, 0, 0, 0),
        time_to_empty_min=0 if charging else 90,
        time_to_full_min=45 if charging else 0,
        timestamp=time.time(),
    )


class _ScriptedBattery:
    """Returns whatever `reading` is set to at call time."""

    def __init__(self, reading=None, raise_on_read=False):
        self.reading = reading
        self.raise_on_read = raise_on_read
        self.read_count = 0

    def read(self):
        self.read_count += 1
        if self.raise_on_read:
            raise OSError("simulated I2C failure")
        return self.reading

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _latch_path(tmp_path, monkeypatch):
    """Point the persisted latch at a temp file.

    `app.py` imports the constant by value, so patching `config` would
    have no effect — the module attribute is the one that matters.
    """
    monkeypatch.setattr(
        app_module, "LOW_BATTERY_STATE_PATH", tmp_path / "low_battery_alerted",
    )
    monkeypatch.setattr(
        app_module, "CRITICAL_BATTERY_STATE_PATH",
        tmp_path / "critical_battery_alerted",
    )


class _RecordingApp(MockApp):
    """Captures announcements instead of synthesising audio."""

    def __init__(self):
        super().__init__()
        self.spoken: list[tuple[str, bool]] = []     # (text, critical)

    def _announce(self, text: str, critical: bool = False) -> None:
        self.spoken.append((text, critical))


@pytest.fixture
def app():
    instance = _RecordingApp()
    instance.battery = _ScriptedBattery()
    instance.alert_sink = MockTelemetryClient()
    return instance


def _spoken_text(app) -> list[str]:
    return [text for text, _ in app.spoken]


def _check_now(app):
    """Run a battery check, bypassing the 10 s internal rate limit."""
    app._last_battery_check = 0.0
    app._check_battery_and_alert()


def _low_battery_alerts(app):
    return [
        a for a in app.alert_sink.alerts
        if a.event_type is EventType.LOW_BATTERY
    ]


# --- firing ------------------------------------------------------------------

def test_alert_fires_below_the_threshold(app):
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    _check_now(app)

    assert len(_low_battery_alerts(app)) == 1
    assert app._low_battery_alerted is True


def test_no_alert_at_or_above_the_threshold(app):
    """The comparison is `pct < LOW_BATTERY_PERCENT`, so exactly 15% is
    not low. Pinned so a refactor can't flip it unnoticed."""
    app.battery.reading = _reading(LOW_BATTERY_PERCENT)
    _check_now(app)
    assert _low_battery_alerts(app) == []


def test_a_charging_device_does_not_alert(app):
    """Plugged in at 10% is not an emergency — it's a device being looked
    after. Texting every guardian about it would be noise."""
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 5, charging=True)
    _check_now(app)
    assert _low_battery_alerts(app) == []


# --- the latch ---------------------------------------------------------------

def test_the_alert_fires_once_not_on_every_check(app):
    """Without the latch, a battery sitting at 14% would text every
    guardian every 10 seconds."""
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    for _ in range(5):
        _check_now(app)

    assert len(_low_battery_alerts(app)) == 1


def test_the_latch_clears_only_above_the_recovery_threshold(app):
    """Hysteresis: two separate thresholds stop a battery hovering at the
    boundary from flapping between alerted and clear."""
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    _check_now(app)

    # Between fire and recovery thresholds — still latched.
    app.battery.reading = _reading(LOW_BATTERY_PERCENT + 1)
    _check_now(app)
    assert app._low_battery_alerted is True

    app.battery.reading = _reading(LOW_BATTERY_RECOVERY_PERCENT)
    _check_now(app)
    assert app._low_battery_alerted is False


def test_a_second_discharge_cycle_alerts_again(app):
    """One alert per discharge, not one alert ever."""
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    _check_now(app)
    app.battery.reading = _reading(LOW_BATTERY_RECOVERY_PERCENT + 10)
    _check_now(app)
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    _check_now(app)

    assert len(_low_battery_alerts(app)) == 2


def test_the_latch_survives_a_restart():
    """A Pi crash-looping on a low battery must not text every guardian on
    each boot. `Restart=on-failure` in the systemd unit makes that
    reachable, so the latch is mirrored to disk."""
    first = MockApp()
    first.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    first.alert_sink = MockTelemetryClient()
    _check_now(first)
    assert first._low_battery_alerted is True

    # A fresh process, battery unchanged: still latched, so silent.
    second = MockApp()
    second.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    second.alert_sink = MockTelemetryClient()
    assert second._low_battery_alerted is True
    _check_now(second)
    assert _low_battery_alerts(second) == []


def test_recovery_clears_the_latch_across_a_restart():
    """The mirror has to work in both directions, or a device that
    recovered would stay permanently silent about future low batteries."""
    first = MockApp()
    first.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    first.alert_sink = MockTelemetryClient()
    _check_now(first)
    first.battery.reading = _reading(LOW_BATTERY_RECOVERY_PERCENT + 5)
    _check_now(first)

    second = MockApp()
    second.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    second.alert_sink = MockTelemetryClient()
    assert second._low_battery_alerted is False
    _check_now(second)
    assert len(_low_battery_alerts(second)) == 1


def test_an_unwritable_latch_path_still_alerts(tmp_path, monkeypatch):
    """Persistence is best effort. Losing it across a reboot is
    acceptable; refusing to alert a guardian is not."""
    blocked = tmp_path / "file-not-a-dir"
    blocked.write_text("x")
    monkeypatch.setattr(app_module, "LOW_BATTERY_STATE_PATH", blocked / "latch")

    instance = MockApp()
    instance.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    instance.alert_sink = MockTelemetryClient()
    _check_now(instance)

    assert len(_low_battery_alerts(instance)) == 1
    assert instance._low_battery_alerted is True


# --- rate limiting -----------------------------------------------------------

def test_checks_are_rate_limited_off_the_hot_loop(app):
    """Called from the 100 Hz loop but throttled internally — the I2C bus
    is shared with the IMU and both ultrasonics."""
    app.battery.reading = _reading(50)
    app._last_battery_check = time.monotonic()

    for _ in range(20):
        app._check_battery_and_alert()

    assert app.battery.read_count == 0


def test_the_rate_limit_expires(app):
    app.battery.reading = _reading(50)
    app._last_battery_check = time.monotonic() - (BATTERY_CHECK_INTERVAL_S + 1)
    app._check_battery_and_alert()
    assert app.battery.read_count == 1


# --- degradation -------------------------------------------------------------

def test_absent_battery_reader_is_a_no_op(app):
    app.battery = None
    _check_now(app)
    assert app.alert_sink.alerts == []


def test_a_raising_reader_does_not_break_the_loop(app):
    app.battery.raise_on_read = True
    _check_now(app)
    assert app.alert_sink.alerts == []
    assert app._low_battery_alerted is False


def test_a_none_reading_is_ignored(app):
    """A transient read failure must not be read as 0%."""
    app.battery.reading = None
    _check_now(app)
    assert app.alert_sink.alerts == []
    assert app._low_battery_alerted is False


# --- warning the wearer ------------------------------------------------------
#
# Guardians have had an SMS and a dashboard alert since the first threshold.
# The person actually carrying the device was the only one not told, and
# found out when it died.

def test_the_wearer_is_warned_at_the_low_threshold(app):
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    _check_now(app)

    assert len(app.spoken) == 1
    text, critical = app.spoken[0]
    assert str(LOW_BATTERY_PERCENT - 1) in text
    assert critical is False, "a 15% warning should not cut off speech in progress"


def test_the_low_warning_is_spoken_once_per_crossing(app):
    """Same latch that stops the guardian SMS flapping — the wearer should
    not be nagged every ten seconds either."""
    app.battery.reading = _reading(LOW_BATTERY_PERCENT - 1)
    _check_now(app)
    _check_now(app)
    _check_now(app)

    assert len(app.spoken) == 1


def test_the_critical_warning_preempts(app):
    """"Your device is about to die" is worth interrupting a turn
    instruction for; "charge it soon" is not."""
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)

    critical_flags = [critical for _, critical in app.spoken]
    assert True in critical_flags


def test_crossing_both_thresholds_speaks_both_tiers(app):
    """Different instructions: charge soon, then it is about to shut down."""
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)

    assert len(app.spoken) == 2
    assert app.spoken[0][1] is False        # low warning, not critical
    assert app.spoken[1][1] is True         # critical warning


def test_the_critical_tier_does_not_alert_guardians_again(app):
    """They were told at 15% over SMS and the dashboard. A second text as
    the battery dies says nothing they can act on."""
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)

    assert len(_low_battery_alerts(app)) == 1


def test_the_critical_warning_is_spoken_once_per_crossing(app):
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)
    _check_now(app)

    assert len(app.spoken) == 2      # one low + one critical, not four


def test_a_charging_device_is_not_warned(app):
    """Plugged in at 3% is a device being looked after, not an emergency."""
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 2, charging=True)
    _check_now(app)

    assert app.spoken == []


def test_the_critical_latch_clears_on_recovery(app):
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)
    assert app._critical_battery_alerted is True

    app.battery.reading = _reading(CRITICAL_BATTERY_RECOVERY_PERCENT + 1)
    _check_now(app)

    assert app._critical_battery_alerted is False


def test_the_two_latches_are_independent(app):
    """Recovering past 10% must not clear the 15% latch, or the guardian
    SMS would re-fire on the way back down."""
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)
    assert app._low_battery_alerted is True
    assert app._critical_battery_alerted is True

    # Back above the critical recovery point but still below the low one.
    app.battery.reading = _reading(CRITICAL_BATTERY_RECOVERY_PERCENT + 1)
    _check_now(app)

    assert app._critical_battery_alerted is False
    assert app._low_battery_alerted is True


def test_the_critical_latch_survives_a_restart(app, tmp_path):
    """Same reasoning as the low-battery latch: a crash-looping Pi on a
    dying battery must not repeat the warning on every boot."""
    app.battery.reading = _reading(CRITICAL_BATTERY_PERCENT - 1)
    _check_now(app)

    restarted = _RecordingApp()
    assert restarted._critical_battery_alerted is True


def test_a_failing_announcer_still_sets_the_latch(app):
    """If the announcement could abort the check, the latch would never be
    set and the guardian SMS would re-fire on every ten-second poll —
    texting the whole contact list until the battery died."""
    class _BrokenAnnouncer:
        def say(self, *args, **kwargs):
            raise OSError("audio device gone")

    plain = MockApp()
    plain.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    plain.alert_sink = MockTelemetryClient()
    plain.announcer = _BrokenAnnouncer()

    _check_now(plain)
    _check_now(plain)
    _check_now(plain)

    assert plain._low_battery_alerted is True
    assert len(_low_battery_alerts(plain)) == 1
