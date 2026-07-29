"""Unit tests for the NavigationMonitor.

Pure logic — no threads, no hardware. Tests exercise the state machine
by feeding synthetic GPS positions and asserting on the cues returned.
"""
from indepensense.navigation.monitor import (
    NavigationCue,
    NavigationMonitor,
    _round_speech_distance,
)
from indepensense.routing.base import Coordinate, Route, RouteInstruction


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
    m = NavigationMonitor()
    m.set_route(_make_route(), "Home")

    # Position right at the destination — advance through midpoint and
    # then reach arrive. The check() loop advances through both.
    m.check(_END)   # this should reach both midpoint and end in one call

    # We should have received an arrive cue at some point. In practice
    # a single call at exactly the destination triggers the advance
    # through midpoint (via loop) and then the arrival cue for `end`.
    # After arrive, the monitor deactivates.
    assert m.is_active() is False


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
    assert _round_speech_distance(87.0) == 90    # nearest 10 under 100
    assert _round_speech_distance(43.0) == 40
    assert _round_speech_distance(5.0) == 10     # min 10
    assert _round_speech_distance(150.0) == 150  # nearest 50 up to 500
    assert _round_speech_distance(178.0) == 200
    assert _round_speech_distance(650.0) == 700  # nearest 100 beyond 500


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
