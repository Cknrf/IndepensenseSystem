"""Turn-by-turn navigation progress monitor.

Given a `Route` and successive GPS positions, decides when to speak the
next turn instruction and when to say the direction on its own. Pure
logic — no threads, no network, no hardware access. The application is
responsible for calling `check()` periodically with the latest GPS fix
and acting on the returned cues.

Design
------

Three thresholds gate the cues per instruction:

  - `NAV_ANNOUNCE_DISTANCE_M` (100 m) — speak the instruction once. The
    text includes the current remaining distance so the user hears
    "In 87 meters, turn left onto Main Street", not a bare "turn left".
  - `NAV_TURN_NOW_DISTANCE_M` (20 m) — say the direction on its own,
    once: "turn left". The announce 80 m back carried the street name and
    a distance; this is the shortest thing that can be said at the moment
    the turn arrives, and short matters because the user is at a junction
    listening to traffic.
  - `NAV_ADVANCE_DISTANCE_M` (5 m) — how far *past* a turn, measured
    along the route, the cursor moves on to the next instruction.

Both announce and turn_now latch — each instruction only fires each cue
once, so a user lingering at a turn doesn't get spam.

Progress is measured along the route, not as a radius
-----------------------------------------------------

The cursor used to advance when the user came within 5 m of the turn
point in a straight line, which made the whole feature a hostage to GPS
cross-track error. Consumer GPS in a town is commonly off by more than
5 m, and the error is a *bias* that persists for as long as the sky view
does — so the user walks the corner correctly, their reported position
passes 7 m to one side of it, and the cursor never moves. Every later
turn then goes unspoken, with nothing to tell them: they are on the
route, so off-route detection stays quiet, and the only cue they get is
silence. Simulated against this monitor, a 2D error of σ=5 m stuck the
cursor on 61% of turns, which is 2% of four-turn routes completed.

What the user has actually done is covered by their position *along* the
route: `_along_route_m` drops the perpendicular component by projecting
onto the polyline, so a constant sideways bias of any size cancels. The
turn counts as taken once that projection has passed the turn point by
`advance_distance_m`.

Straight-line distance remains the fallback for a degenerate route whose
polyline has fewer than two points — there is nothing to project onto,
and proximity is the best that can be said.

The error that remains is along-*track*: a fix that jumps forward down
the route advances the cursor early. That is the cheaper failure — by
the time it can happen the announce and turn_now cues for that turn have
both been spoken, because they fire at 100 m and 20 m against the same
noisy position.

Turn verification
-----------------

Advancement cannot tell a turn taken from a corner walked straight past —
both put the user beyond the turn point — so after either, every later
cue is measured against a leg they may not be on. Off-route detection
catches it, but only after 30 m of sustained deviation: 15-30 s of
walking the wrong way.

When `check()` is given a `heading`, the monitor notes where the user
stood as they reached each left/right turn, waits until they have walked
`turn_verify_distance_m` from there, and compares their facing against
the bearing of the next leg — emitting `missed_turn` when the two do not
match. That is a much faster signal than position, because heading
changes at the corner while position takes tens of metres to diverge.

It is strictly additive: without a heading — which is the case whenever
the compass is uncalibrated — advancement, announces, turn cues and
arrival behave exactly as they did before it existed.

Assumptions and known limitations
---------------------------------

- The user is following the route. Off-route deviation is detected but
  not recovered from.
- Turn verification says a turn was missed; it cannot say what to do
  about it, because the wearable does not reroute. The user is told what
  the instruction was and decides.
- Projection onto the polyline takes the nearest segment, which is the
  wrong one on a route that doubles back along a street it has already
  used — the two legs overlap, and "nearest" cannot tell them apart.
  An out-and-back route can therefore read as further along than it is.
  Turn points are exempt, because the router numbers them
  (`RouteInstruction.point_index`); it is the *user's* position that is
  ambiguous.

Recovering from route deviation is a future-work bullet.
"""
import math
import time
from dataclasses import dataclass

from indepensense.intents.messages import round_speech_distance
from indepensense.navigation.orientation import heading_error
from indepensense.routing.base import (
    Coordinate,
    Route,
    RouteInstruction,
    bearing_to,
    haversine_m,
)


