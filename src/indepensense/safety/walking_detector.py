"""Still / walking classification from the chest-mounted IMU.

Obstacle warnings fire when an obstacle gets *closer*, never while it
merely stays put — that is what stopped a wall in front of a standing
user from buzzing forever. The gap it left: a user who stands still in
front of something, then sets off towards it, was told nothing, because
the distance had not changed yet. The cane is a poor witness to that
moment (it is swept and wobbled whether or not the user moves), but the
IMU is on the vest, so it moves only when the body does.

Method: the standard deviation of total acceleration magnitude over a
short rolling window. Walking bounces the torso once per step, which
shows up as a large spread; standing, even fidgeting, barely moves it.
Magnitude rather than any one axis for the same reason the fall detector
uses it — the mounting angle drops out, so nothing needs calibrating.

The classifier is deliberately lopsided:

  - **still → walking is immediate**, on the first window above the
    threshold. Calling a user still while they are moving is the
    dangerous mistake — it suppresses the re-alert this exists for.
  - **walking → still needs `still_hold_s` of quiet.** A pause between
    steps, or the slow phase of a stride, must not count as stopping,
    or every resumed step would re-alert.

A stationary user misclassified as walking costs a few extra reminders;
the reverse costs a missed warning. Thresholds lean towards the first.
"""
from collections import deque

from indepensense.safety.fall_detector import magnitude_g, stddev
from indepensense.sensors.base import IMUReading


class WalkingDetector:
    def __init__(
        self,
        window_s: float,
        motion_stddev_g: float,
        still_hold_s: float,
    ) -> None:
        self._window_s = window_s
        self._motion_stddev_g = motion_stddev_g
        self._still_hold_s = still_hold_s

        self._samples: deque[tuple[float, float]] = deque()
        # Starts as walking: until a full window says otherwise, assume
        # the user may be moving, so nothing is suppressed at boot.
        self._walking = True
        # When the current unbroken run of quiet windows began; None while
        # the user is moving.
        self._quiet_since: float | None = None

    @property
    def walking(self) -> bool:
        return self._walking

    def process(self, reading: IMUReading) -> bool:
        """Feed one IMU sample. Returns True only on the sample where the
        user goes from still to walking — the moment worth acting on."""
        now = reading.timestamp
        # Readings are stamped with wall-clock time, which NTP can step
        # backwards after boot. A window holding "future" samples would
        # never prune and never fill, so start it over instead.
        if self._samples and now < self._samples[-1][0]:
            self._samples.clear()
            self._quiet_since = None
        self._samples.append((now, magnitude_g(reading)))
        while self._samples and now - self._samples[0][0] > self._window_s:
            self._samples.popleft()

        # A window that does not yet span most of its length is too short
        # to tell a step from a twitch. Hold the current state until it does.
        if now - self._samples[0][0] < self._window_s * 0.8:
            return False

        if stddev([mag for _, mag in self._samples]) >= self._motion_stddev_g:
            self._quiet_since = None
            if not self._walking:
                self._walking = True
                return True
            return False

        if self._quiet_since is None:
            self._quiet_since = now
        if self._walking and now - self._quiet_since >= self._still_hold_s:
            self._walking = False
        return False
