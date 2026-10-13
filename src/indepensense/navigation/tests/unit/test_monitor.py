"""Unit tests for the NavigationMonitor.

Pure logic — no threads, no hardware. Tests exercise the state machine
by feeding synthetic GPS positions and asserting on the cues returned.
"""
import pytest

from indepensense.navigation.monitor import (
    NavigationCue,
    NavigationMonitor,
)
from indepensense.intents.messages import round_speech_distance
from indepensense.routing.base import Coordinate, Route, RouteInstruction, haversine_m


# Two coordinates ~150 m apart at walking scale (0.0013 degrees ~= 145 m
# of latitude near the equator).
_START = Coordinate(lat=14.0000, lon=121.0000)
_MIDPOINT = Coordinate(lat=14.0013, lon=121.0000)
_END = Coordinate(lat=14.0026, lon=121.0000)

# One degree of latitude is ~111 km everywhere; the test route runs due
# north, so this walks a position along it by a given number of metres.
# Negative goes back the way they came.
_M_PER_DEG_LAT = 111_000.0


def _metres_north_of(point: Coordinate, metres: float) -> Coordinate:
    return Coordinate(lat=point.lat + metres / _M_PER_DEG_LAT, lon=point.lon)


def _make_route() -> Route:
    return Route(
        distance_m=290.0,
        duration_s=210.0,
        instructions=[
            RouteInstruction(
                text="Head north on First Street",
                distance_m=145.0,
                street_name="First Street",
                location=_START,
                direction="straight",
            ),
            RouteInstruction(
                text="Turn left onto Second Avenue",
                distance_m=145.0,
                street_name="Second Avenue",
                location=_MIDPOINT,
                direction="left",
            ),
            RouteInstruction(
                text="Arrive at destination",
                distance_m=0.0,
                street_name=None,
                location=_END,
                direction="arrive",
            ),
        ],
        points=[_START, _MIDPOINT, _END],
    )


# --- lifecycle ---------------------------------------------------------------

def test_new_monitor_is_inactive():
    m = NavigationMonitor()
    assert m.is_active() is False
    assert m.check(_START) == []


def test_set_route_activates():
    m = NavigationMonitor()
    m.set_route(_make_route(), "Test Destination")
    assert m.is_active() is True


def test_clear_deactivates():
    m = NavigationMonitor()
    m.set_route(_make_route(), "Test Destination")
    m.clear()
    assert m.is_active() is False
    assert m.check(_START) == []


def test_initial_index_skips_first_straight():
    """The first "continue on X" instruction is the user's current
    heading, not a turn. Monitor should target the FIRST turn (index 1)
    at start."""
    m = NavigationMonitor()
    m.set_route(_make_route(), "Test")
    assert m.current_index() == 1


# --- announce cue ------------------------------------------------------------

