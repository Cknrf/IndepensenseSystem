"""Turn-by-turn navigation progress monitor.

Given a `Route` and successive GPS positions, decides when to speak the
next turn instruction and when to fire directional haptics. Pure logic —
no threads, no network, no hardware access. The application layer is
responsible for calling `check()` periodically with the latest GPS fix
and acting on the returned cues.

Design
------

Three thresholds gate the cues per instruction:

  - `NAV_ANNOUNCE_DISTANCE_M` (100 m) — speak the instruction once. The
    text includes the current remaining distance so the user hears
    "In 87 meters, turn left onto Main Street", not a bare "turn left".
  - `NAV_HAPTIC_DISTANCE_M` (20 m) — pulse the direction-matching motor
    once. Left turn → left motor. Right → right. Straight → front. This
    is a silent cue the user can feel through the cane even in noisy
    environments where the announce speech might be missed.
  - `NAV_ADVANCE_DISTANCE_M` (5 m) — advance the internal cursor to the
    next instruction. We assume the user has taken the turn once they
    get within 5 m of it.

Both announce and haptic latch — each instruction only fires each cue
once, so a user lingering at a turn doesn't get spam.

Assumptions and known limitations
---------------------------------

- The user is following the route. We do not detect off-route deviation.
- We do NOT try to identify "past the turn" from a distance increase;
  that's fragile with GPS jitter. Advancement is strictly on proximity.
- If the user never gets within 5 m of a turn (GPS bias, wide turn),
  the monitor gets stuck on that instruction and its remaining turns
  go unspoken. The user can voice "cancel navigation" to reset.
  Arrival is deliberately exempt: it is checked against the
  destination directly, not through the cursor, so a missed turn
  still ends with "you have arrived".

Both are acceptable for a thesis MVP; recovering from route deviation
is a future-work bullet.
"""
import math
import time
from dataclasses import dataclass

from indepensense.intents.messages import round_speech_distance
from indepensense.routing.base import Coordinate, Route, haversine_m


# Thresholds — imported by app.py via config; also inlined here as
# defaults so the monitor can be constructed without app-level config.
_DEFAULT_ANNOUNCE_M = 100.0
_DEFAULT_HAPTIC_M = 20.0
_DEFAULT_ADVANCE_M = 5.0

# Off-route detection defaults. Chosen so that a legitimate GPS jitter
# (~5-10 m occasional spike) doesn't false-positive: we require 30 m
# sustained deviation for 15 seconds before speaking a warning. When
# the user gets back within 15 m of the route the latch clears, so a
# second deviation later will warn again.
_DEFAULT_OFF_ROUTE_DISTANCE_M = 30.0
_DEFAULT_ON_ROUTE_RECOVERY_M = 15.0
_DEFAULT_OFF_ROUTE_DURATION_S = 15.0


@dataclass(frozen=True)
class NavigationCue:
    """One action the monitor wants the application to perform.

    `kind` is one of:
      - "announce"  — speak `text` through TTS.
      - "haptic"    — pulse the motor identified by `direction`.
      - "arrive"    — final destination reached. `text` gives the spoken
                      confirmation; app should also fire the arrival
                      haptic (all motors) and clear active-navigation state.
      - "off_route" — user has deviated substantially from the planned
                      route. `text` gives a spoken warning; the wearable
                      does NOT auto-reroute. Fires once per deviation
                      event (latched until user gets back on route).
    """
    kind: str
    text: str | None = None
    direction: str | None = None


