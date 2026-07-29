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
  the monitor gets stuck on that instruction. The user can voice
  "cancel navigation" to reset.

Both are acceptable for a thesis MVP; recovering from route deviation
is a future-work bullet.
"""
import math
from dataclasses import dataclass

from indepensense.routing.base import Coordinate, Route


# Thresholds — imported by app.py via config; also inlined here as
# defaults so the monitor can be constructed without app-level config.
_DEFAULT_ANNOUNCE_M = 100.0
_DEFAULT_HAPTIC_M = 20.0
_DEFAULT_ADVANCE_M = 5.0


@dataclass(frozen=True)
class NavigationCue:
    """One action the monitor wants the application to perform.

    `kind` is one of:
      - "announce" — speak `text` through TTS.
      - "haptic"   — pulse the motor identified by `direction`.
      - "arrive"   — final destination reached. `text` gives the spoken
                     confirmation; app should also fire the arrival
                     haptic (all motors) and clear active-navigation state.
    """
    kind: str
    text: str | None = None
    direction: str | None = None


def _haversine_m(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance in metres between two lat/lon points.

    Standard haversine formula. Accurate to <1 m at walking scales; the
    Earth's ellipsoidal shape only matters for kilometre-scale routing
    and we're operating at sub-100 m thresholds.
    """
    r_earth_m = 6_371_000.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    d_lat = math.radians(b.lat - a.lat)
    d_lon = math.radians(b.lon - a.lon)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2)
    return 2 * r_earth_m * math.asin(math.sqrt(h))


class NavigationMonitor:
    def __init__(
        self,
        announce_distance_m: float = _DEFAULT_ANNOUNCE_M,
        haptic_distance_m: float = _DEFAULT_HAPTIC_M,
        advance_distance_m: float = _DEFAULT_ADVANCE_M,
    ):
        self._announce_distance_m = announce_distance_m
        self._haptic_distance_m = haptic_distance_m
        self._advance_distance_m = advance_distance_m

        self._route: Route | None = None
        self._destination_name: str = ""
        # Cursor into `route.instructions`. Points to the NEXT instruction
        # whose action has not yet fired.
        self._current_index: int = 0
        # Per-instruction latches so each cue fires exactly once.
        self._announced: set[int] = set()
        self._haptic_fired: set[int] = set()

    # ------------------------------------------------------------------ API

    def set_route(self, route: Route, destination_name: str) -> None:
        """Start tracking a new route. Overwrites any prior state."""
        self._route = route
        self._destination_name = destination_name
        self._current_index = self._initial_index(route)
        self._announced.clear()
        self._haptic_fired.clear()

    def clear(self) -> None:
        """Stop tracking. Subsequent `check()` calls return no cues."""
        self._route = None
        self._destination_name = ""
        self._current_index = 0
        self._announced.clear()
        self._haptic_fired.clear()

    def is_active(self) -> bool:
        return self._route is not None

    def current_index(self) -> int:
        """The next instruction index we're waiting to advance past."""
        return self._current_index

    def check(self, position: Coordinate) -> list[NavigationCue]:
        """Given the user's current position, return cues to fire.

        Multiple cues can fire in one call — e.g. if the user is within
        both the announce AND the haptic threshold on first check, both
        return. Advances through multiple instructions if the user is
        very close to several in a row (rare, but possible on short
        routes).
        """
        if self._route is None:
            return []

        cues: list[NavigationCue] = []
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

            distance = _haversine_m(position, instr.location)

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
                # For arrive, emit the arrival cue (if not already
                # emitted via announce) and stop tracking.
                if instr.direction == "arrive":
                    # Only add arrive cue if we haven't already
                    # announced (the announce for arrive already fired
                    # the spoken confirmation).
                    if self._current_index not in self._announced:
                        cues.append(self._build_announce_cue(instr, distance))
                    self.clear()
                    return cues
                self._current_index += 1
                continue

            # Not yet at the turn — nothing more to do this tick.
            break

        return cues

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
        """Build the spoken text for an approaching instruction."""
        if instr.direction == "arrive":
            return NavigationCue(
                kind="arrive",
                text=f"You have arrived at {self._destination_name}.",
            )
        # Round distance to a friendlier number for speech.
        rounded = _round_speech_distance(distance)
        return NavigationCue(
            kind="announce",
            text=f"In {rounded} meters, {instr.text}.",
        )


def _round_speech_distance(m: float) -> int:
    """Round a distance to a value pleasant for speech synthesis.

    "In 87 meters, turn left" sounds robotic. "In 90 meters..." sounds
    natural. Rounds up to the nearest 10 m for distances under 100 m,
    nearest 50 m up to 500 m, nearest 100 m beyond. Never returns 0.
    """
    if m < 100:
        return max(10, int(round(m / 10) * 10))
    if m < 500:
        return int(round(m / 50) * 50)
    return int(round(m / 100) * 100)
