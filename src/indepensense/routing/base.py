"""Routing and geocoding interfaces.

`Coordinate` carries latitude and longitude in that order — application code
uses (lat, lon). GeoJSON encodes coordinates as (lon, lat); drivers translate
at the boundary so callers never see GeoJSON's order.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Coordinate:
    lat: float
    lon: float


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
    ) -> Route:
        """Compute a route between two coordinates."""


class Geocoder(Protocol):
    def geocode(
        self,
        query: str,
        limit: int = 5,
        near: Coordinate | None = None,
    ) -> list[GeocodingResult]:
        """Forward-geocode a place name into coordinates.

        When `near` is provided, the geocoder biases results toward that
        location. Exact name matches for specific places (e.g. "SM
        Manila") still win over proximity — the bias only breaks ties
        between multiple matches with equivalent text relevance (e.g. the
        five hundred Jollibees scattered across the country).
        """

    def reverse(self, coordinate: Coordinate) -> GeocodingResult | None:
        """Reverse-geocode coordinates into the nearest known place."""
