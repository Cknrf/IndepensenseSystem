"""Unit tests for `GPSCache`, which owns the GPS device and reopens it.

The behaviour under test exists because of one observed failure: the
SIM7600 re-enumerates — a dmesg two seconds apart shows it drop
`ttyUSB2`-`ttyUSB5` and return as `ttyUSB0`-`ttyUSB4` — and the cache
used to hold a single handle opened at startup. After a re-enumeration
every read raised, the loop logged the same error once a second, and
`latest_fix()` kept answering with a position from before the
disconnect. The device looked healthy and every emergency alert from
that point carried a stale fix.

Driven by stub devices rather than timing. The worker thread polls on an
interval and sleeps between ticks, so a test that waited for real time
would be slow and flaky; `_poll_once` and `_attempt_reopen` are called
directly instead, which is also what makes the failure *counting* legible
rather than inferred from how long something took.
"""
import pytest

from indepensense.app import (
    GPS_FAILURES_BEFORE_REOPEN,
    GPS_REOPEN_BACKOFF_MAX_S,
    GPS_REOPEN_BACKOFF_START_S,
    GPSCache,
)
from indepensense.sensors.base import GPSFix


def _fix(quality: int = 1, lat: float = 14.5824):
    return GPSFix(
        lat=lat, lon=120.9760, altitude_m=15.0, speed_knots=0.0,
        course_deg=None, satellites=8, hdop=1.2, fix_quality=quality,
        utc_time=None, timestamp=0.0,
    )


class _StubGPS:
    """A GPS whose every read is scripted. `raises` makes `read()` throw."""

    def __init__(self, reads=None, raises: bool = False):
        self._reads = list(reads or [])
        self.raises = raises
        self.closed = False
        self.read_count = 0

    def read(self):
        self.read_count += 1
        if self.raises:
            raise OSError("device disappeared")
        return self._reads.pop(0) if self._reads else None

    def close(self):
        self.closed = True


class _Factory:
    """Records how often it was called and hands out scripted devices."""

    def __init__(self, *devices):
        self._devices = list(devices)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self._devices.pop(0) if self._devices else None


# --- the ordinary path -------------------------------------------------------

def test_a_good_read_is_cached():
    gps = _StubGPS([_fix(lat=10.5)])
    cache = GPSCache(_Factory(gps))
    cache._gps = gps

    cache._poll_once()

    assert cache.latest_fix().lat == 10.5


def test_a_fix_with_no_lock_is_not_cached():
    """`fix_quality == 0` is the receiver saying it does not know where
    it is. Caching that would overwrite a real position with a blank."""
    gps = _StubGPS([_fix(lat=10.5), _fix(quality=0, lat=99.0)])
    cache = GPSCache(_Factory(gps))
    cache._gps = gps

    cache._poll_once()
    cache._poll_once()

    assert cache.latest_fix().lat == 10.5


# --- no fix is not a failure -------------------------------------------------

def test_reads_with_no_fix_never_trigger_a_reopen():
    """The trap this class had to avoid. Indoors, and through a cold
    start, a working receiver returns None every second. Counting those
    as failures would make the device close and reopen its own serial
    port the whole time its user is inside — turning a working GPS into
    a broken one."""
    gps = _StubGPS()                      # read() returns None forever
    factory = _Factory(gps)
    cache = GPSCache(factory)
    cache._gps = gps

    for _ in range(GPS_FAILURES_BEFORE_REOPEN * 5):
        cache._poll_once()

    assert cache._gps is gps, "reopened on a receiver that was merely unfixed"
    assert not gps.closed
    assert factory.calls == 0


# --- the reopen --------------------------------------------------------------

def test_one_read_error_does_not_reopen():
    """A single glitch is not a dead handle."""
    gps = _StubGPS(raises=True)
    cache = GPSCache(_Factory(gps))
    cache._gps = gps

    cache._poll_once()

    assert cache._gps is gps
    assert not gps.closed


def test_consecutive_errors_close_and_reopen():
    dead, fresh = _StubGPS(raises=True), _StubGPS([_fix()])
    factory = _Factory(fresh)
    cache = GPSCache(factory)
    cache._gps = dead

    for _ in range(GPS_FAILURES_BEFORE_REOPEN):
        cache._poll_once()

    assert dead.closed, "the dead handle was leaked"
    assert cache._gps is None, "should be waiting to reopen"

    cache._attempt_reopen()

    assert cache._gps is fresh
    assert factory.calls == 1


