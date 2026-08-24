"""Unit tests for low-battery alerting and its hysteresis latch.

This logic now costs money: SMS fans out to every guardian on a
`LOW_BATTERY` alert, so an unlatched or flapping alert texts the whole
contact list repeatedly. The latch was already correct when I read it —
these tests are here so it stays that way.
"""
import time

import pytest

from indepensense.app_mock import MockApp
from indepensense.config import (
    BATTERY_CHECK_INTERVAL_S,
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


@pytest.fixture
def app():
    instance = MockApp()
    instance.battery = _ScriptedBattery()
    instance.alert_sink = MockTelemetryClient()
    return instance


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


def test_the_latch_does_not_survive_a_restart():
    """Documents a real limitation rather than asserting desired
    behaviour. The latch is in-memory, so a Pi that crash-loops at 14%
    re-alerts on every boot — and with SMS wired in, that texts every
    guardian each time. `Restart=on-failure` in the systemd unit makes
    this reachable. Persisting it alongside `var/language` would fix it.
    """
    first = MockApp()
    first.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    first.alert_sink = MockTelemetryClient()
    _check_now(first)
    assert first._low_battery_alerted is True

    # A fresh process, battery unchanged.
    second = MockApp()
    second.battery = _ScriptedBattery(_reading(LOW_BATTERY_PERCENT - 1))
    second.alert_sink = MockTelemetryClient()
    assert second._low_battery_alerted is False
    _check_now(second)
    assert len(_low_battery_alerts(second)) == 1


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