def _project_onto_segment(
    p: Coordinate, a: Coordinate, b: Coordinate,
) -> tuple[float, float]:
    """Distance from p to segment [a, b], and how far along it the foot lies.

    Returns `(distance_m, t)` where `t` is 0 at `a` and 1 at `b`, clamped
    to the segment. Off-route detection needs only the distance; remaining
    -distance needs `t` as well, to know how much of this segment is still
    ahead of the user.

    Uses a local flat-earth (ENU) approximation centred at `a`. Accurate
    to well under 1 m at the tens-of-metres scale we care about here.
    Handles the degenerate case where a == b (returns straight distance
    from p to a, with t = 0).
    """
    lat_scale_m_per_deg = 111_000.0
    lon_scale_m_per_deg = 111_000.0 * math.cos(math.radians(a.lat))

    # Vectors in local metres, relative to a.
    px = (p.lon - a.lon) * lon_scale_m_per_deg
    py = (p.lat - a.lat) * lat_scale_m_per_deg
    bx = (b.lon - a.lon) * lon_scale_m_per_deg
    by = (b.lat - a.lat) * lat_scale_m_per_deg

    seg_len_sq = bx * bx + by * by
    if seg_len_sq < 1e-9:
        # a and b coincide — segment collapses to a point.
        return math.hypot(px, py), 0.0

    # Project p onto the segment. `t` is the parameter along ab: 0=a, 1=b.
    t = (px * bx + py * by) / seg_len_sq
    t = max(0.0, min(1.0, t))     # clamp to [0, 1] so we stay on the segment

    # Nearest point on segment, minus p, is the perpendicular vector.
    nx = t * bx
    ny = t * by
    return math.hypot(px - nx, py - ny), t


def _distance_to_segment_m(p: Coordinate, a: Coordinate, b: Coordinate) -> float:
    """Perpendicular distance from point p to segment [a, b] in metres."""
    return _project_onto_segment(p, a, b)[0]


def _min_distance_to_polyline_m(pos: Coordinate, points: list[Coordinate]) -> float:
    """Shortest distance from `pos` to any point on the polyline.

    Iterates every segment. For a walking route with ~50-200 points,
    this is trivial CPU (microseconds) at 1 Hz check rate.
    """
    if not points:
        return float("inf")
    if len(points) == 1:
        return haversine_m(pos, points[0])

    best = float("inf")
    for i in range(len(points) - 1):
        d = _distance_to_segment_m(pos, points[i], points[i + 1])
        if d < best:
            best = d
    return best


