"""Turning the user to face the right way before they start walking.

GraphHopper's first instruction is "Head north on Rizal Street". A user
who cannot see has no way to act on that, and everything downstream —
every turn cue, the off-route detector, the arrival check — assumes they
set off in roughly the right direction. This is the step that makes that
assumption true.

Pure decision logic: given how far off the user's facing is, say which way
to turn and how urgently. No threads, no hardware, no speech. The
application layer reads the compass, fires the motor, and calls back.

Why haptic rate-coding
----------------------

The feedback is a motor pulsing on the side to turn toward, faster as the
error shrinks, rather than a spoken angle. Three reasons, in order of
weight:

  * A spoken "turn right about ninety degrees" is ~2 s of Piper, so the
    feedback lags the movement it is describing and the user is already
    past it. Pulses track the turn continuously.
  * It survives traffic. This is used standing on a street corner.
  * It asks nothing of the user but "turn until the buzzing speeds up,
    then stop" — no counting, no arithmetic, no memory of what was said.

Hysteresis
----------

Once aligned, `aligned_tolerance_deg` widens to `release_tolerance_deg`.
Without that, a user who overshoots by a degree past the boundary gets
told to turn back, overshoots the other way, and oscillates — the device
nagging at somebody who is, to any practical purpose, pointing the right
way. Alignment is sticky on purpose.
"""
import math
from dataclasses import dataclass

# Error bands, in degrees, and the pulse interval each maps to. Ordered
# widest-first; the first band the error falls inside wins.
#
# The values are a starting point, not a finding — whether 800 ms reads as
# "slower" than 400 ms to somebody wearing this is a question only a person
# in a corridor can answer. They live in `config.py` for exactly that
# reason; these defaults exist so the module can be constructed and tested
# without app-level config.
_DEFAULT_BANDS: tuple[tuple[float, float], ...] = (
    (90.0, 0.8),      # more than 90° out: keep turning, no hurry
    (30.0, 0.4),      # getting closer
    (0.0, 0.2),       # nearly there — urgency is the signal to slow down
)

_DEFAULT_ALIGNED_TOLERANCE_DEG = 15.0
_DEFAULT_RELEASE_TOLERANCE_DEG = 30.0


@dataclass(frozen=True)
class OrientationCue:
    """What to do about the user's current facing.

    `aligned` true means stop turning and walk. Otherwise `direction` is
    "left" or "right" — the shorter way round — and `pulse_interval_s` is
    how long to wait before pulsing again.
    """
    aligned: bool
    direction: str | None = None
    pulse_interval_s: float | None = None


def heading_error(current_deg: float, target_deg: float) -> float:
    """Signed degrees to turn, in [-180, 180). Negative is left.

    Wrapping through this range is what makes the guidance take the short
    way round. Facing 350° and needing 10° is a 20° turn to the right, not
    340° to the left — and a user told to turn 340° would simply stop
    trusting the device.

    The half-open range resolves the exact-opposite case deterministically:
    180° out becomes -180, i.e. turn left. Either direction is equally
    right; picking one and staying with it stops the cue flickering between
    them on a degree of sensor noise.
    """
    return (target_deg - current_deg + 180.0) % 360.0 - 180.0


class OrientationGuide:
    """Tracks one turn-to-face attempt, including its alignment latch.

    Stateful only in the sticky sense: it remembers whether the user has
    reached alignment, so the tolerance can widen once they have. Construct
    one per attempt.
    """

    def __init__(
        self,
        aligned_tolerance_deg: float = _DEFAULT_ALIGNED_TOLERANCE_DEG,
        release_tolerance_deg: float = _DEFAULT_RELEASE_TOLERANCE_DEG,
        bands: tuple[tuple[float, float], ...] = _DEFAULT_BANDS,
    ):
        if release_tolerance_deg < aligned_tolerance_deg:
            raise ValueError(
                f"release tolerance {release_tolerance_deg}° is tighter than "
                f"the aligned tolerance {aligned_tolerance_deg}° — hysteresis "
                f"needs the band to widen once aligned, not narrow"
            )
        self._aligned_tolerance = aligned_tolerance_deg
        self._release_tolerance = release_tolerance_deg
        self._bands = bands
        self._has_aligned = False

    @property
    def has_aligned(self) -> bool:
        return self._has_aligned

    def cue(self, current_deg: float, target_deg: float) -> OrientationCue:
        """Decide what to do about the user's current facing."""
        error = heading_error(current_deg, target_deg)
        magnitude = abs(error)

        tolerance = (
            self._release_tolerance if self._has_aligned
            else self._aligned_tolerance
        )
        if magnitude <= tolerance:
            self._has_aligned = True
            return OrientationCue(aligned=True)

        direction = "right" if error > 0 else "left"
        return OrientationCue(
            aligned=False,
            direction=direction,
            pulse_interval_s=self._interval_for(magnitude),
        )

    def _interval_for(self, magnitude: float) -> float:
        for lower_bound, interval in self._bands:
            if magnitude > lower_bound:
                return interval
        # Below every band's lower bound but outside tolerance — use the
        # most urgent interval rather than failing, since this only happens
        # when the bands and the tolerance disagree about the fine end.
        return self._bands[-1][1]


def first_meaningful_point(points, origin, minimum_distance_m: float):
    """The first route point far enough away to give a stable bearing.

    A point two metres ahead produces a bearing that swings wildly with GPS
    jitter, and a device acting on it would spin the user on the spot. The
    destination is no good either — it may lie through a building. So this
    walks the polyline for the first point that is genuinely down the road.

    Falls back to the last point when every one of them is closer than the
    threshold, which means the whole route is shorter than the threshold
    and any bearing is about as good as any other. Returns None for an
    empty polyline.

    `origin` and the points are `routing.base.Coordinate`; the distance
    function is imported here rather than passed to keep the call sites
    plain.
    """
    from indepensense.routing.base import haversine_m

    if not points:
        return None
    for point in points:
        if haversine_m(origin, point) >= minimum_distance_m:
            return point
    return points[-1]
