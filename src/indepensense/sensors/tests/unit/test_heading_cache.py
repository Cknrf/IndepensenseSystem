"""Unit tests for `App._check_heading` — the compass-heading cache.

Lives under `sensors/tests/unit/` rather than an app-level test package
because its subject is magnetometer consumption, and `app.py` has no test
package of its own (adding one would be a structural change).

`_check_heading` is the only thing in the runtime loop that touches the
magnetometer. Two properties matter enough to lock down:

- It is called at 100 Hz but must self-throttle to
  `HEADING_CHECK_INTERVAL_S`. Without the throttle it would hammer an I²C
  bus shared with the IMU, both ultrasonics and the UPS HAT.
- A magnetometer failure must never escape into the main loop. Heading is
  advisory; a fall detector that dies because the compass glitched would be
  a serious regression.

Hand-written fakes, no mocking library — matching the convention used
everywhere else in this repo.
"""
import pytest

from indepensense.app import App
from indepensense.config import HEADING_CHECK_INTERVAL_S
from indepensense.sensors.mock import MockMagnetometer


class _CountingMagnetometer(MockMagnetometer):
    """MockMagnetometer that records how many times `read()` was called."""

    def __init__(self, heading_deg: float = 0.0):
        super().__init__(heading_deg=heading_deg)
        self.read_count = 0

    def read(self):
        self.read_count += 1
        return super().read()


class _FailingMagnetometer:
    """Raises on every read — simulates a wedged I²C bus."""

    def read(self):
        raise OSError("simulated I2C failure")

    def close(self) -> None:
        pass


class _NoneMagnetometer:
    """Returns None on every read — simulates the QMC5883P overflow (STATUS.OVFL) path."""

    def read(self):
        return None

    def close(self) -> None:
        pass


def _app_with(magnetometer) -> App:
    """An App with only the magnetometer wired. No hardware is opened."""
    app = App()
    app.magnetometer = magnetometer
    return app


def _expire_throttle(app: App) -> None:
    """Rewind the throttle clock so the next check reads, without sleeping."""
    app._last_heading_check -= HEADING_CHECK_INTERVAL_S


def test_no_magnetometer_is_a_safe_noop():
    app = _app_with(None)
    app._check_heading()
    assert app.latest_heading() is None


def test_successful_read_caches_heading():
    mag = _CountingMagnetometer(heading_deg=137.0)
    app = _app_with(mag)

    app._check_heading()

    assert app.latest_heading() == pytest.approx(137.0)
    assert mag.read_count == 1


def test_second_call_within_interval_is_throttled():
    mag = _CountingMagnetometer(heading_deg=10.0)
    app = _app_with(mag)
    app._check_heading()

    mag.set_heading(200.0)
    app._check_heading()   # immediately after — must not touch the bus

    assert mag.read_count == 1
    assert app.latest_heading() == pytest.approx(10.0)


def test_read_happens_again_once_the_interval_elapses():
    mag = _CountingMagnetometer(heading_deg=10.0)
    app = _app_with(mag)
    app._check_heading()

    mag.set_heading(200.0)
    _expire_throttle(app)
    app._check_heading()

    assert mag.read_count == 2
    assert app.latest_heading() == pytest.approx(200.0)


def test_raising_read_does_not_propagate_and_keeps_last_value():
    app = _app_with(_CountingMagnetometer(heading_deg=42.0))
    app._check_heading()

    app.magnetometer = _FailingMagnetometer()
    _expire_throttle(app)
    app._check_heading()   # must not raise

    assert app.latest_heading() == pytest.approx(42.0)


def test_none_read_keeps_last_value():
    app = _app_with(_CountingMagnetometer(heading_deg=42.0))
    app._check_heading()

    app.magnetometer = _NoneMagnetometer()
    _expire_throttle(app)
    app._check_heading()

    assert app.latest_heading() == pytest.approx(42.0)


def test_heading_is_none_before_the_first_successful_read():
    app = _app_with(_NoneMagnetometer())
    app._check_heading()
    assert app.latest_heading() is None
