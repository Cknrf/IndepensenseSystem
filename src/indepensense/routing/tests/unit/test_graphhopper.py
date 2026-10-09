import pytest

from indepensense.routing import graphhopper
from indepensense.routing.base import Coordinate
from indepensense.routing.graphhopper import (
    GraphHopperRouter,
    parse_graphhopper_response,
)


_SAMPLE_RESPONSE = {
    "paths": [
        {
            "distance": 134.5,
            "time": 96000,
            "instructions": [
                {"text": "Head east on Rizal Park Rd", "distance": 50.0, "street_name": "Rizal Park Rd"},
                {"text": "Turn left onto Roxas Blvd", "distance": 80.0, "street_name": "Roxas Blvd"},
                {"text": "Arrive at destination", "distance": 0.0, "street_name": ""},
            ],
            "points": {
                "coordinates": [
                    [120.9842, 14.5995],
                    [120.9850, 14.6000],
                    [120.9860, 14.6010],
                ],
            },
        }
    ]
}


def test_parses_distance_and_duration():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    assert route.distance_m == 134.5
    assert route.duration_s == 96.0   # 96000 ms -> 96 s


def test_parses_all_instructions():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    assert len(route.instructions) == 3
    assert route.instructions[0].text == "Head east on Rizal Park Rd"
    assert route.instructions[0].street_name == "Rizal Park Rd"


def test_treats_empty_street_name_as_none():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    assert route.instructions[-1].street_name is None


def test_flips_geojson_lon_lat_to_lat_lon():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    # GeoJSON input was [120.9842, 14.5995]; we should expose (lat=14.5995, lon=120.9842)
    assert route.points[0].lat == 14.5995
    assert route.points[0].lon == 120.9842


# --- departure heading -------------------------------------------------------
#
# Without it a route can open with "turn around". A sighted user glances at
# a map and corrects; this one simply walks the wrong way.

class _CapturingSession:
    """Stands in for `requests.get`, recording the params it was handed."""

    def __init__(self, payload):
        self._payload = payload
        self.params = None
        # A real requests.Response always carries these; the client reads
        # `ok` so that a failed request can report GraphHopper's own
        # message instead of a bare status line.
        self.ok = True
        self.status_code = 200

    def __call__(self, url, params=None, timeout=None):
        self.params = params
        return self

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


@pytest.fixture
def capture(monkeypatch):
    import requests
    session = _CapturingSession({
        "paths": [{
            "distance": 100.0, "time": 60000,
            "points": {"coordinates": [[121.0, 14.0], [121.001, 14.001]]},
            "instructions": [
                {"text": "Head north", "distance": 100.0, "sign": 0, "interval": [0, 1]},
            ],
        }]
    })
    monkeypatch.setattr(requests, "get", session)
    return session


def _params(capture) -> dict:
    """Flatten the (key, value) list into a dict for assertions."""
    return {key: value for key, value in capture.params}


def test_a_heading_is_sent_to_graphhopper(capture):
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001), heading=90.0,
    )

    assert _params(capture)["heading"] == "90"


def test_no_heading_sends_no_parameter(capture):
    """A request without a heading must be byte-identical to what this sent
    before the parameter existed — an uncalibrated compass is the normal
    case today, and it must not change routing at all."""
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001),
    )

    assert "heading" not in _params(capture)


def test_a_heading_is_normalised_into_range(capture):
    """GraphHopper rejects values outside 0-360. A caller's arithmetic
    producing 375 is not a reason to fail the whole route request."""
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001), heading=375.0,
    )

    assert _params(capture)["heading"] == "15"


def test_a_negative_heading_is_normalised(capture):
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001), heading=-90.0,
    )

    assert _params(capture)["heading"] == "270"


def test_a_heading_of_zero_is_sent_not_dropped(capture):
    """Due north is a real heading. `if heading:` would have silently
    dropped it — the bug this test exists to prevent."""
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001), heading=0.0,
    )

    assert _params(capture)["heading"] == "0"


# --- what a failed request reports -------------------------------------------
#
# `raise_for_status()` alone says "500 Server Error for url: ...", which
# is the one thing the caller already knew. A field test lost time to
# exactly that while GraphHopper's own explanation sat unread in the
# response body.

class _Response:
    def __init__(self, status_code=500, payload=None, text=""):
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


def test_the_servers_own_message_reaches_the_caller():
    detail = graphhopper._error_detail(
        _Response(payload={"message": "Cannot find point 1: 13.9,121.1"})
    )

    assert "Cannot find point 1" in detail


def test_hints_are_appended_when_they_add_something():
    detail = graphhopper._error_detail(_Response(payload={
        "message": "Connection between locations not found",
        "hints": [{"details": "ConnectionNotFoundException"}],
    }))

    assert "Connection between locations not found" in detail
    assert "ConnectionNotFoundException" in detail


def test_a_hint_that_repeats_the_message_is_not_doubled():
    detail = graphhopper._error_detail(_Response(payload={
        "message": "Unknown profile 'foot'",
        "hints": [{"details": "Unknown profile 'foot'"}],
    }))

    assert detail == "Unknown profile 'foot'"


def test_a_non_json_body_falls_back_to_text():
    detail = graphhopper._error_detail(
        _Response(text="<html>502 Bad Gateway</html>")
    )

    assert "502 Bad Gateway" in detail


def test_an_empty_body_still_says_something():
    """This runs while something is already broken; it must not become a
    second failure on top of the first."""
    assert graphhopper._error_detail(_Response(text="")) == "no detail in response"


def test_the_route_call_raises_with_the_detail(monkeypatch):
    import requests

    def _get(url, params=None, timeout=None):
        return _Response(payload={"message": "Cannot find point 2"})

    monkeypatch.setattr(requests, "get", _get)
    router = graphhopper.GraphHopperRouter(base_url="http://127.0.0.1:8989")

    with pytest.raises(requests.HTTPError) as caught:
        router.route(Coordinate(13.9, 121.1), Coordinate(13.94, 121.13))

    assert "Cannot find point 2" in str(caught.value)
    assert "500" in str(caught.value)


# --- heading and contraction hierarchies cannot both be used -----------------
#
# GraphHopper 400s on the pair: CH bakes the first edge out of the start
# into its shortcuts, so a departure bias has nothing to act on. The
# request was sending `heading` alone, which worked only for as long as
# the compass was uncalibrated and the caller passed None.

def test_a_heading_disables_speed_mode(capture):
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001), heading=270.0,
    )

    assert _params(capture)["ch.disable"] == "true", (
        "sent a heading without disabling CH — GraphHopper answers 400"
    )


def test_no_heading_leaves_speed_mode_on(capture):
    """CH is why routing is fast. It must not be given up on every
    request just because some requests cannot use it."""
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001),
    )

    assert "ch.disable" not in _params(capture)


def test_a_heading_of_zero_still_disables_speed_mode(capture):
    """Due north is a heading, not a missing one — the same `0 is falsy`
    trap the heading parameter itself already guards against."""
    GraphHopperRouter("http://x").route(
        Coordinate(14.0, 121.0), Coordinate(14.001, 121.001), heading=0.0,
    )

    assert _params(capture)["ch.disable"] == "true"
