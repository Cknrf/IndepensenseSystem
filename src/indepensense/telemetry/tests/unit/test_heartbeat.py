"""Unit tests for PeriodicHeartbeatSender.

Uses short intervals (10-50 ms) so tests complete quickly. Waits use
polling with a 2 s hard timeout so tests never hang if a bug freezes
the worker thread.

The sender's `_probe_internet()` makes a real HTTP HEAD request once per
heartbeat. Left unstubbed that would make this suite depend on the dev
machine's connectivity — tests would flip result offline, and each beat
would stall for the 2 s probe timeout behind a firewall. The autouse
`_no_network` fixture below stubs it out for every test in this module;
the two probe-specific tests override the stub to assert each branch.
"""
import threading
import time

import pytest
import requests

from indepensense.sensors.base import GPSFix
from indepensense.telemetry.heartbeat import PeriodicHeartbeatSender
from indepensense.telemetry.mock import MockTelemetryClient


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Stub `requests.head` so no test in this module touches the network."""
    def _refuse(*_args, **_kwargs):
        raise requests.RequestException("network disabled in unit tests")

    monkeypatch.setattr(requests, "head", _refuse)


class _FakeGPS:
    """Configurable GPS mock.

    - `fix_quality=1` and lat/lon → returns a valid fix
    - `fix_quality=0` → no-fix
    - `raise_on_read=True` → raises OSError on read
    """

    def __init__(
        self,
        lat: float = 14.5824,
        lon: float = 120.9760,
        fix_quality: int = 1,
        raise_on_read: bool = False,
    ):
        self._lat = lat
        self._lon = lon
        self._fix_quality = fix_quality
        self._raise = raise_on_read

    def read(self):
        if self._raise:
            raise OSError("simulated GPS read failure")
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


def _wait_until(condition, timeout_s: float = 2.0, poll_s: float = 0.01) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(poll_s)
    return False


# --- basic lifecycle --------------------------------------------------------

def test_start_sends_at_least_one_heartbeat():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.02)
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        assert sender.sent_count >= 1
    finally:
        sender.stop(timeout_s=1.0)


def test_sends_multiple_heartbeats_at_interval():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.05)
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 5, timeout_s=3.0)
    finally:
        sender.stop(timeout_s=1.0)


def test_stop_returns_promptly_even_with_long_interval():
    """stop() must not wait the full interval — the loop wakes early via
    the stop event."""
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=30.0)
    sender.start()
    time.sleep(0.05)   # let the loop fire once
    t0 = time.time()
    sender.stop(timeout_s=2.0)
    elapsed = time.time() - t0
    assert elapsed < 1.0, f"stop() took {elapsed}s, expected << 30s"


def test_start_is_idempotent():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.05)
    sender.start()
    sender.start()   # second call should be a no-op, not spawn a second thread
    time.sleep(0.15)
    sender.stop(timeout_s=1.0)


# --- GPS handling ----------------------------------------------------------

def test_uses_real_gps_lat_lon_when_available():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(
        tel, _FakeGPS(lat=13.9374, lon=121.1186), "dev", interval_s=0.02,
    )
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        hb = tel.heartbeats[0]
        assert hb.latitude == 13.9374
        assert hb.longitude == 121.1186
    finally:
        sender.stop(timeout_s=1.0)


def test_falls_back_to_zero_when_gps_is_none():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, None, "dev", interval_s=0.02)
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        hb = tel.heartbeats[0]
        assert hb.latitude == 0.0
        assert hb.longitude == 0.0
    finally:
        sender.stop(timeout_s=1.0)


def test_falls_back_to_zero_when_gps_has_no_fix():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(
        tel, _FakeGPS(fix_quality=0), "dev", interval_s=0.02,
    )
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        hb = tel.heartbeats[0]
        assert hb.latitude == 0.0
        assert hb.longitude == 0.0
    finally:
        sender.stop(timeout_s=1.0)


def test_survives_gps_read_exception():
    """A raising GPS driver must not kill the heartbeat loop."""
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(
        tel, _FakeGPS(raise_on_read=True), "dev", interval_s=0.02,
    )
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 3, timeout_s=2.0)
        # All heartbeats used the 0/0 fallback.
        assert all(hb.latitude == 0.0 and hb.longitude == 0.0 for hb in tel.heartbeats)
    finally:
        sender.stop(timeout_s=1.0)


# --- failure accounting -----------------------------------------------------

def test_counts_successful_sends():
    tel = MockTelemetryClient(succeed=True)
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.02)
    sender.start()
    try:
        assert _wait_until(lambda: sender.sent_count >= 3, timeout_s=2.0)
        assert sender.failed_count == 0
    finally:
        sender.stop(timeout_s=1.0)


def test_counts_failed_sends():
    tel = MockTelemetryClient(succeed=False)
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.02)
    sender.start()
    try:
        assert _wait_until(lambda: sender.failed_count >= 3, timeout_s=2.0)
        assert sender.sent_count == 0
    finally:
        sender.stop(timeout_s=1.0)


class _RaisingTelemetry:
    """Telemetry client that always raises. Used to verify the worker
    doesn't die from a broken inner client."""

    def __init__(self):
        self.call_count = 0

    def send_heartbeat(self, info):
        self.call_count += 1
        raise RuntimeError("simulated telemetry failure")

    def send_alert(self, event):
        raise RuntimeError("not used")


