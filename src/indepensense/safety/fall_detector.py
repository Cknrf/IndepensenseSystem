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

Two routes, because freefall does not happen in a trip
------------------------------------------------------

The three phases above are the **freefall route**, and measurement on the
assembled vest showed it catches nothing but straight-down collapses.
Recorded forward, backward and sideways falls spent as little as 10 ms
below the freefall threshold against a 100 ms requirement: a torso-mounted
sensor in a trip swings about the feet like a falling tree rather than
dropping, so it never becomes weightless.

Loosening the gate cannot fix that, because the recordings also showed the
harmless activities score *higher* than real falls on every individual
signal:

    signal                falls        daily activities   separates?
    lowest |a|            0.12-0.38    0.07-0.95          no
    peak |a|              3.58-6.76    1.05-7.01          no
    peak rotation °/s      315-427       13-359           no
    posture change °         9-95         1-102           no

No single threshold exists. Two of them together do:

    peak |a| > 3.0 g  AND  posture change > 50°

Each covers the other's blind spot. Sitting down hard is *violent but
upright* (7.01 g, 13°) — the tilt gate rejects it. Lying down and bending
over are *horizontal but gentle* (2.15 g at 102°, 1.60 g at 75°) — the
impact gate rejects them. That pair is the **posture route**, and it
scored 3/3 falls and 7/7 activities on the recorded set.

Both routes run at once and either one firing is a fall. The freefall
route is kept because it covers a case the posture route cannot: a
collapse that ends up seated or slumped against a wall is weightless on
the way down but never horizontal at rest.

Orientation is measured against the body's own recent past
-----------------------------------------------------------

The posture route compares orientation shortly *before* the impact
against orientation once the body has settled — not against a learned
"upright". Gravity is a constant 1 g downward, so the direction of the
accelerometer vector at rest reads body angle directly, with no gyro
integration and no drift.

Comparing against the recent past rather than an absolute reference is
what keeps the gate honest for someone who was not upright to begin
with. A person already lying in bed who rolls over and knocks the vest
registers a large impact while horizontal; against a learned "upright"
that is a 90° change and a false alert, while against their own prior
orientation it is near zero and correctly ignored.
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


def _mean_vector(samples) -> tuple[float, float, float]:
    """Average of a sequence of (ax, ay, az) tuples.

    Averaging is what turns noisy motion samples into a usable gravity
    direction: individual readings during a fall are dominated by the
    fall itself, but the mean over a window of relative calm is gravity
    and nothing else.
    """
    n = len(samples)
    if not n:
        return (0.0, 0.0, 0.0)
    return (
        sum(s[0] for s in samples) / n,
        sum(s[1] for s in samples) / n,
        sum(s[2] for s in samples) / n,
    )