def test_a_good_read_resets_the_failure_count():
    """Two errors, a success, two more errors — that is not five
    consecutive failures and must not reopen."""
    gps = _StubGPS([_fix()])
    cache = GPSCache(_Factory(gps))
    cache._gps = gps

    gps.raises = True
    cache._poll_once()
    cache._poll_once()
    gps.raises = False
    cache._poll_once()                    # the scripted good read
    gps.raises = True
    cache._poll_once()
    cache._poll_once()

    assert cache._gps is gps
    assert not gps.closed


def test_recovery_restores_the_fix_stream():
    """The whole point: a position after the reopen, not a stale one."""
    dead, fresh = _StubGPS(raises=True), _StubGPS([_fix(lat=55.0)])
    cache = GPSCache(_Factory(fresh))
    cache._gps = dead

    for _ in range(GPS_FAILURES_BEFORE_REOPEN):
        cache._poll_once()
    cache._attempt_reopen()
    cache._poll_once()

    assert cache.latest_fix().lat == 55.0


# --- backoff -----------------------------------------------------------------

def test_a_failed_reopen_backs_off_instead_of_spinning():
    """A dongle that is physically absent must not cost one failed open
    and one log line every second for the rest of the run."""
    cache = GPSCache(_Factory())          # the factory always returns None

    cache._attempt_reopen()
    first = cache._backoff_s
    cache._next_attempt_at = 0.0          # pretend the wait elapsed
    cache._attempt_reopen()

    assert first == GPS_REOPEN_BACKOFF_START_S * 2
    assert cache._backoff_s == first * 2


def test_the_backoff_is_bounded():
    cache = GPSCache(_Factory())

    for _ in range(50):
        cache._next_attempt_at = 0.0
        cache._attempt_reopen()

    assert cache._backoff_s == GPS_REOPEN_BACKOFF_MAX_S


def test_the_backoff_is_respected_between_attempts():
    factory = _Factory()
    cache = GPSCache(factory)

    cache._attempt_reopen()               # attempt 1, schedules the next
    cache._attempt_reopen()               # too soon — must not call again

    assert factory.calls == 1


def test_a_successful_reopen_resets_the_backoff():
    """Otherwise a device that drops twice in one session would wait a
    minute to come back the second time."""
    cache = GPSCache(_Factory(None, None, _StubGPS()))

    cache._attempt_reopen()
    cache._next_attempt_at = 0.0
    cache._attempt_reopen()
    assert cache._backoff_s > GPS_REOPEN_BACKOFF_START_S

    cache._next_attempt_at = 0.0
    cache._attempt_reopen()

    assert cache._backoff_s == GPS_REOPEN_BACKOFF_START_S


# --- lifecycle ---------------------------------------------------------------

def test_start_reports_whether_the_device_opened():
    opened = GPSCache(_Factory(_StubGPS()))
    assert opened.start() is True
    opened.stop(timeout_s=0.5)

    missing = GPSCache(_Factory())
    assert missing.start() is False
    missing.stop(timeout_s=0.5)


def test_the_worker_runs_even_when_the_first_open_fails():
    """A dongle missing at boot used to mean no GPS for the whole run.
    The same backoff that recovers a mid-run disconnect picks it up."""
    cache = GPSCache(_Factory())
    cache.start()
    try:
        assert cache._thread.is_alive()
    finally:
        cache.stop(timeout_s=0.5)


def test_stop_closes_the_device():
    gps = _StubGPS()
    cache = GPSCache(_Factory(gps))
    cache.start()
    cache.stop(timeout_s=0.5)

    assert gps.closed


def test_stopping_twice_does_not_raise():
    """`App.stop` is reachable from more than one path and must stay
    best-effort."""
    cache = GPSCache(_Factory(_StubGPS()))
    cache.start()
    cache.stop(timeout_s=0.5)
    cache.stop(timeout_s=0.5)


def test_a_close_that_raises_is_swallowed():
    """Closing a device that has already vanished is the normal case
    here, not an error worth propagating out of shutdown."""
    class _AngryGPS(_StubGPS):
        def close(self):
            raise OSError("already gone")

    cache = GPSCache(_Factory(_AngryGPS()))
    cache.start()
    cache.stop(timeout_s=0.5)
