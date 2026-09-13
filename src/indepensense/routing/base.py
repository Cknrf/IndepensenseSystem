"""Routing and geocoding interfaces.

`Coordinate` carries latitude and longitude in that order — application code
uses (lat, lon). GeoJSON encodes coordinates as (lon, lat); drivers translate
at the boundary so callers never see GeoJSON's order.
"""
import math
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lon: float


def haversine_m(a: Coordinate, b: Coordinate) -> float:
    """Great-circle distance in metres between two coordinates.

    Standard haversine formula. Accurate to <1 m at walking scales; the
    Earth's ellipsoidal shape only matters for kilometre-scale routing and
    every consumer here operates well below that.

    Lives beside `Coordinate` rather than in either caller because both the
    navigation monitor (distance to the next turn) and candidate ranking
    (distance to each geocoder hit) need it, and neither domain should have
    to import the other to measure a distance.
    """
    r_earth_m = 6_371_000.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    d_lat = math.radians(b.lat - a.lat)
    d_lon = math.radians(b.lon - a.lon)
    h = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2)
    return 2 * r_earth_m * math.asin(math.sqrt(h))


@dataclass(frozen=True)
class RouteInstruction:
    text: str
    distance_m: float
    street_name: str | None
    # Where this instruction's turn happens. The turn point is the
    # START of the instruction's polyline segment — i.e. from the user's
    # perspective, this is where they need to act (turn left, turn right,
    # or arrive). `None` when the router doesn't provide interval data.
    location: Coordinate | None = None
    # Turn semantics, derived from GraphHopper's `sign` code:
    #   "left"     — any leftward turn (slight, normal, sharp, keep-left)
    #   "right"    — any rightward turn
    #   "straight" — continue on street, no significant turn
    #   "arrive"   — final destination reached
    #   "waypoint" — intermediate via-point (rare on single-destination routes)
    direction: str = "straight"


@dataclass(frozen=True)
class Route:
    distance_m: float
    duration_s: float
    instructions: list[RouteInstruction]
    points: list[Coordinate]


@dataclass(frozen=True)
class GeocodingResult:
    name: str
    coordinate: Coordinate
    country: str | None
    city: str | None
    feature_type: str | None
    street: str | None = None
    district: str | None = None
    state: str | None = None


class Router(Protocol):
    def route(
        self,
        start: Coordinate,
        end: Coordinate,
        profile: str = "foot",
        heading: float | None = None,
    ) -> Route:
        """Compute a route between two coordinates.

        `heading` is the direction the user is currently facing, in degrees
        clockwise from north. When given, the route is biased to set off
        that way rather than opening with "turn around" — a sighted user
        glances at a map and corrects; this one would simply walk the wrong
        way. None means the direction is unknown, which is also what an
        uncalibrated compass reports.
        """


class Geocoder(Protocol):
    def geocode(
        self,
        query: str,
        limit: int = 5,
        near: Coordinate | None = None,
    ) -> list[GeocodingResult]:
        """Forward-geocode a place name into candidate coordinates.

        Returns up to `limit` candidates in the geocoder's own relevance
        order, which blends text match against an opaque location bias.
        `near` nudges that bias but does not control it.

        Callers must NOT assume the first result is the one the user
        meant. No geocoder here answers "which of these is nearest" —
        that question is decided by `routing.ranking.rank_candidates`
        over the full candidate list. Asking for a single result throws
        away the information that decision needs.
        """

    def reverse(self, coordinate: Coordinate) -> GeocodingResult | None:
        """Reverse-geocode coordinates into the nearest known place."""