# Thresholds — imported by app.py via config; also inlined here as
# defaults so the monitor can be constructed without app-level config.
_DEFAULT_ANNOUNCE_M = 100.0
_DEFAULT_TURN_NOW_M = 20.0
_DEFAULT_ADVANCE_M = 5.0

# Arrival has its own, much larger radius, and does not share the advance
# threshold as it used to. The two answer different questions. Advancing
# the cursor early costs nothing — the cues for that turn have already
# been spoken — so 5 m of margin past the turn is plenty. Arrival is the
# one cue the user cannot do without, and it is checked against a single
# fixed point with no second chance: at 5 m, a GPS bias the user cannot
# see means they stand at their destination and are told nothing, while
# navigation runs on indefinitely.
#
# 15 m is the smallest radius that clears the error this receiver
# actually shows in town. It is deliberately an over-call: arriving 15 m
# early leaves the user a few steps short of a door they can find by
# other means, where never arriving leaves them stranded. It is not
# simply "say it sooner" — see `_check_arrival`, where the along-route
# remainder has to be inside the same radius, so a destination 15 m away
# in a straight line but around a corner still does not fire.
_DEFAULT_ARRIVAL_M = 15.0

# Off-route detection defaults. Chosen so that a legitimate GPS jitter
# (~5-10 m occasional spike) doesn't false-positive: we require 30 m
# sustained deviation for 15 seconds before speaking a warning. When
# the user gets back within 15 m of the route the latch clears, so a
# second deviation later will warn again.
_DEFAULT_OFF_ROUTE_DISTANCE_M = 30.0
_DEFAULT_ON_ROUTE_RECOVERY_M = 15.0
_DEFAULT_OFF_ROUTE_DURATION_S = 15.0

# Turn verification. After the cursor passes a turn, wait until the user has
# put this much distance between themselves and the turn point before
# comparing their heading against the next leg. Checking immediately would
# flag everybody, since nobody has pivoted by the time they reach the corner.
#
# This was a fixed 5 s delay, and a delay cannot express the thing that
# matters, which is whether the turn has been *walked*. The timer started
# when the cursor advanced, so the check landed `delay - advance/speed`
# seconds after the user reached the corner: +1.4 s at 1.4 m/s, 0.0 s at
# 1.0 m/s, and -3.3 s at 0.6 m/s — before they had got there at all. Cane
# users walk at 0.6-0.9 m/s, so the device told them they had missed a turn
# they were still approaching, and even a brisk walker had barely a second
# of margin for a pivot that takes two. Simulated against this monitor with
# perfect GPS and a correct turn, every speed at or below 1.0 m/s produced
# a false warning.
#
# Distance has no such dependency: whoever the walker is and however long
# they stand at the kerb waiting to cross, 10 m of walking is 10 m of
# walking, and by the end of it the turn has either happened or it has not.
#
# It is measured as displacement from where the user stood when they
# reached the turn, not as distance from the turn point itself. A GPS bias
# sits in both positions and cancels in the difference, where distance from
# a fixed point carries it in full — a user 12 m off to one side is already
# "12 m from the corner" before they get there.
_DEFAULT_TURN_VERIFY_DISTANCE_M = 10.0

# How far off the next leg's bearing counts as "did not turn". Deliberately
# generous: the question is whether a roughly-90° turn happened at all, not
# whether it was taken tidily, and heading measured while walking carries
# the sway of every stride. A tight threshold here would flag users who
# turned perfectly well but cut the corner wide.
_DEFAULT_TURN_VERIFY_TOLERANCE_DEG = 60.0

# Below this, the next instruction is too close for the bearing between the
# two to mean anything, so verification is skipped rather than guessed.
_DEFAULT_TURN_VERIFY_MIN_LEG_M = 15.0

