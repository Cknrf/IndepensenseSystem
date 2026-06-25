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


class Router(Protocol):
    def route(
        self,
        start: Coordinate,
        end: Coordinate,
        profile: str = "foot",
    ) -> Route:
        """Compute a route between two coordinates."""


class Geocoder(Protocol):
    def geocode(self, query: str, limit: int = 5) -> list[GeocodingResult]:
        """Forward-geocode a place name into coordinates."""

    def reverse(self, coordinate: Coordinate) -> GeocodingResult | None:
        """Reverse-geocode coordinates into the nearest known place."""