def test_announce_fires_within_threshold():
    m = NavigationMonitor(announce_distance_m=100.0, turn_now_distance_m=20.0, advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")

    # Position 80m from midpoint — inside announce threshold.
    close_to_midpoint = Coordinate(lat=14.0006, lon=121.0000)  # ~78m from midpoint
    cues = m.check(close_to_midpoint)

    announce = [c for c in cues if c.kind == "announce"]
    assert len(announce) == 1
    # Data, not prose: the monitor does not know what language the user
    # is being spoken to in, and must not decide the wording.
    assert announce[0].direction == "left"
    assert announce[0].street_name == "Second Avenue"
    assert announce[0].distance_m == pytest.approx(78.0, abs=5.0)


def test_announce_does_not_repeat():
    """Two checks in a row at the same position should only announce once."""
    m = NavigationMonitor()
    m.set_route(_make_route(), "Test")

    close = Coordinate(lat=14.0006, lon=121.0000)
    cues1 = m.check(close)
    cues2 = m.check(close)

    announces1 = [c for c in cues1 if c.kind == "announce"]
    announces2 = [c for c in cues2 if c.kind == "announce"]
    assert len(announces1) == 1
    assert len(announces2) == 0


def test_announce_does_not_fire_outside_threshold():
    m = NavigationMonitor(announce_distance_m=50.0)
    m.set_route(_make_route(), "Test")

    # Position ~145m from midpoint — outside 50m announce threshold.
    far = Coordinate(lat=13.9996, lon=121.0000)  # ~189m from midpoint
    cues = m.check(far)
    assert cues == []


# --- turn_now cue --------------------------------------------------------------

def test_turn_now_fires_within_turn_now_threshold_with_direction():
    m = NavigationMonitor(announce_distance_m=100.0, turn_now_distance_m=20.0, advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")

    # Position ~15m south of midpoint — inside the 20 m turn_now threshold.
    very_close = Coordinate(lat=14.00117, lon=121.0000)  # ~14.5m from midpoint
    cues = m.check(very_close)

    turn_cues = [c for c in cues if c.kind == "turn_now"]
    assert len(turn_cues) == 1
    assert turn_cues[0].direction == "left"


def test_turn_now_does_not_repeat():
    m = NavigationMonitor()
    m.set_route(_make_route(), "Test")

    very_close = Coordinate(lat=14.00117, lon=121.0000)
    m.check(very_close)  # first call fires turn_now
    cues = m.check(very_close)  # second should not
    assert not any(c.kind == "turn_now" for c in cues)


# --- advancement -------------------------------------------------------------

def test_advance_once_past_the_turn():
    """The cursor moves on when the user's position *along the route* has
    passed the turn, not when they come within a radius of it."""
    m = NavigationMonitor(advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")
    assert m.current_index() == 1

    m.check(_metres_north_of(_MIDPOINT, 8.0))
    assert m.current_index() == 2   # advanced to "arrive"


def test_short_of_the_turn_does_not_advance():
    """Standing a few metres before a corner is not taking it. The old
    rule — within 5 m of the turn point — counted it as taken, which is
    also what let a sideways GPS bias skip the turn entirely."""
    m = NavigationMonitor(advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")

    m.check(_metres_north_of(_MIDPOINT, -3.0))

    assert m.current_index() == 1


def test_a_sideways_gps_bias_does_not_stick_the_cursor():
    """The failure this measure exists for. Consumer GPS in a town is
    commonly off by more than the 5 m the cursor used to need, and the
    error is a bias that lasts as long as the sky view does — so the user
    walks the corner correctly, their reported position passes to one
    side of it, and under the old rule every later turn went unspoken
    with nothing to tell them it had happened."""
    m = NavigationMonitor(advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")

    # 12 m east of the route, which runs due north: a pure cross-track
    # error, and never once inside the old 5 m radius of the turn.
    biased = _metres_north_of(_MIDPOINT, 8.0)
    m.check(Coordinate(lat=biased.lat, lon=biased.lon + 0.00011))

    assert m.current_index() == 2


def test_arrival_fires_arrive_cue_and_deactivates():
    """Arrival is checked against the destination directly, not through
    the turn cursor. Here the user is at the destination without ever
    having come within the advance threshold of the midpoint turn — a
    missed turn must not suppress the arrival cue."""
    m = NavigationMonitor()
    m.set_route(_make_route(), "Home")
    assert m.current_index() == 1   # cursor still on the midpoint turn

    cues = m.check(_END)

    assert any(c.kind == "arrive" for c in cues)
    assert m.is_active() is False


def test_no_arrive_cue_before_reaching_destination():
    """Arrival has its own radius (15 m), not the announce threshold
    (100 m). Guards against speaking "you have arrived" while the user is
    still most of a block away."""
    two_step = Route(
        distance_m=290.0,
        duration_s=210.0,
        instructions=[
            RouteInstruction("Head north", 290.0, None, location=_START, direction="straight"),
            RouteInstruction("Arrive", 0.0, None, location=_END, direction="arrive"),
        ],
        points=[_START, _END],
    )
    m = NavigationMonitor(announce_distance_m=100.0, advance_distance_m=5.0)
    m.set_route(two_step, "Home")
    assert m.current_index() == 1   # cursor sits on the arrive instruction

    # ~78 m short of the destination — inside announce range, well
    # outside the advance threshold.
    cues = m.check(Coordinate(lat=14.0019, lon=121.0000))

    assert not any(c.kind == "arrive" for c in cues)
    assert m.is_active() is True


def test_a_destination_that_is_near_but_not_yet_walkable_does_not_arrive():
    """The radius alone is too blunt once it is 15 m wide.

    This route loops: it runs 100 m east, steps 12 m north, and comes 100 m
    back west, so the destination ends up 12 m from where the user started
    and 212 m away on foot. A bare radius would congratulate them on
    arriving before they had taken a step. The along-route remainder is
    what tells the two apart, and it costs nothing — it falls out of the
    same projection the cursor already uses.
    """
    start = Coordinate(lat=14.0000, lon=121.0000)
    east = Coordinate(lat=14.0000, lon=121.000926)        # ~100 m east
    north = Coordinate(lat=14.000108, lon=121.000926)     # ~12 m north
    end = Coordinate(lat=14.000108, lon=121.0000)         # ~100 m back west
    loop = Route(
        distance_m=212.0,
        duration_s=160.0,
        instructions=[
            RouteInstruction("Head east", 100.0, None, location=start,
                             point_index=0, direction="straight"),
            RouteInstruction("Turn left", 12.0, None, location=east,
                             point_index=1, direction="left"),
            RouteInstruction("Turn left", 100.0, None, location=north,
                             point_index=2, direction="left"),
            RouteInstruction("Arrive", 0.0, None, location=end,
                             point_index=3, direction="arrive"),
        ],
        points=[start, east, north, end],
    )
    m = NavigationMonitor(arrival_distance_m=15.0)
    m.set_route(loop, "Home")

    # Standing at the start: 12 m from the destination, 212 m of walking.
    cues = m.check(start)

    assert not any(c.kind == "arrive" for c in cues)
    assert m.is_active() is True

    # Having actually walked it, the same radius now means arrival.
    assert any(c.kind == "arrive" for c in m.check(end))


def test_arrive_cue_names_destination():
    m = NavigationMonitor(announce_distance_m=1000.0)  # generous so first check announces
    m.set_route(_make_route(), "Home")

    cues = m.check(_END)
    arrive_cues = [c for c in cues if c.kind == "arrive"]
    assert len(arrive_cues) >= 1
    # Carried on the cue rather than read back off the monitor, which
    # clears the route in the same breath as emitting this.
    assert arrive_cues[0].destination == "Home"


# --- direction mapping guard ------------------------------------------------

def test_turn_now_direction_matches_instruction():
    """Haptic cue's direction field must match the instruction's."""
    right_route = Route(
        distance_m=145.0,
        duration_s=100.0,
        instructions=[
            RouteInstruction("Start", 145.0, None, location=_START, direction="straight"),
            RouteInstruction("Turn right", 0.0, None, location=_MIDPOINT, direction="right"),
        ],
        points=[_START, _MIDPOINT],
    )
    m = NavigationMonitor()
    m.set_route(right_route, "Test")

    very_close = Coordinate(lat=14.00117, lon=121.0000)
    cues = m.check(very_close)
    turn_cues = [c for c in cues if c.kind == "turn_now"]
    assert len(turn_cues) == 1
    assert turn_cues[0].direction == "right"


# --- distance rounding ------------------------------------------------------

def test_round_speech_distance_examples():
    assert round_speech_distance(87.0) == 90    # nearest 10 under 100
    assert round_speech_distance(43.0) == 40
    assert round_speech_distance(5.0) == 10     # min 10
    assert round_speech_distance(150.0) == 150  # nearest 50 up to 500
    assert round_speech_distance(178.0) == 200
    assert round_speech_distance(650.0) == 700  # nearest 100 beyond 500


# --- edge cases -------------------------------------------------------------

def test_instruction_without_location_is_skipped():
    """If the router didn't provide interval data, that instruction has
    no location. Monitor should skip past it silently."""
    route_missing_loc = Route(
        distance_m=290.0,
        duration_s=210.0,
        instructions=[
            RouteInstruction("Head north", 145.0, None, location=_START, direction="straight"),
            RouteInstruction("Mystery turn", 145.0, None, location=None, direction="left"),
            RouteInstruction("Arrive", 0.0, None, location=_END, direction="arrive"),
        ],
        points=[_START, _END],
    )
    m = NavigationMonitor()
    m.set_route(route_missing_loc, "Test")

    # Skips the middle instruction; on a check near the end, arrive fires.
    m.check(_END)
    assert m.is_active() is False


def test_set_route_resets_state():
    """Calling set_route on an active monitor resets latches and cursor."""
    m = NavigationMonitor()
    m.set_route(_make_route(), "First")
    # Fire a turn_now + advance a bit.
    m.check(Coordinate(lat=14.00117, lon=121.0000))

    m.set_route(_make_route(), "Second")
    assert m.current_index() == 1
    # Same position should now announce/turn_now again (fresh latches).
    cues = m.check(Coordinate(lat=14.00117, lon=121.0000))
    assert any(c.kind == "turn_now" for c in cues)


# --- off-route detection ----------------------------------------------------

# ~44 m east of the route (which runs along lon=121.0000 north-south).
_OFF_ROUTE_44M = Coordinate(lat=14.0006, lon=121.0004)
# ~5 m east of the route — inside recovery zone.
_ON_ROUTE_5M = Coordinate(lat=14.0006, lon=121.00005)


def test_on_route_does_not_emit_off_route_cue():
    m = NavigationMonitor(
        off_route_distance_m=30.0,
        on_route_recovery_m=15.0,
        off_route_duration_s=15.0,
    )
    m.set_route(_make_route(), "Home")
    cues = m.check(Coordinate(14.0006, 121.0000), now=0.0)
    assert not any(c.kind == "off_route" for c in cues)


def test_off_route_debounces_before_warning():
    """The user must be off-route for the full duration before we warn."""
    m = NavigationMonitor(
        off_route_distance_m=30.0,
        on_route_recovery_m=15.0,
        off_route_duration_s=15.0,
    )
    m.set_route(_make_route(), "Home")

    # First observation — no warning yet.
    cues = m.check(_OFF_ROUTE_44M, now=0.0)
    assert not any(c.kind == "off_route" for c in cues)

    # 10 seconds later — still under the 15 s debounce.
    cues = m.check(_OFF_ROUTE_44M, now=10.0)
    assert not any(c.kind == "off_route" for c in cues)


def test_off_route_warning_fires_after_duration():
    m = NavigationMonitor(
        off_route_distance_m=30.0,
        on_route_recovery_m=15.0,
        off_route_duration_s=15.0,
    )
    m.set_route(_make_route(), "Home")

    m.check(_OFF_ROUTE_44M, now=0.0)
    cues = m.check(_OFF_ROUTE_44M, now=16.0)
    off_route_cues = [c for c in cues if c.kind == "off_route"]
    assert len(off_route_cues) == 1
    assert off_route_cues[0].direction is None   # the cue carries no data


def test_off_route_warning_latches_after_firing():
    """Once fired, don't warn again until the user gets back on route."""
    m = NavigationMonitor(off_route_duration_s=1.0)
    m.set_route(_make_route(), "Home")

    m.check(_OFF_ROUTE_44M, now=0.0)
    m.check(_OFF_ROUTE_44M, now=2.0)   # warns once
    cues = m.check(_OFF_ROUTE_44M, now=5.0)
    assert not any(c.kind == "off_route" for c in cues)


def test_off_route_recovery_clears_latch():
    """Getting back within recovery threshold clears the warning latch."""
    m = NavigationMonitor(
        off_route_distance_m=30.0,
        on_route_recovery_m=15.0,
        off_route_duration_s=1.0,
    )
    m.set_route(_make_route(), "Home")

    # Deviate and warn.
    m.check(_OFF_ROUTE_44M, now=0.0)
    m.check(_OFF_ROUTE_44M, now=2.0)

    # Recover.
    m.check(_ON_ROUTE_5M, now=10.0)

    # Second deviation — should warn again (fresh event).
    m.check(_OFF_ROUTE_44M, now=15.0)
    cues = m.check(_OFF_ROUTE_44M, now=17.0)
    assert any(c.kind == "off_route" for c in cues)


def test_set_route_clears_off_route_state():
    """Starting a new route clears any prior deviation state."""
    m = NavigationMonitor(off_route_duration_s=1.0)
    m.set_route(_make_route(), "First")
    m.check(_OFF_ROUTE_44M, now=0.0)
    m.check(_OFF_ROUTE_44M, now=2.0)   # warns for first route

    # New route resets everything.
    m.set_route(_make_route(), "Second")

    # Same deviation on the new route — should warn again (not latched
    # from the previous route).
    m.check(_OFF_ROUTE_44M, now=10.0)
    cues = m.check(_OFF_ROUTE_44M, now=12.0)
    assert any(c.kind == "off_route" for c in cues)


# --- remaining distance ------------------------------------------------------
#
# Measured along the polyline, not straight to the destination. The
# difference is the whole value of the answer: a destination 200 m away as
# the crow flies can be 500 m of walking around a block, and a user told
# the smaller number will believe they have arrived when they have not.

def _l_shaped_route() -> Route:
    """Two 100 m legs at a right angle: north, then east.

    Straight-line start-to-end is ~141 m; along the route it is 200 m.
    That gap is what these tests are about.
    """
    corner = Coordinate(lat=14.0009, lon=121.0000)      # ~100 m north of start
    end = Coordinate(lat=14.0009, lon=121.0009)         # ~100 m east of corner
    return Route(
        distance_m=200.0,
        duration_s=150.0,
        instructions=[],
        points=[_START, corner, end],
    )


def test_remaining_distance_follows_the_route_not_the_crow():
    monitor = NavigationMonitor()
    monitor.set_route(_l_shaped_route(), "Home")

    remaining = monitor.remaining_distance_m(_START)

    straight = haversine_m(_START, _l_shaped_route().points[-1])
    assert remaining > straight * 1.3        # the detour is real
    assert remaining == pytest.approx(200, rel=0.05)


def test_remaining_distance_shrinks_as_the_user_advances():
    monitor = NavigationMonitor()
    route = _l_shaped_route()
    monitor.set_route(route, "Home")

    at_start = monitor.remaining_distance_m(_START)
    at_corner = monitor.remaining_distance_m(route.points[1])

    assert at_corner < at_start
    assert at_corner == pytest.approx(100, rel=0.05)


def test_remaining_distance_is_about_zero_at_the_destination():
    monitor = NavigationMonitor()
    route = _l_shaped_route()
    monitor.set_route(route, "Home")

    assert monitor.remaining_distance_m(route.points[-1]) == pytest.approx(0, abs=5)


def test_partway_along_a_leg_counts_only_what_is_left_of_it():
    """The user is rarely standing exactly on a route point."""
    monitor = NavigationMonitor()
    route = _l_shaped_route()
    monitor.set_route(route, "Home")

    halfway_up = Coordinate(lat=14.00045, lon=121.0000)
    assert monitor.remaining_distance_m(halfway_up) == pytest.approx(150, rel=0.08)


def test_remaining_distance_measures_from_the_route_when_off_it():
    """The honest answer to "how much further" while walking back to the
    route is how far is left along it, not a detour they have not taken."""
    monitor = NavigationMonitor()
    route = _l_shaped_route()
    monitor.set_route(route, "Home")

    # 30 m to the side of the first leg, level with its midpoint.
    off_route = Coordinate(lat=14.00045, lon=121.0003)
    assert monitor.remaining_distance_m(off_route) == pytest.approx(150, rel=0.15)


def test_remaining_distance_is_none_without_a_route():
    assert NavigationMonitor().remaining_distance_m(_START) is None


def test_remaining_distance_is_none_for_a_degenerate_route():
    """A single point is not a path to measure along."""
    monitor = NavigationMonitor()
    monitor.set_route(
        Route(distance_m=0.0, duration_s=0.0, instructions=[], points=[_START]),
        "Home",
    )
    assert monitor.remaining_distance_m(_START) is None


def test_the_destination_name_is_available_while_active():
    monitor = NavigationMonitor()
    monitor.set_route(_l_shaped_route(), "Home")
    assert monitor.destination_name() == "Home"

    monitor.clear()
    assert monitor.destination_name() == ""


# --- turn verification -------------------------------------------------------
#
# The cursor advances past a turn on proximity alone, so a user who walks
# straight past a corner keeps getting cues for a leg they are not on until
# off-route detection catches it 15-30 s later. With a heading, the monitor
# can say so in about five.
#
# Additive by design: every assertion below about advancement, announces and
# turn_cues elsewhere in this file still holds, because passing no heading
# changes nothing.

def _turning_route() -> Route:
    """North for 100 m, then a left turn and 100 m west."""
    start = Coordinate(lat=14.0000, lon=121.0000)
    corner = Coordinate(lat=14.0009, lon=121.0000)
    end = Coordinate(lat=14.0009, lon=120.9991)
    return Route(
        distance_m=200.0, duration_s=150.0,
        instructions=[
            RouteInstruction(text="Head north", distance_m=100.0,
                             street_name="A", location=start, direction="straight"),
            RouteInstruction(text="Turn left onto B", distance_m=100.0,
                             street_name="B", location=corner, direction="left"),
            RouteInstruction(text="Arrive", distance_m=0.0,
                             street_name=None, location=end, direction="arrive"),
        ],
        points=[start, corner, end],
    )


def _past_corner(metres: float) -> Coordinate:
    """A position `metres` west of the corner, i.e. along the second leg.

    The route turns left and runs ~97 m west, so a fraction of that
    longitude span is a distance along it.
    """
    corner = _turning_route().instructions[1].location
    return Coordinate(lat=corner.lat, lon=corner.lon - 0.0009 * (metres / 97.0))


def _north_of_corner(metres: float) -> Coordinate:
    """A position `metres` north of the corner: the user carried straight
    on instead of turning left."""
    corner = _turning_route().instructions[1].location
    return Coordinate(lat=corner.lat + metres / 111_000.0, lon=corner.lon)


def _at_corner(monitor, now=0.0, heading=None):
    """Walk the user to the turn point, which is what arms verification.

    Reaching the turn is the event, not passing it: a user who carries
    straight on past a corner makes no further progress *along* the route,
    so arming on the cursor advance would miss the one case verification
    exists for.
    """
    return monitor.check(
        _turning_route().instructions[1].location, now=now, heading=heading,
    )


def test_carrying_straight_on_is_reported():
    """Route turns left (west). The user is still heading north."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(_north_of_corner(12.0), now=10.0, heading=0.0)

    assert [c.kind for c in cues].count("missed_turn") == 1
    missed = next(c for c in cues if c.kind == "missed_turn")
    assert missed.direction == "left"
    assert missed.street_name == "B"


def test_actually_turning_is_not_reported():
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(_past_corner(12.0), now=10.0, heading=270.0)

    assert [c.kind for c in cues] == []


def test_a_wide_turn_is_tolerated():
    """The question is whether a turn happened at all, not whether it was
    tidy. Heading measured while walking carries the sway of every stride,
    and flagging a user who turned perfectly well would teach them to
    ignore the warning."""
    monitor = NavigationMonitor(turn_verify_tolerance_deg=60.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(_past_corner(12.0), now=10.0, heading=315.0)

    assert [c.kind for c in cues] == []


def test_nothing_is_judged_until_the_turn_has_been_walked():
    """Nobody has pivoted by the time they reach the corner. Judging
    there would flag every user on every turn."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(_past_corner(3.0), now=2.0, heading=0.0)

    assert [c.kind for c in cues] == []


def test_standing_at_the_corner_is_never_judged_however_long():
    """The bug this measure replaced. Verification ran on a fixed 5 s
    timer started when the cursor passed the turn, so the check landed
    `delay - advance/speed` seconds after the user reached the corner:
    +1.4 s at 1.4 m/s, and -3.3 s at 0.6 m/s — before they got there.
    Cane users walk at 0.6-0.9 m/s, so the device told them they had
    missed a turn they were still approaching.

    No amount of elapsed time may produce a verdict on its own. A user
    waiting at a kerb for traffic has not failed to turn.
    """
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    corner = _turning_route().instructions[1].location

    for second in range(1, 60):
        assert monitor.check(corner, now=float(second), heading=0.0) == []


def test_a_slow_walker_who_turns_correctly_is_not_flagged():
    """Walked at 0.6 m/s — the pace the old timer could not survive —
    with the pivot taking a realistic couple of seconds."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")

    now = 0.0
    _at_corner(monitor, now=now, heading=0.0)
    corner = _turning_route().instructions[1].location

    # Two seconds pivoting on the spot, still facing north.
    for _ in range(2):
        now += 1.0
        assert monitor.check(corner, now=now, heading=0.0) == []

    # Then 30 s of walking the next leg at 0.6 m/s, now facing west.
    cues = []
    for step in range(1, 31):
        now += 1.0
        cues += monitor.check(
            _past_corner(0.6 * step), now=now, heading=270.0,
        )

    assert [c.kind for c in cues if c.kind == "missed_turn"] == []


def test_it_reports_at_most_once_per_turn():
    """A user who knows they missed it does not need telling twice."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    corner = _turning_route().instructions[1].location

    first = monitor.check(_north_of_corner(12.0), now=10.0, heading=0.0)
    second = monitor.check(_north_of_corner(14.0), now=11.0, heading=0.0)

    assert [c.kind for c in first].count("missed_turn") == 1
    assert [c.kind for c in second] == []


def test_no_heading_never_reports_a_missed_turn():
    """An absent or uncalibrated compass must not manufacture a warning."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(_north_of_corner(12.0), now=10.0)

    assert [c.kind for c in cues] == []


def test_a_straight_instruction_is_never_verified():
    """"Carry on" cannot be missed."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    monitor.check(_turning_route().points[0], now=0.0, heading=0.0)

    assert monitor._pending_turn is None


def test_a_short_next_leg_is_not_verified():
    """Under the minimum, the bearing between two instructions is too
    noisy to judge a turn by — skipped rather than guessed at."""
    start = Coordinate(lat=14.0000, lon=121.0000)
    corner = Coordinate(lat=14.0009, lon=121.0000)
    barely = Coordinate(lat=14.0009, lon=120.99995)      # ~5 m west
    route = Route(
        distance_m=105.0, duration_s=80.0,
        instructions=[
            RouteInstruction(text="Head north", distance_m=100.0, street_name="A",
                             location=start, direction="straight"),
            RouteInstruction(text="Turn left", distance_m=5.0, street_name="B",
                             location=corner, direction="left"),
            RouteInstruction(text="Arrive", distance_m=0.0, street_name=None,
                             location=barely, direction="arrive"),
        ],
        points=[start, corner, barely],
    )
    monitor = NavigationMonitor()
    monitor.set_route(route, "Home")
    monitor.check(corner, now=0.0, heading=0.0)

    assert monitor._pending_turn is None


def test_cancelling_navigation_disarms_verification():
    """Otherwise a stale turn could be reported against the next route."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    assert monitor._pending_turn is not None

    monitor.clear()

    assert monitor._pending_turn is None


def test_a_new_route_disarms_verification():
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    monitor.set_route(_turning_route(), "Work")

    assert monitor._pending_turn is None


# --- cues handed back --------------------------------------------------------
#
# Each cue is marked fired before it is returned, so one the application
# could not speak was gone for good. `app.py` drops them whenever the voice
# pipeline is busy — any voice command, plus the whole turn-to-face step —
# and the comment there claimed they came round again on a later poll.
#
# `defer()` undoes the latch rather than holding the text, because these
# cues are statements about where the user is and the user is walking: held
# and replayed, "In 90 meters, turn left" arrives after they have walked 25
# of them. Un-latched, the next poll re-asks the question.


def test_a_deferred_announce_is_offered_again():
    m = NavigationMonitor()
    m.set_route(_make_route(), "Home")
    approaching = _metres_north_of(_MIDPOINT, -60.0)

    first = [c for c in m.check(approaching) if c.kind == "announce"]
    assert len(first) == 1
    assert m.check(approaching) == []        # latched, as before

    m.defer(first[0])

    assert [c.kind for c in m.check(approaching)] == ["announce"]


def test_a_deferred_announce_is_re_measured_not_replayed():
    """The distance is taken again, so the user hears where they are now
    rather than where they were when the pipeline was busy."""
    m = NavigationMonitor()
    m.set_route(_make_route(), "Home")

    far = [c for c in m.check(_metres_north_of(_MIDPOINT, -90.0))
           if c.kind == "announce"][0]
    m.defer(far)

    near = [c for c in m.check(_metres_north_of(_MIDPOINT, -40.0))
            if c.kind == "announce"][0]

    assert far.distance_m == pytest.approx(90.0, abs=2.0)
    assert near.distance_m == pytest.approx(40.0, abs=2.0)


def test_a_deferred_turn_now_stops_being_offered_once_the_turn_is_behind():
    """Re-offering is not replaying, and the cursor is what bounds it.

    A user walking through a busy window keeps being offered "turn left"
    and keeps having it deferred; the moment their progress carries them
    `advance_distance_m` past the corner the cursor moves on, and the cue
    is never asked for again. So the staleness is bounded by that margin
    rather than by how long the pipeline stays busy — which matters,
    because turn-to-face can hold it for 20 s and a user told to turn
    left half a block late turns into the wrong street.
    """
    m = NavigationMonitor(advance_distance_m=5.0)
    m.set_route(_make_route(), "Home")

    # Walk from 10 m before the corner to 10 m past it, a metre at a time,
    # deferring everything as a busy pipeline would.
    offered_at = []
    for metres in range(-10, 11):
        for cue in m.check(_metres_north_of(_MIDPOINT, float(metres))):
            if cue.kind == "turn_now":
                offered_at.append(metres)
            m.defer(cue)

    assert offered_at, "the cue was never offered at all"
    assert max(offered_at) <= 5          # never more than the advance margin
    assert m.current_index() == 2


def test_a_deferred_off_route_warning_comes_back_without_a_second_debounce():
    """The deviation has already lasted long enough. Restarting the
    15 s debounce would make the user walk it twice over."""
    m = NavigationMonitor()
    m.set_route(_make_route(), "Home")
    away = Coordinate(lat=14.0013, lon=121.0010)      # ~108 m off route

    m.check(away, now=0.0)
    warning = [c for c in m.check(away, now=20.0) if c.kind == "off_route"][0]
    assert m.check(away, now=21.0) == []              # latched

    m.defer(warning)

    assert [c.kind for c in m.check(away, now=22.0)] == ["off_route"]


def test_a_deferred_missed_turn_is_held_verbatim():
    """The one cue that is held rather than re-measured: it reports
    something that already happened, so it stays true however long it
    waits, and the position it was judged from is gone."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    missed = [c for c in monitor.check(_north_of_corner(12.0), now=10.0,
                                       heading=0.0) if c.kind == "missed_turn"][0]
    assert monitor.check(_north_of_corner(14.0), now=11.0, heading=0.0) == []

    monitor.defer(missed)
    cues = monitor.check(_north_of_corner(16.0), now=12.0, heading=0.0)

    assert cues == [missed]
    # And once delivered it is gone — redelivery is not a repeat.
    assert monitor.check(_north_of_corner(18.0), now=13.0, heading=0.0) == []


def test_a_new_route_drops_a_held_missed_turn():
    """It belongs to a route the user is no longer on."""
    monitor = NavigationMonitor()
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    missed = [c for c in monitor.check(_north_of_corner(12.0), now=10.0,
                                       heading=0.0) if c.kind == "missed_turn"][0]
    monitor.defer(missed)

    monitor.set_route(_turning_route(), "Work")

    assert monitor._missed_turn_redeliver is None