def test_survives_raising_telemetry_client():
    tel = _RaisingTelemetry()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.02)
    sender.start()
    try:
        # Wait on failed_count (not tel.call_count) — the raise happens
        # inside the mock's send_heartbeat, so tel.call_count increments
        # BEFORE the sender's except block bumps failed_count. Waiting
        # on failed_count avoids a race where we assert too early and
        # see call_count=3 but failed_count still lagging at 2.
        assert _wait_until(lambda: sender.failed_count >= 3, timeout_s=2.0)
        assert tel.call_count >= 3
    finally:
        sender.stop(timeout_s=1.0)


# --- payload correctness ----------------------------------------------------

def test_heartbeat_uses_configured_device_id():
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(
        tel, _FakeGPS(), "unique-device-uuid", interval_s=0.02,
    )
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        assert tel.heartbeats[0].device_id == "unique-device-uuid"
    finally:
        sender.stop(timeout_s=1.0)


def test_battery_health_defaults_to_100_without_a_reader():
    """With no BatteryReader wired (dev on Mac, HAT not installed) we
    report 100 rather than 0, so the guardian dashboard doesn't misread
    "no reader" as "critical low battery". This guards that deliberate
    default against being changed silently."""
    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.02)
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        assert tel.heartbeats[0].battery_health == 100
    finally:
        sender.stop(timeout_s=1.0)


def test_internet_status_false_when_probe_fails(monkeypatch):
    """A network-level failure reaching the probe target means offline."""
    def _fail(*_args, **_kwargs):
        raise requests.ConnectionError("simulated DNS failure")

    monkeypatch.setattr(requests, "head", _fail)

    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(tel, _FakeGPS(), "dev", interval_s=0.02)
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        assert tel.heartbeats[0].internet_status is False
    finally:
        sender.stop(timeout_s=1.0)


def test_internet_status_true_when_probe_reaches_target(monkeypatch):
    """Any HTTP response — including a 5xx — means we reached the target,
    which means we're online. Only a network failure means offline."""
    calls: list[dict] = []

    def _respond(url, **kwargs):
        calls.append({"url": url, **kwargs})
        response = requests.Response()
        response.status_code = 503
        return response

    monkeypatch.setattr(requests, "head", _respond)

    tel = MockTelemetryClient()
    sender = PeriodicHeartbeatSender(
        tel, _FakeGPS(), "dev", interval_s=0.02, internet_probe_url="http://probe.test",
    )
    sender.start()
    try:
        assert _wait_until(lambda: len(tel.heartbeats) >= 1)
        assert tel.heartbeats[0].internet_status is True
    finally:
        sender.stop(timeout_s=1.0)

    assert calls[0]["url"] == "http://probe.test"


# --- validation --------------------------------------------------------------

def test_zero_interval_is_rejected():
    with pytest.raises(ValueError):
        PeriodicHeartbeatSender(MockTelemetryClient(), None, "dev", interval_s=0)


def test_negative_interval_is_rejected():
    with pytest.raises(ValueError):
        PeriodicHeartbeatSender(MockTelemetryClient(), None, "dev", interval_s=-1)
