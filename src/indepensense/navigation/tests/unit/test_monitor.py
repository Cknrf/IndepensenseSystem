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
    m = NavigationMonitor(announce_distance_m=100.0, haptic_distance_m=20.0, advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")

    # Position 80m from midpoint — inside announce threshold.
    close_to_midpoint = Coordinate(lat=14.0006, lon=121.0000)  # ~78m from midpoint
    cues = m.check(close_to_midpoint)

    announce = [c for c in cues if c.kind == "announce"]
    assert len(announce) == 1
    assert "meters" in announce[0].text
    assert "Turn left" in announce[0].text


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


# --- haptic cue --------------------------------------------------------------

def test_haptic_fires_within_haptic_threshold_with_direction():
    m = NavigationMonitor(announce_distance_m=100.0, haptic_distance_m=20.0, advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")

    # Position ~15m south of midpoint — inside 20m haptic threshold.
    very_close = Coordinate(lat=14.00117, lon=121.0000)  # ~14.5m from midpoint
    cues = m.check(very_close)

    haptics = [c for c in cues if c.kind == "haptic"]
    assert len(haptics) == 1
    assert haptics[0].direction == "left"


def test_haptic_does_not_repeat():
    m = NavigationMonitor()
    m.set_route(_make_route(), "Test")

    very_close = Coordinate(lat=14.00117, lon=121.0000)
    m.check(very_close)  # first call fires haptic
    cues = m.check(very_close)  # second should not
    assert not any(c.kind == "haptic" for c in cues)


# --- advancement -------------------------------------------------------------

def test_advance_when_close_to_turn():
    m = NavigationMonitor(advance_distance_m=5.0)
    m.set_route(_make_route(), "Test")
    assert m.current_index() == 1

    # Position ~3m from midpoint — within advance threshold.
    at_turn = Coordinate(lat=14.00127, lon=121.0000)  # ~3m from midpoint
    m.check(at_turn)
    assert m.current_index() == 2   # advanced to "arrive"


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
    """Arrival uses the advance threshold (5 m), not the announce
    threshold (100 m). Guards against speaking "you have arrived" while
    the user is still most of a block away."""
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


def test_arrive_cue_names_destination():
    m = NavigationMonitor(announce_distance_m=1000.0)  # generous so first check announces
    m.set_route(_make_route(), "Home")

    cues = m.check(_END)
    arrive_cues = [c for c in cues if c.kind == "arrive"]
    assert len(arrive_cues) >= 1
    assert "Home" in arrive_cues[0].text


# --- direction mapping guard ------------------------------------------------

def test_haptic_direction_matches_instruction():
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
    haptics = [c for c in cues if c.kind == "haptic"]
    assert len(haptics) == 1
    assert haptics[0].direction == "right"


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
    # Fire a haptic + advance a bit.
    m.check(Coordinate(lat=14.00117, lon=121.0000))

    m.set_route(_make_route(), "Second")
    assert m.current_index() == 1
    # Same position should now announce/haptic again (fresh latches).
    cues = m.check(Coordinate(lat=14.00117, lon=121.0000))
    assert any(c.kind == "haptic" for c in cues)


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
    assert "off the planned route" in off_route_cues[0].text.lower()


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
# haptics elsewhere in this file still holds, because passing no heading
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


def _at_corner(monitor, now=0.0, heading=None):
    """Walk the user to the turn point so the cursor advances past it."""
    corner = _turning_route().instructions[1].location
    return monitor.check(corner, now=now, heading=heading)


def test_carrying_straight_on_is_reported():
    """Route turns left (west). The user is still heading north."""
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(
        _turning_route().instructions[1].location, now=10.0, heading=0.0,
    )

    assert [c.kind for c in cues].count("missed_turn") == 1
    missed = next(c for c in cues if c.kind == "missed_turn")
    assert missed.direction == "left"
    assert "B" in missed.text


def test_actually_turning_is_not_reported():
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(
        _turning_route().instructions[1].location, now=10.0, heading=270.0,
    )

    assert [c.kind for c in cues] == []


def test_a_wide_turn_is_tolerated():
    """The question is whether a turn happened at all, not whether it was
    tidy. Heading measured while walking carries the sway of every stride,
    and flagging a user who turned perfectly well would teach them to
    ignore the warning."""
    monitor = NavigationMonitor(
        turn_verify_delay_s=5.0, turn_verify_tolerance_deg=60.0,
    )
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(
        _turning_route().instructions[1].location, now=10.0, heading=315.0,
    )

    assert [c.kind for c in cues] == []


def test_nothing_is_judged_before_the_turn_has_had_time():
    """Nobody has pivoted by the time they reach the corner. Checking
    immediately would flag every user on every turn."""
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(
        _turning_route().instructions[1].location, now=2.0, heading=0.0,
    )

    assert [c.kind for c in cues] == []


def test_it_reports_at_most_once_per_turn():
    """A user who knows they missed it does not need telling twice."""
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    corner = _turning_route().instructions[1].location

    first = monitor.check(corner, now=10.0, heading=0.0)
    second = monitor.check(corner, now=11.0, heading=0.0)

    assert [c.kind for c in first].count("missed_turn") == 1
    assert [c.kind for c in second] == []


def test_no_heading_never_reports_a_missed_turn():
    """An absent or uncalibrated compass must not manufacture a warning."""
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    cues = monitor.check(_turning_route().instructions[1].location, now=10.0)

    assert [c.kind for c in cues] == []


def test_a_straight_instruction_is_never_verified():
    """"Carry on" cannot be missed."""
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
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
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(route, "Home")
    monitor.check(corner, now=0.0, heading=0.0)

    assert monitor._pending_turn is None


def test_cancelling_navigation_disarms_verification():
    """Otherwise a stale turn could be reported against the next route."""
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)
    assert monitor._pending_turn is not None

    monitor.clear()

    assert monitor._pending_turn is None


def test_a_new_route_disarms_verification():
    monitor = NavigationMonitor(turn_verify_delay_s=5.0)
    monitor.set_route(_turning_route(), "Home")
    _at_corner(monitor, now=0.0)

    monitor.set_route(_turning_route(), "Work")

    assert monitor._pending_turn is None