class NavigationMonitor:
    def __init__(
        self,
        announce_distance_m: float = _DEFAULT_ANNOUNCE_M,
        haptic_distance_m: float = _DEFAULT_HAPTIC_M,
        advance_distance_m: float = _DEFAULT_ADVANCE_M,
        off_route_distance_m: float = _DEFAULT_OFF_ROUTE_DISTANCE_M,
        on_route_recovery_m: float = _DEFAULT_ON_ROUTE_RECOVERY_M,
        off_route_duration_s: float = _DEFAULT_OFF_ROUTE_DURATION_S,
    ):
        self._announce_distance_m = announce_distance_m
        self._haptic_distance_m = haptic_distance_m
        self._advance_distance_m = advance_distance_m
        self._off_route_distance_m = off_route_distance_m
        self._on_route_recovery_m = on_route_recovery_m
        self._off_route_duration_s = off_route_duration_s

        self._route: Route | None = None
        self._destination_name: str = ""
        # Cursor into `route.instructions`. Points to the NEXT instruction
        # whose action has not yet fired.
        self._current_index: int = 0
        # Per-instruction latches so each cue fires exactly once.
        self._announced: set[int] = set()
        self._haptic_fired: set[int] = set()

        # Off-route state:
        # - `_off_route_since`: monotonic timestamp of first-observed
        #   deviation, or None while on route. We only warn after the
        #   user has been off-route for `_off_route_duration_s` seconds
        #   to avoid false-positives from GPS jitter.
        # - `_off_route_warned`: True once the warning has been emitted;
        #   clears when the user returns within `_on_route_recovery_m`.
        self._off_route_since: float | None = None
        self._off_route_warned: bool = False

    # ------------------------------------------------------------------ API

    def set_route(self, route: Route, destination_name: str) -> None:
        """Start tracking a new route. Overwrites any prior state."""
        self._route = route
        self._destination_name = destination_name
        self._current_index = self._initial_index(route)
        self._announced.clear()
        self._haptic_fired.clear()
        self._off_route_since = None
        self._off_route_warned = False

    def clear(self) -> None:
        """Stop tracking. Subsequent `check()` calls return no cues."""
        self._route = None
        self._destination_name = ""
        self._current_index = 0
        self._announced.clear()
        self._haptic_fired.clear()
        self._off_route_since = None
        self._off_route_warned = False

    def is_active(self) -> bool:
        return self._route is not None

    def current_index(self) -> int:
        """The next instruction index we're waiting to advance past."""
        return self._current_index

    def destination_name(self) -> str:
        """Where this route ends, as the user named it. Empty if inactive."""
        return self._destination_name

    def remaining_distance_m(self, position: Coordinate) -> float | None:
        """Metres still to walk along the route. None if there is no route.

        Measured along the polyline, not as the crow flies. The difference
        is the whole value of the answer: a destination 200 m away in a
        straight line can be 500 m of walking around a block, and a user
        told the smaller number will believe they have arrived when they
        have not.

        The user is placed at the nearest point on the route, then the
        remainder of that segment plus every later segment is summed. That
        stays correct when they are off-route — it measures from where the
        route would have them be, which is the honest answer to "how much
        further" while they walk back to it.
        """
        if self._route is None:
            return None
        points = self._route.points
        if len(points) < 2:
            return None

        # Nearest segment, and how far along it the user has got.
        best_distance = float("inf")
        best_index = 0
        best_t = 0.0
        for i in range(len(points) - 1):
            distance, t = _project_onto_segment(position, points[i], points[i + 1])
            if distance < best_distance:
                best_distance, best_index, best_t = distance, i, t

        # What is left of the segment they are on, plus all the ones after.
        remaining = (1.0 - best_t) * haversine_m(
            points[best_index], points[best_index + 1]
        )
        for i in range(best_index + 1, len(points) - 1):
            remaining += haversine_m(points[i], points[i + 1])
        return remaining

    def check(
        self,
        position: Coordinate,
        now: float | None = None,
    ) -> list[NavigationCue]:
        """Given the user's current position, return cues to fire.

        Multiple cues can fire in one call — e.g. if the user is within
        both the announce AND the haptic threshold on first check, both
        return. Advances through multiple instructions if the user is
        very close to several in a row (rare, but possible on short
        routes).

        Also detects sustained deviation from the route polyline and
        emits an `off_route` cue once per deviation event. `now` is a
        monotonic timestamp; if omitted the wall clock is used
        (tests inject explicit values to make deviation timing
        deterministic).
        """
        if self._route is None:
            return []

        if now is None:
            now = time.monotonic()

        cues: list[NavigationCue] = []

        # Off-route detection runs alongside the turn-tracking below.
        # Kept as its own block for clarity; both consume `position`
        # but they don't otherwise interact.
        deviation_cue = self._check_off_route(position, now)
        if deviation_cue is not None:
            cues.append(deviation_cue)

        # Arrival is tested independently of the turn cursor, and before
        # it. The cursor only advances when the user passes within
        # `advance_distance_m` of each turn, so a turn missed to GPS bias
        # or a wide corner leaves it stuck — and a stuck cursor would
        # otherwise mean the user reaches their destination and is never
        # told. Arrival is the single cue they most need, so it must not
        # depend on turn-by-turn bookkeeping being perfect.
        arrival_cue = self._check_arrival(position)
        if arrival_cue is not None:
            cues.append(arrival_cue)
            self.clear()
            return cues

        # Loop so we can advance through consecutive instructions the
        # user is already past. `break` ends the loop as soon as we
        # find one we haven't reached yet.
        while self._current_index < len(self._route.instructions):
            instr = self._route.instructions[self._current_index]
            if instr.location is None:
                # Router didn't give us coordinates for this step —
                # skip forward and don't fire a cue.
                self._current_index += 1
                continue

            if instr.direction == "arrive":
                # Handled by `_check_arrival` above, which fires on
                # proximity to the destination rather than at the much
                # larger announce distance. Letting the announce branch
                # below see this instruction would say "you have arrived"
                # up to `announce_distance_m` (100 m) early.
                break

            distance = haversine_m(position, instr.location)

            # Announce (once) at the announce threshold.
            if (distance <= self._announce_distance_m
                    and self._current_index not in self._announced):
                self._announced.add(self._current_index)
                cues.append(self._build_announce_cue(instr, distance))

            # Haptic (once) at the haptic threshold. Skip for "arrive"
            # since the arrival cue is a different pattern (all motors).
            if (distance <= self._haptic_distance_m
                    and self._current_index not in self._haptic_fired
                    and instr.direction in ("left", "right", "straight")):
                self._haptic_fired.add(self._current_index)
                cues.append(NavigationCue(kind="haptic", direction=instr.direction))

            # Advance to next instruction if we're at the turn point.
            if distance <= self._advance_distance_m:
                self._current_index += 1
                continue

            # Not yet at the turn — nothing more to do this tick.
            break

        return cues

    def _check_arrival(self, position: Coordinate) -> NavigationCue | None:
        """Fire the arrival cue when within `advance_distance_m` of the
        destination, whatever the turn cursor is doing.

        Uses the advance threshold rather than the announce threshold so
        the confirmation lands where the user actually is, not 100 m out.
        Returns None when the route has no "arrive" instruction, or the
        router gave it no coordinates — in that degenerate case the
        monitor simply runs out of instructions and stays active until
        the user cancels.
        """
        destination = self._destination_instruction()
        if destination is None or destination.location is None:
            return None
        if haversine_m(position, destination.location) > self._advance_distance_m:
            return None
        return NavigationCue(
            kind="arrive",
            text=f"You have arrived at {self._destination_name}.",
        )

    def _destination_instruction(self):
        """The final "arrive" instruction, or None if the route has none."""
        if self._route is None:
            return None
        for instr in reversed(self._route.instructions):
            if instr.direction == "arrive":
                return instr
        return None

    def _check_off_route(
        self,
        position: Coordinate,
        now: float,
    ) -> NavigationCue | None:
        """Detect sustained deviation from the route polyline.

        Emits a spoken warning once per deviation event, then latches
        until the user gets back within `on_route_recovery_m`. The
        `off_route_duration_s` debounce filters GPS jitter — a single
        stray fix won't false-fire.
        """
        if self._route is None or not self._route.points:
            return None

        distance = _min_distance_to_polyline_m(position, self._route.points)

        # Recovery: user came back within the recovery threshold. Reset
        # both timers so a future deviation warns again.
        if distance <= self._on_route_recovery_m:
            self._off_route_since = None
            self._off_route_warned = False
            return None

        # Off-route: mark the first-observed deviation time. If it's
        # been sustained long enough AND we haven't already warned,
        # emit the warning.
        if distance > self._off_route_distance_m:
            if self._off_route_since is None:
                self._off_route_since = now
            elif (not self._off_route_warned
                  and now - self._off_route_since >= self._off_route_duration_s):
                self._off_route_warned = True
                return NavigationCue(
                    kind="off_route",
                    text=(
                        "You are off the planned route. You can continue "
                        "trying to reach the destination, or say cancel "
                        "navigation to stop."
                    ),
                )
            return None

        # Middle zone: between recovery and off-route thresholds.
        # Don't reset the deviation timer — this is a grace zone where
        # the user may still be drifting.
        return None

    # ---------------------------------------------------------------- helpers

    @staticmethod
    def _initial_index(route: Route) -> int:
        """Pick the starting instruction index.

        GraphHopper's first instruction is usually "Continue on X" (the
        user's current heading — not a turn). If we started tracking at
        index 0, we'd immediately announce/haptic at the user's own
        position. Skip past it if it's clearly a starter step.

        Falls back to 0 for degenerate routes with just one instruction
        (rare — implies "arrive" right at the origin).
        """
        if not route.instructions:
            return 0
        if len(route.instructions) == 1:
            return 0
        first = route.instructions[0]
        if first.direction == "straight":
            return 1
        return 0

    def _build_announce_cue(self, instr, distance: float) -> NavigationCue:
        """Build the spoken text for an approaching turn.

        Never called for the "arrive" instruction — `check()` breaks out
        of the loop before it, and `_check_arrival` builds that cue.
        """
        # Round distance to a friendlier number for speech.
        rounded = round_speech_distance(distance)
        return NavigationCue(
            kind="announce",
            text=f"In {rounded} meters, {instr.text}.",
        )