# How near the turn point the user has to be for "they have reached the
# turn" to be believed, on top of their along-route progress having got
# there. Progress alone is not enough near a corner: once the cross-track
# bias exceeds the along-track distance still to run, the user's nearest
# point on the route is on the *next* leg, so their projection crosses the
# junction while they are still short of it. Arming there starts the
# displacement count early, and the heading is judged before they have
# reached the corner, let alone turned — the original bug in a new costume.
#
# A radius on its own would be no better: wide enough to admit a biased
# fix, it also admits an unbiased user 15 m short of the corner. It is the
# conjunction that is right, because the two fail in opposite directions.
#
# At 15 m, a sweep over this monitor detects every missed turn out to a
# 9 m bias and raises no false alarm at any bias or walking speed. The
# ceiling is lower than the radius because the two conditions close on
# each other: a large enough bias snaps the projection across the junction
# early, which advances the cursor off this instruction before the user is
# ever near enough to arm it. By 12 m nothing arms and the turn goes
# unverified.
#
# That is the right way to lose it. Off-route detection is still
# underneath, 15-30 s slower, and saying nothing is a great deal better
# than telling somebody who turned correctly that they did not — a warning
# the user cannot check is one they learn to ignore, including the
# true ones.
_DEFAULT_TURN_VERIFY_ARM_RADIUS_M = 15.0