def angle_between_deg(a: tuple, b: tuple) -> float:
    """Angle in degrees between two acceleration vectors.

    With the device at rest both vectors point along gravity, so this is
    the change in body angle: ~0° means the same posture, ~90° means
    upright became horizontal.

    Returns 0.0 for a zero-length vector — that is a dead sensor, not a
    posture change, and `mpu6050.is_dead_block` already turns those into
    failed reads before they reach here.
    """
    na = math.sqrt(sum(v * v for v in a))
    nb = math.sqrt(sum(v * v for v in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    cos = sum(x * y for x, y in zip(a, b)) / (na * nb)
    return math.degrees(math.acos(max(-1.0, min(1.0, cos))))


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
        posture_impact_threshold_g: float = 3.0,
        posture_tilt_threshold_deg: float = 50.0,
        orientation_history_samples: int = 200,
        orientation_window_samples: int = 50,
    ):
        self._ff_threshold = freefall_threshold_g
        self._ff_min_duration = freefall_min_duration_s
        self._impact_threshold = impact_threshold_g
        self._impact_window = impact_window_s
        self._stillness_max_stddev = stillness_max_stddev_g
        self._stillness_duration = stillness_duration_s
        self._post_impact_timeout = post_impact_timeout_s
        self._posture_impact_threshold = posture_impact_threshold_g
        self._posture_tilt_threshold = posture_tilt_threshold_deg
        self._orientation_window = orientation_window_samples

        self._state = DetectorState.IDLE
        self._ff_start_time: float | None = None
        self._ff_end_time: float | None = None
        self._ff_duration_s: float = 0.0
        self._impact_time: float | None = None
        self._impact_peak_g: float = 0.0
        self._stillness_start_time: float | None = None
        self._history: deque[float] = deque(maxlen=stillness_history_samples)

        # Rolling window of recent acceleration vectors, long enough to
        # reach back past a whole fall. A trip takes up to ~1.5 s from
        # first stumble to impact, so at 100 Hz the default 200 samples
        # (2 s) still contains pre-fall posture at the moment of impact.
        self._recent: deque[tuple[float, float, float]] = deque(
            maxlen=orientation_history_samples
        )
        # Orientation captured from before the impact, and the vectors
        # accumulated while lying still afterwards. Compared once the
        # stillness window completes.
        self._pre_impact_orientation: tuple[float, float, float] | None = None
        self._settled: deque[tuple[float, float, float]] = deque(
            maxlen=orientation_history_samples
        )
        self._via_freefall = False

    @property
    def state(self) -> DetectorState:
        return self._state

    def process(self, reading: IMUReading) -> FallEvent | None:
        mag = magnitude_g(reading)
        now = reading.timestamp
        vector = (reading.accel_x, reading.accel_y, reading.accel_z)

        # Kept in every state so the buffer still holds pre-fall posture
        # when an impact arrives with no warning — which is the whole
        # point of the posture route.
        self._recent.append(vector)
        if self._state is DetectorState.POST_IMPACT:
            self._settled.append(vector)

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
            return

        self._ff_start_time = None

        # Posture route: a hard enough impact with no freefall before it.
        # Deliberately a higher bar than the freefall route's impact
        # threshold — with no weightless phase to corroborate it, the
        # impact is carrying more of the evidence, and the recordings put
        # everyday knocks (2.15 g getting into bed) below this while every
        # real fall cleared it.
        if mag > self._posture_impact_threshold:
            self._enter_post_impact(mag, now, via_freefall=False)

    def _on_post_freefall(self, mag: float, now: float) -> None:
        if mag > self._impact_threshold:
            self._enter_post_impact(mag, now, via_freefall=True)
        elif self._ff_end_time is not None and now - self._ff_end_time > self._impact_window:
            # Freefall without a follow-up impact. Not a fall.
            self._reset()

    def _enter_post_impact(self, mag: float, now: float, via_freefall: bool) -> None:
        """Both routes converge here: an impact happened, now confirm it.

        The pre-impact orientation is snapshotted from the *oldest* end
        of the rolling buffer rather than the most recent samples. The
        newest ones are the fall itself — tumbling, already part-way to
        horizontal — so averaging those would compare the middle of the
        fall against its end and report almost no change.
        """
        self._impact_time = now
        self._impact_peak_g = mag
        self._via_freefall = via_freefall
        self._history.clear()
        self._settled.clear()
        self._stillness_start_time = None
        self._pre_impact_orientation = (
            _mean_vector(list(self._recent)[: self._orientation_window])
            if len(self._recent) >= self._orientation_window
            else None
        )
        self._state = DetectorState.POST_IMPACT

    def tilt_since_impact(self) -> float:
        """Orientation change between pre-impact posture and now.

        0.0 when there is no pre-impact snapshot — which happens only in
        the first couple of seconds after startup, before the rolling
        buffer has filled. Zero fails the tilt gate, so the posture route
        stays shut during that window rather than deciding on a
        half-filled buffer.
        """
        if self._pre_impact_orientation is None or not self._settled:
            return 0.0
        recent_settled = list(self._settled)[-self._orientation_window:]
        return angle_between_deg(
            self._pre_impact_orientation, _mean_vector(recent_settled)
        )

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
                    return self._confirm(now)
            else:
                # Motion resumed — restart the stillness window.
                self._stillness_start_time = None

        # Impact happened but stillness never confirmed. Reset.
        if self._impact_time is not None and now - self._impact_time > self._post_impact_timeout:
            self._reset()

        return None

    def _confirm(self, now: float) -> FallEvent | None:
        """Impact happened and the body has been still. Was it a fall?

        The freefall route is already complete at this point — weightless,
        impact, stillness — so it fires without consulting orientation. A
        collapse that ends up slumped and seated is still a fall, and
        demanding horizontality would discard the one case this route
        exists to catch.

        The posture route has no weightless phase to lean on, so the
        orientation change is its second piece of evidence and it is
        required. Without it the route would fire on anything heavy and
        stationary: sitting down hard peaked at 7.01 g in testing and
        must not alert a guardian.
        """
        tilt = self.tilt_since_impact()

        if not self._via_freefall and tilt < self._posture_tilt_threshold:
            # Hard impact, went still, but the body never changed
            # orientation. Sitting down, not falling. Reset rather than
            # keep waiting — the evidence is in and it says no.
            self._reset()
            return None

        event = FallEvent(
            timestamp=now,
            freefall_duration_s=self._ff_duration_s,
            impact_magnitude_g=self._impact_peak_g,
            route="freefall" if self._via_freefall else "posture",
            tilt_deg=0.0 if self._via_freefall else tilt,
        )
        self._reset()
        return event

    def _reset(self) -> None:
        self._state = DetectorState.IDLE
        self._ff_start_time = None
        self._ff_end_time = None
        self._ff_duration_s = 0.0
        self._impact_time = None
        self._impact_peak_g = 0.0
        self._stillness_start_time = None
        self._history.clear()
        self._via_freefall = False
        self._pre_impact_orientation = None
        self._settled.clear()
        # `_recent` is deliberately NOT cleared. It is the body's rolling
        # posture history, not per-event state, and a second impact
        # moments after a reset still needs to know which way up the
        # wearer was before any of it started.
