"""Unit tests for IntentExecutor.

Uses the existing mock Router / mock Geocoder / mock GPS from the sensor
and routing modules — no live LLM, no live services, no hardware.
"""
import time

from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.routing.mock import MockGeocoder, MockRouter
from indepensense.sensors.base import GPSFix


class _StaticGPS:
    """A GPS mock with configurable fix quality (0 = no fix, 1 = GPS)."""

    def __init__(self, lat: float = 14.5824, lon: float = 120.9760, fix_quality: int = 1):
        self._lat = lat
        self._lon = lon
        self._fix_quality = fix_quality

    def read(self) -> GPSFix | None:
        return GPSFix(
            lat=self._lat,
            lon=self._lon,
            altitude_m=15.0,
            speed_knots=0.0,
            course_deg=None,
            satellites=8,
            hdop=1.2,
            fix_quality=self._fix_quality,
            utc_time=None,
            timestamp=time.time(),
        )

    def close(self) -> None:
        pass


def _make_executor(fix_quality: int = 1) -> IntentExecutor:
    return IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        gps=_StaticGPS(fix_quality=fix_quality),
    )


def test_navigation_start_returns_route_summary():
    executor = _make_executor()
    result = IntentResult(
        intent=Intent.NAVIGATION_START,
        parameters={"location": "Jollibee", "nearest": False},
    )
    response = executor.execute(result)
    assert "Navigating" in response
    assert "Jollibee" in response


def test_navigation_start_without_location_asks_again():
    executor = _make_executor()
    result = IntentResult(Intent.NAVIGATION_START, {"location": "", "nearest": False})
    response = executor.execute(result)
    assert "didn't hear" in response.lower() or "try again" in response.lower()


def test_navigation_start_without_gps_fix_declines():
    executor = _make_executor(fix_quality=0)
    result = IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    )
    response = executor.execute(result)
    assert "gps" in response.lower()


def test_navigation_stop_without_active_route_says_no_active():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.NAVIGATION_STOP))
    assert "no" in response.lower() or "don't" in response.lower() or "active" in response.lower()


def test_navigation_stop_after_start_cancels():
    executor = _make_executor()
    executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))
    response = executor.execute(IntentResult(Intent.NAVIGATION_STOP))
    assert "cancel" in response.lower()


def test_navigation_repeat_before_navigation_says_nothing_to_repeat():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert "no instruction" in response.lower() or "repeat" in response.lower()


def test_navigation_repeat_after_start_returns_last_instruction():
    executor = _make_executor()
    start_response = executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": "Jollibee", "nearest": False}
    ))
    repeat_response = executor.execute(IntentResult(Intent.NAVIGATION_REPEAT))
    assert repeat_response  # non-empty
    # The repeated instruction is a substring of the start-navigation message
    assert repeat_response in start_response


def test_navigation_location_uses_reverse_geocode():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.NAVIGATION_LOCATION))
    assert "You are near" in response or "latitude" in response.lower()


def test_emergency_returns_confirmation():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.EMERGENCY_TRIGGER))
    assert "emergency" in response.lower() or "guardian" in response.lower()


def test_device_status_gps_with_fix():
    executor = _make_executor(fix_quality=1)
    response = executor.execute(IntentResult(
        Intent.DEVICE_STATUS, {"status_field": "gps"}
    ))
    assert "gps" in response.lower() and "lock" in response.lower()


def test_device_status_gps_without_fix():
    executor = _make_executor(fix_quality=0)
    response = executor.execute(IntentResult(
        Intent.DEVICE_STATUS, {"status_field": "gps"}
    ))
    assert "no fix" in response.lower()


def test_system_time_returns_current_time():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.SYSTEM_TIME))
    # response looks like "It's currently 2:34 PM."
    assert "currently" in response.lower()
    assert any(c.isdigit() for c in response)


def test_unknown_intent_asks_user_to_retry():
    executor = _make_executor()
    response = executor.execute(IntentResult(Intent.UNKNOWN))
    assert "didn't understand" in response.lower() or "try again" in response.lower()
