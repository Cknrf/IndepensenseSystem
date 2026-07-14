"""Threshold-based fall detector using the classic three-phase temporal pattern.

Phase 1 (freefall): |accel_mag| below `freefall_threshold_g` for at least
`freefall_min_duration_s`. During real freefall the accelerometer measures
near-zero magnitude because the sensor and the user fall together, so the
gravitational component briefly disappears.

Phase 2 (impact): |accel_mag| above `impact_threshold_g` within
`impact_window_s` after freefall ends. The body's collision with the ground
produces a sharp acceleration spike.

Phase 3 (stillness): stddev of magnitude below `stillness_max_stddev_g` for
`stillness_duration_s` seconds after the impact. A fallen person typically
lies still; someone who caught themselves keeps moving.

A `FallEvent` is emitted only when all three phases fire in sequence. Any
timeout in any phase resets the machine to IDLE — this is how the algorithm
rejects "just dropped the device" (only freefall + impact) and "sat down
hard" (only impact + stillness) as non-falls.
"""
import math
from collections import deque
from statistics import fmean

from indepensense.safety.base import DetectorState, FallEvent
from indepensense.sensors.base import IMUReading


def magnitude_g(reading: IMUReading) -> float:
    """Total accelerometer magnitude in g."""
    return math.sqrt(
        reading.accel_x**2 + reading.accel_y**2 + reading.accel_z**2
    )


def stddev(values: list[float] | deque[float]) -> float:
    """Sample standard deviation. Returns 0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = fmean(values)
    variance = sum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(variance)


class ThresholdFallDetector:
    def __init__(
        self,
        freefall_threshold_g: float = 0.5,
        freefall_min_duration_s: float = 0.1,
        impact_threshold_g: float = 2.0,
        impact_window_s: float = 0.5,
        stillness_max_stddev_g: float = 0.15,
        stillness_duration_s: float = 2.0,
        stillness_history_samples: int = 100,
        post_impact_timeout_s: float = 10.0,
    ):
        self._ff_threshold = freefall_threshold_g
        self._ff_min_duration = freefall_min_duration_s
        self._impact_threshold = impact_threshold_g
        self._impact_window = impact_window_s
        self._stillness_max_stddev = stillness_max_stddev_g
        self._stillness_duration = stillness_duration_s
        self._post_impact_timeout = post_impact_timeout_s

        self._state = DetectorState.IDLE
        self._ff_start_time: float | None = None
        self._ff_end_time: float | None = None
        self._ff_duration_s: float = 0.0
        self._impact_time: float | None = None
        self._impact_peak_g: float = 0.0
        self._stillness_start_time: float | None = None
        self._history: deque[float] = deque(maxlen=stillness_history_samples)

    @property
    def state(self) -> DetectorState:
        return self._state

    def process(self, reading: IMUReading) -> FallEvent | None:
        mag = magnitude_g(reading)
        now = reading.timestamp

        if self._state is DetectorState.IDLE:
            self._on_idle(mag, now)
            return None

        if self._state is DetectorState.POST_FREEFALL:
            self._on_post_freefall(mag, now)
            return None

        if self._state is DetectorState.POST_IMPACT:
            return self._on_post_impact(mag, now)

        return None

    def _on_idle(self, mag: float, now: float) -> None:
        if mag < self._ff_threshold:
            if self._ff_start_time is None:
                self._ff_start_time = now
            elif now - self._ff_start_time >= self._ff_min_duration:
                # Freefall confirmed; transition to POST_FREEFALL.
                self._ff_duration_s = now - self._ff_start_time
                self._ff_end_time = now
                self._state = DetectorState.POST_FREEFALL
        else:
            self._ff_start_time = None

    def _on_post_freefall(self, mag: float, now: float) -> None:
        if mag > self._impact_threshold:
            self._impact_time = now
            self._impact_peak_g = mag
            self._history.clear()
            self._stillness_start_time = None
            self._state = DetectorState.POST_IMPACT
        elif self._ff_end_time is not None and now - self._ff_end_time > self._impact_window:
            # Freefall without a follow-up impact. Not a fall.
            self._reset()

    def _on_post_impact(self, mag: float, now: float) -> FallEvent | None:
        self._impact_peak_g = max(self._impact_peak_g, mag)

        # Only accumulate samples that could plausibly be "settling" or "still"
        # motion. Samples still above the impact threshold are part of the
        # impact spike itself; including them would keep the rolling stddev
        # artificially high and delay stillness confirmation by however long
        # it takes the history window to flush them out.
        if mag <= self._impact_threshold:
            self._history.append(mag)

        # Need enough samples for a meaningful stddev.
        if len(self._history) >= 10:
            sd = stddev(self._history)
            if sd < self._stillness_max_stddev:
                if self._stillness_start_time is None:
                    self._stillness_start_time = now
                elif now - self._stillness_start_time >= self._stillness_duration:
                    event = FallEvent(
                        timestamp=now,
                        freefall_duration_s=self._ff_duration_s,
                        impact_magnitude_g=self._impact_peak_g,
                    )
                    self._reset()
                    return event
            else:
                # Motion resumed — restart the stillness window.
                self._stillness_start_time = None

        # Impact happened but stillness never confirmed. Reset.
        if self._impact_time is not None and now - self._impact_time > self._post_impact_timeout:
            self._reset()

        return None

    def _reset(self) -> None:
        self._state = DetectorState.IDLE
        self._ff_start_time = None
        self._ff_end_time = None
        self._ff_duration_s = 0.0
        self._impact_time = None
        self._impact_peak_g = 0.0
        self._stillness_start_time = None
        self._history.clear()