@dataclass(frozen=True)
class NavigationCue:
    """One action the monitor wants the application to perform.

    `kind` is one of:
      - "announce"  — speak `text` through TTS.
      - "turn_now"  — speak `direction` on its own, at the turn.
      - "arrive"    — final destination reached. `text` gives the spoken
                      confirmation; app should also clear
                      active-navigation state.
      - "off_route" — user has deviated substantially from the planned
                      route. `text` gives a spoken warning; the wearable
                      does NOT auto-reroute. Fires once per deviation
                      event (latched until user gets back on route).
      - "missed_turn" — the compass says the user did not actually turn
                      where the route said to. `direction` is the turn
                      they should have made; `text` names it. Fires at
                      most once per instruction, and only when a heading
                      is supplied.
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
        turn_now_distance_m: float = _DEFAULT_TURN_NOW_M,
        advance_distance_m: float = _DEFAULT_ADVANCE_M,
        arrival_distance_m: float = _DEFAULT_ARRIVAL_M,
        off_route_distance_m: float = _DEFAULT_OFF_ROUTE_DISTANCE_M,
        on_route_recovery_m: float = _DEFAULT_ON_ROUTE_RECOVERY_M,
        off_route_duration_s: float = _DEFAULT_OFF_ROUTE_DURATION_S,
        turn_verify_distance_m: float = _DEFAULT_TURN_VERIFY_DISTANCE_M,
        turn_verify_tolerance_deg: float = _DEFAULT_TURN_VERIFY_TOLERANCE_DEG,
        turn_verify_min_leg_m: float = _DEFAULT_TURN_VERIFY_MIN_LEG_M,
        turn_verify_arm_radius_m: float = _DEFAULT_TURN_VERIFY_ARM_RADIUS_M,
    ):
        self._announce_distance_m = announce_distance_m
        self._turn_now_distance_m = turn_now_distance_m
        self._advance_distance_m = advance_distance_m
        self._arrival_distance_m = arrival_distance_m
        self._off_route_distance_m = off_route_distance_m
        self._on_route_recovery_m = on_route_recovery_m
        self._off_route_duration_s = off_route_duration_s
        self._turn_verify_distance_m = turn_verify_distance_m
        self._turn_verify_tolerance_deg = turn_verify_tolerance_deg
        self._turn_verify_min_leg_m = turn_verify_min_leg_m
        self._turn_verify_arm_radius_m = turn_verify_arm_radius_m

        self._route: Route | None = None
        self._destination_name: str = ""
        # Route geometry, measured once per route rather than per check.
        # `_segment_m[i]` is the length of points[i] -> points[i+1];
        # `_cumulative_m[i]` is the distance from the route start to
        # points[i]; `_instruction_along_m[i]` is the same for instruction
        # i's turn point, or None where the router gave it no location.
        self._segment_m: list[float] = []
        self._cumulative_m: list[float] = []
        self._instruction_along_m: list[float | None] = []
        # Cursor into `route.instructions`. Points to the NEXT instruction
        # whose action has not yet fired.
        self._current_index: int = 0
        # Per-instruction latches so each cue fires exactly once.
        self._announced: set[int] = set()
        self._turn_now_fired: set[int] = set()

        # Off-route state:
        # - `_off_route_since`: monotonic timestamp of first-observed
        #   deviation, or None while on route. We only warn after the
        #   user has been off-route for `_off_route_duration_s` seconds
        #   to avoid false-positives from GPS jitter.
        # - `_off_route_warned`: True once the warning has been emitted;
        #   clears when the user returns within `_on_route_recovery_m`.
        self._off_route_since: float | None = None
        self._off_route_warned: bool = False

        # Turn verification: set when the user reaches a left/right turn,
        # cleared once the check has run. Holds (instruction, expected
        # bearing after the turn, where the user stood when they got there).
        self._pending_turn: tuple[
            RouteInstruction, float, Coordinate
        ] | None = None
        # Which instructions have already been armed, so reaching a turn
        # arms it once. Without this, a user standing at the junction
        # re-arms on every tick and the reference position follows them,
        # so the displacement below never grows and no turn is ever judged.
        self._verify_armed: set[int] = set()

    # ------------------------------------------------------------------ API

    def set_route(self, route: Route, destination_name: str) -> None:
        """Start tracking a new route. Overwrites any prior state."""
        self._route = route
        self._destination_name = destination_name
        self._measure_route(route)
        self._current_index = self._initial_index(route)
        self._announced.clear()
        self._turn_now_fired.clear()
        self._off_route_since = None
        self._off_route_warned = False
        self._pending_turn = None
        self._verify_armed.clear()

    def clear(self) -> None:
        """Stop tracking. Subsequent `check()` calls return no cues."""
        self._route = None
        self._destination_name = ""
        self._segment_m = []
        self._cumulative_m = []
        self._instruction_along_m = []
        self._current_index = 0
        self._announced.clear()
        self._turn_now_fired.clear()
        self._off_route_since = None
        self._off_route_warned = False
        self._pending_turn = None
        self._verify_armed.clear()

    def is_active(self) -> bool:
        return self._route is not None

    def current_index(self) -> int:
        """The next instruction index we're waiting to advance past."""
        return self._current_index

    def route(self) -> Route | None:
        """The route being tracked, or None. Read-only by convention.

        Exposed for turn-to-face guidance, which needs the polyline to work
        out which way the user should be pointing before they set off.
        """
        return self._route

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
        along = self._along_route_m(position)
        if along is None:
            return None
        return max(0.0, self._cumulative_m[-1] - along)

    # ------------------------------------------------------- route geometry

    def _measure_route(self, route: Route) -> None:
        """Pre-compute segment and cumulative lengths for a new route.

        Done once here rather than inside `check()` because the polyline
        does not change while it is being walked, and `check()` runs on
        the main loop. The instruction distances come from the router's
        own point indices where it supplied them, and are otherwise
        recovered by projecting the turn point onto the polyline — which
        is exact for a turn point, since it *is* one of the points.
        """
        points = route.points
        self._segment_m = [
            haversine_m(points[i], points[i + 1]) for i in range(len(points) - 1)
        ]
        self._cumulative_m = [0.0]
        for length in self._segment_m:
            self._cumulative_m.append(self._cumulative_m[-1] + length)

        self._instruction_along_m = []
        for instr in route.instructions:
            self._instruction_along_m.append(self._instruction_distance(instr))

    def _instruction_distance(self, instr: RouteInstruction) -> float | None:
        """How far along the route this instruction's turn point sits."""
        index = instr.point_index
        if index is not None and 0 <= index < len(self._cumulative_m):
            return self._cumulative_m[index]
        if instr.location is None:
            return None
        return self._along_route_m(instr.location)

    def _along_route_m(self, position: Coordinate) -> float | None:
        """Distance from the route start to the point on the route nearest
        `position`. None when there is no route, or it has no segments.

        This is the measure the cursor advances on. Taking the nearest
        point on the polyline discards the perpendicular component of the
        fix, which is exactly the component a GPS bias puts there.
        """
        if self._route is None or not self._segment_m:
            return None

        points = self._route.points
        best_distance = float("inf")
        best_index = 0
        best_t = 0.0
        for i in range(len(points) - 1):
            distance, t = _project_onto_segment(position, points[i], points[i + 1])
            if distance < best_distance:
                best_distance, best_index, best_t = distance, i, t

        return self._cumulative_m[best_index] + best_t * self._segment_m[best_index]

    def check(
        self,
        position: Coordinate,
        now: float | None = None,
        heading: float | None = None,
    ) -> list[NavigationCue]:
        """Given the user's current position, return cues to fire.

        Multiple cues can fire in one call — e.g. if the user is within
        both the announce AND the turn_now threshold on first check, both
        return. Advances through multiple instructions if the user is
        very close to several in a row (rare, but possible on short
        routes).

        Also detects sustained deviation from the route polyline and
        emits an `off_route` cue once per deviation event. `now` is a
        monotonic timestamp; if omitted the wall clock is used
        (tests inject explicit values to make deviation timing
        deterministic).

        `heading` is the user's facing in degrees, or None when it is
        unknown or untrustworthy. Supplying it enables turn verification:
        having passed a turn, the monitor waits for it to be completed and
        then checks whether the user is actually pointing down the next
        leg, emitting `missed_turn` when they are not. Without it every
        other behaviour here is unchanged — the cursor still advances on
        proximity alone, exactly as before.
        """
        if self._route is None:
            return []

        if now is None:
            now = time.monotonic()

        cues: list[NavigationCue] = []

        # How far along the route the user has got. Measured once: the
        # cursor, the arrival test and the remaining distance all want it.
        along = self._along_route_m(position)

        # Did the last turn actually happen? Checked before the cursor
        # moves on, so a user who walked straight past a corner hears
        # about it rather than being cued for a leg they are not on.
        # Off-route detection is the backstop and takes 15-30 s longer.
        missed = self._check_pending_turn(position, heading)
        if missed is not None:
            cues.append(missed)

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
        arrival_cue = self._check_arrival(position, along)
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

            # Distance to this turn, along the route where the geometry
            # allows it and straight-line otherwise. Signed: it goes
            # negative once the user is past the turn, which is what the
            # advance threshold below reads.
            #
            # Every threshold in this loop reads the same measure, and
            # that matters as much as the measure itself. While the cursor
            # advanced on along-route progress and `turn_now` still fired
            # on a straight-line radius, a large cross-track error could
            # satisfy the first without ever satisfying the second: near a
            # corner the user's projection snaps onto the *next* leg while
            # they are still short of the junction, so the cursor moved on
            # from a turn whose "turn right" had never been spoken. One
            # measure makes that unrepresentable — the cue bands are
            # intervals on the same axis, and the user crosses all of them.
            turn_along = self._instruction_along_m[self._current_index]
            along_route = along is not None and turn_along is not None
            if along_route:
                distance = turn_along - along
            else:
                distance = haversine_m(position, instr.location)

            # Announce (once) at the announce threshold.
            if (distance <= self._announce_distance_m
                    and self._current_index not in self._announced):
                self._announced.add(self._current_index)
                cues.append(self._build_announce_cue(instr, distance))

            # Direction alone (once) at the turn_now threshold. Skip
            # for "arrive", which speaks its own confirmation.
            if (distance <= self._turn_now_distance_m
                    and self._current_index not in self._turn_now_fired
                    and instr.direction in ("left", "right", "straight")):
                self._turn_now_fired.add(self._current_index)
                cues.append(NavigationCue(kind="turn_now", direction=instr.direction))

            # Arm turn verification the moment the user reaches the turn —
            # separately from the cursor advancing, and before it.
            #
            # Arming used to live in the advance branch, which no longer
            # works now that advancing means along-route progress: a user
            # who carries straight on past a corner makes none. Their
            # projection pins to the junction and stays there, so the one
            # case verification exists to catch would be the one case that
            # never armed. Reaching the turn is the event that matters, and
            # both a turn taken and a turn missed share it.
            reached = (
                distance <= (0.0 if along_route else self._advance_distance_m)
                and haversine_m(position, instr.location)
                <= self._turn_verify_arm_radius_m
            )
            if (instr.direction in ("left", "right")
                    and self._current_index not in self._verify_armed
                    and reached):
                self._verify_armed.add(self._current_index)
                self._arm_turn_verification(instr, position)

            # Advance once the user is `advance_distance_m` past the turn.
            # "Past" is a negative distance on the along-route measure;
            # where only the straight-line one is available there is no
            # sign to read, and proximity is the best that can be said.
            advance_at = (
                -self._advance_distance_m if along_route
                else self._advance_distance_m
            )
            if distance <= advance_at:
                self._current_index += 1
                continue

            # Not yet at the turn — nothing more to do this tick.
            break

        return cues

    def _arm_turn_verification(self, instr, position: Coordinate) -> None:
        """Note that a turn has been reached, to be judged once walked.

        `position` is where the user stood at that moment, and is what the
        displacement in `_check_pending_turn` is measured from. Only left
        and right turns reach here — "straight" cannot be missed, and
        arrival is handled elsewhere.

        The bearing to aim at is the one from this turn to the *next*
        instruction, which is the direction the user should now be
        walking. Taken between instructions rather than along the polyline
        because that is the data already to hand; a leg shorter than
        `turn_verify_min_leg_m` gives a bearing too noisy to judge, so
        those are skipped rather than guessed at.
        """
        if instr.direction not in ("left", "right"):
            self._pending_turn = None
            return
        if instr.location is None or self._route is None:
            self._pending_turn = None
            return

        next_index = self._current_index + 1
        if next_index >= len(self._route.instructions):
            self._pending_turn = None
            return
        next_instr = self._route.instructions[next_index]
        if next_instr.location is None:
            self._pending_turn = None
            return

        leg_m = haversine_m(instr.location, next_instr.location)
        if leg_m < self._turn_verify_min_leg_m:
            self._pending_turn = None
            return

        expected = bearing_to(instr.location, next_instr.location)
        self._pending_turn = (instr, expected, position)

    def _check_pending_turn(
        self,
        position: Coordinate,
        heading: float | None,
    ) -> NavigationCue | None:
        """Compare the user's facing against the leg they should be on.

        Returns a `missed_turn` cue when the heading says they carried
        straight on, and None otherwise. Disarms once it judges, so this
        fires at most once per turn — a user who knows they missed it does
        not need telling twice.

        Judges only once the user is `turn_verify_distance_m` from the turn
        point, because nobody has pivoted by the time they reach the
        corner. Until then it holds: a user standing at the kerb waiting
        for traffic has not failed to turn, they have not finished
        arriving, and no amount of elapsed time changes that. A heading
        that is unavailable when the moment comes disarms without a verdict
        rather than guessing — an absent compass must not manufacture a
        warning.

        The measure is blind to *which way* the user went: walking back
        down the leg they came from also puts distance between them and
        the corner, and would be read as a missed turn. Off-route detection
        is the honest answer to that one, and the warning they would get
        here is not far wrong in the meantime.
        """
        if self._pending_turn is None:
            return None

        instr, expected, armed_from = self._pending_turn
        if haversine_m(position, armed_from) < self._turn_verify_distance_m:
            return None

        self._pending_turn = None
        if heading is None:
            return None

        error = abs(heading_error(heading, expected))
        if error <= self._turn_verify_tolerance_deg:
            return None

        return NavigationCue(
            kind="missed_turn",
            text=instr.text,
            direction=instr.direction,
        )

    def _check_arrival(
        self,
        position: Coordinate,
        along: float | None,
    ) -> NavigationCue | None:
        """Fire the arrival cue at the destination, whatever the cursor
        is doing.

        Two conditions, both against `arrival_distance_m`: the user is
        within that radius of the destination, AND the walking distance
        still ahead of them is inside it too.

        The radius alone would be too blunt at 15 m. A destination on the
        far side of a corner can sit 15 m away in a straight line and 80 m
        away on foot, and telling that user they have arrived sends them
        looking for a door that is round the block. The remainder is what
        distinguishes the two, and it is free — it comes from the same
        projection the cursor uses. Where there is no usable polyline to
        project onto, the radius stands alone, which is the best that can
        be said about a route with no geometry.

        Returns None when the route has no "arrive" instruction, or the
        router gave it no coordinates — in that degenerate case the
        monitor simply runs out of instructions and stays active until
        the user cancels.
        """
        destination = self._destination_instruction()
        if destination is None or destination.location is None:
            return None
        if haversine_m(position, destination.location) > self._arrival_distance_m:
            return None
        if along is not None:
            remaining = max(0.0, self._cumulative_m[-1] - along)
            if remaining > self._arrival_distance_m:
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
        index 0, we'd immediately announce at the user's own
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
        # Clamped because the distance is signed: a user already past the
        # turn would otherwise round to a negative. Unreachable in
        # practice — the announce latches at 100 m out, long before the
        # sign can flip — but "In -10 meters" is not a sentence the
        # wearable should be one arithmetic slip away from saying.
        rounded = round_speech_distance(max(0.0, distance))
        return NavigationCue(
            kind="announce",
            text=f"In {rounded} meters, {instr.text}.",
        )


