"""Types shared across the safety-decision layer.

The safety layer consumes sensor data and emits high-level events
(falls, SOS, etc.) that the guardian dashboard and on-device feedback layer
react to. Fall detection is the first module.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from indepensense.sensors.base import IMUReading


class DetectorState(Enum):
    """Public state of the fall-detection state machine.

    Exposed so tests can assert state transitions and a debug UI can render
    what phase the detector is currently in.
    """
    IDLE = "idle"                       # nothing suspicious
    POST_FREEFALL = "post_freefall"     # freefall confirmed, waiting for impact
    POST_IMPACT = "post_impact"         # impact confirmed, waiting for stillness


@dataclass(frozen=True)
class FallEvent:
    """A confirmed fall.

    Emitted when either detection route completes. `route` says which,
    because the two answer different questions and a wrong alert has to
    be attributable to the one that produced it:

      - `"freefall"` — weightless, then impact, then still. Catches a
        straight-down collapse.
      - `"posture"`  — impact, then the body ended up horizontal, then
        still. Catches a trip, which barely goes weightless at all
        because the torso swings rather than drops.

    `tilt_deg` is the orientation change across the event and is 0.0 on
    the freefall route, which never measures it.
    """
    timestamp: float              # local time when the fall was confirmed
    freefall_duration_s: float    # how long the freefall phase lasted
    impact_magnitude_g: float     # peak accel magnitude observed at impact
    route: str = "freefall"       # which route confirmed it
    tilt_deg: float = 0.0         # orientation change, posture route only


class FallDetector(Protocol):
    def process(self, reading: IMUReading) -> FallEvent | None:
        """Feed a single IMU sample.

        Returns a FallEvent only on the sample that completes a fall pattern
        (i.e. the last sample of the post-impact stillness window). Otherwise
        returns None.
        """

    @property
    def state(self) -> DetectorState:
        ...
