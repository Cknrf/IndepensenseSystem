"""Unit tests for the three-phase fall detector.

Tests build synthetic IMU sample sequences (stationary / freefall / impact /
stillness) and feed them through the detector, verifying that only the full
sequence produces a FallEvent and that partial sequences don't.
"""
import random

from indepensense.safety.base import DetectorState, FallEvent
from indepensense.safety.fall_detector import ThresholdFallDetector
from indepensense.sensors.base import IMUReading


SAMPLE_HZ = 50


def _make_reading(t: float, ax: float, ay: float, az: float) -> IMUReading:
    return IMUReading(
        accel_x=ax, accel_y=ay, accel_z=az,
        gyro_x=0.0, gyro_y=0.0, gyro_z=0.0,
        temperature_c=25.0,
        timestamp=t,
    )


def _stationary(start_t: float, duration_s: float) -> list[IMUReading]:
    """Device sitting on a table: gravity on +Z with tiny sensor noise."""
    rng = random.Random(42)
    dt = 1.0 / SAMPLE_HZ
    n = int(duration_s * SAMPLE_HZ)
    return [
        _make_reading(
            start_t + i * dt,
            rng.gauss(0.0, 0.01),
            rng.gauss(0.0, 0.01),
            1.0 + rng.gauss(0.0, 0.01),
        )
        for i in range(n)
    ]


def _freefall(start_t: float, duration_s: float) -> list[IMUReading]:
    """Freefall: near-zero total magnitude."""
    dt = 1.0 / SAMPLE_HZ
    n = int(duration_s * SAMPLE_HZ)
    return [_make_reading(start_t + i * dt, 0.0, 0.0, 0.05) for i in range(n)]


def _impact(start_t: float, peak_g: float, duration_s: float = 0.06) -> list[IMUReading]:
    """A brief high-magnitude spike along +Z."""
    dt = 1.0 / SAMPLE_HZ
    n = max(int(duration_s * SAMPLE_HZ), 3)
    return [_make_reading(start_t + i * dt, 0.0, 0.0, peak_g) for i in range(n)]


def _still(start_t: float, duration_s: float, orientation_z: float = 1.0) -> list[IMUReading]:
    """Post-fall stillness. Orientation can differ from pre-fall (person on their side, etc.)."""
    rng = random.Random(7)
    dt = 1.0 / SAMPLE_HZ
    n = int(duration_s * SAMPLE_HZ)
    return [
        _make_reading(
            start_t + i * dt,
            rng.gauss(0.0, 0.008),
            rng.gauss(0.0, 0.008),
            orientation_z + rng.gauss(0.0, 0.008),
        )
        for i in range(n)
    ]


def _run(readings: list[IMUReading]) -> tuple[ThresholdFallDetector, list[FallEvent]]:
    detector = ThresholdFallDetector()
    events: list[FallEvent] = []
    for r in readings:
        result = detector.process(r)
        if result is not None:
            events.append(result)
    return detector, events


# --- scenario tests ----------------------------------------------------------

def test_stationary_device_produces_no_event():
    _, events = _run(_stationary(0.0, 5.0))
    assert events == []


def test_full_fall_sequence_produces_one_event():
    readings = (
        _stationary(0.0, 1.0)
        + _freefall(1.0, 0.25)
        + _impact(1.25, peak_g=4.5)
        + _still(1.35, 3.0, orientation_z=0.98)
    )
    detector, events = _run(readings)
    assert len(events) == 1
    event = events[0]
    assert event.freefall_duration_s >= 0.1
    assert event.impact_magnitude_g >= 4.0
    # After emitting the event, the detector returns to IDLE.
    assert detector.state is DetectorState.IDLE


def test_freefall_without_impact_does_not_trigger():
    """User drops the wearable onto a soft surface — freefall then just stillness, no spike."""
    readings = (
        _stationary(0.0, 1.0)
        + _freefall(1.0, 0.25)
        + _still(1.25, 3.0)
    )
    _, events = _run(readings)
    assert events == []


def test_impact_without_freefall_does_not_trigger():
    """User taps the wearable hard — spike without a preceding freefall."""
    readings = (
        _stationary(0.0, 1.0)
        + _impact(1.0, peak_g=4.5)
        + _still(1.1, 3.0)
    )
    _, events = _run(readings)
    assert events == []


def test_freefall_and_impact_but_no_stillness_does_not_trigger():
    """User falls but catches themselves — freefall + impact but keeps moving after."""
    # Post-impact behaviour is high-variance motion, so magnitudes must vary
    # too — not just axes. An earlier version of this test alternated the
    # sign of a single axis, which produced constant magnitude and the
    # detector correctly (but confusingly) reported stillness.
    dt = 1.0 / SAMPLE_HZ
    rng = random.Random(11)
    post_motion = [
        _make_reading(
            1.35 + i * dt,
            rng.uniform(-1.5, 1.5),
            rng.uniform(-1.5, 1.5),
            rng.uniform(-1.5, 1.5),
        )
        for i in range(int(3.0 * SAMPLE_HZ))
    ]
    readings = (
        _stationary(0.0, 1.0)
        + _freefall(1.0, 0.25)
        + _impact(1.25, peak_g=4.5)
        + post_motion
    )
    _, events = _run(readings)
    assert events == []


# --- state transition tests -------------------------------------------------

def test_state_progresses_through_expected_phases():
    """Verify the detector actually visits POST_FREEFALL and POST_IMPACT."""
    detector = ThresholdFallDetector()
    states_seen: list[DetectorState] = []

    for r in _stationary(0.0, 0.5):
        detector.process(r)
        states_seen.append(detector.state)
    assert DetectorState.IDLE in states_seen

    for r in _freefall(0.5, 0.25):
        detector.process(r)
    assert detector.state is DetectorState.POST_FREEFALL

    for r in _impact(0.75, peak_g=4.5):
        detector.process(r)
    assert detector.state is DetectorState.POST_IMPACT
