"""Unit tests for the still / walking classifier.

Synthetic chest traces: standing is gravity plus sensor noise; walking
adds a ~2 Hz vertical bounce of ±0.2 g, one cycle per step. The detector
is asserted on the two properties obstacle warnings rely on — it reports
setting off at once, and it does not report stopping until the quiet has
lasted — rather than on the exact threshold, which is still untuned.
"""
import math
import random

from indepensense.safety.walking_detector import WalkingDetector
from indepensense.sensors.base import IMUReading

SAMPLE_HZ = 100
DT = 1.0 / SAMPLE_HZ

WINDOW_S = 1.0
MOTION_STDDEV_G = 0.06
STILL_HOLD_S = 2.0


def _detector() -> WalkingDetector:
    return WalkingDetector(
        window_s=WINDOW_S,
        motion_stddev_g=MOTION_STDDEV_G,
        still_hold_s=STILL_HOLD_S,
    )


def _reading(t: float, az: float, rng: random.Random) -> IMUReading:
    return IMUReading(
        accel_x=rng.gauss(0.0, 0.01),
        accel_y=rng.gauss(0.0, 0.01),
        accel_z=az + rng.gauss(0.0, 0.01),
        gyro_x=0.0, gyro_y=0.0, gyro_z=0.0,
        temperature_c=25.0,
        timestamp=t,
    )


def _standing(start_t: float, duration_s: float, seed: int = 1) -> list[IMUReading]:
    rng = random.Random(seed)
    n = int(duration_s * SAMPLE_HZ)
    return [_reading(start_t + i * DT, 1.0, rng) for i in range(n)]


def _walking(start_t: float, duration_s: float, seed: int = 2) -> list[IMUReading]:
    rng = random.Random(seed)
    n = int(duration_s * SAMPLE_HZ)
    return [
        _reading(start_t + i * DT, 1.0 + 0.2 * math.sin(2 * math.pi * 2.0 * i * DT), rng)
        for i in range(n)
    ]


def _feed(detector: WalkingDetector, readings) -> list[float]:
    """Feed readings; return the timestamps where setting off was reported."""
    return [r.timestamp for r in readings if detector.process(r)]


def test_starts_as_walking():
    """Until a full window says otherwise, nothing should be suppressed."""
    assert _detector().walking is True


def test_standing_settles_to_still_after_the_hold():
    detector = _detector()
    _feed(detector, _standing(0.0, WINDOW_S + STILL_HOLD_S - 0.2))
    assert detector.walking is True, "declared still before the hold elapsed"

    _feed(detector, _standing(WINDOW_S + STILL_HOLD_S - 0.2, 0.5))
    assert detector.walking is False


def test_setting_off_is_reported_once_and_quickly():
    detector = _detector()
    _feed(detector, _standing(0.0, 5.0))
    assert detector.walking is False

    started = _feed(detector, _walking(5.0, 3.0))

    assert len(started) == 1, f"reported setting off {len(started)} times"
    assert started[0] - 5.0 < 0.5, f"took {started[0] - 5.0:.2f} s to notice"
    assert detector.walking is True


def test_continuous_walking_never_reports_setting_off():
    """Only a still → walking change is an event. A user who boots the
    device mid-walk has not "set off" — they were already going."""
    detector = _detector()
    assert _feed(detector, _walking(0.0, 10.0)) == []
    assert detector.walking is True


def test_a_pause_mid_walk_is_not_stopping():
    """Half a second of quiet between steps must not flip to still, or the
    next step would re-alert every obstacle in range."""
    detector = _detector()
    _feed(detector, _walking(0.0, 3.0))
    _feed(detector, _standing(3.0, 0.5))
    started = _feed(detector, _walking(3.5, 2.0))

    assert started == []
    assert detector.walking is True


def test_stopping_then_setting_off_again_reports_again():
    detector = _detector()
    _feed(detector, _walking(0.0, 3.0))
    _feed(detector, _standing(3.0, 5.0))
    assert detector.walking is False

    assert len(_feed(detector, _walking(8.0, 2.0))) == 1


def test_a_clock_stepped_backwards_does_not_freeze_the_window():
    """NTP can step wall-clock time back after boot. The detector must
    keep classifying rather than wait out the difference."""
    detector = _detector()
    _feed(detector, _standing(1000.0, 5.0))
    assert detector.walking is False

    started = _feed(detector, _walking(10.0, 2.0))

    assert len(started) == 1
