"""Mock router and geocoder for off-device development.

Returns deterministic, hand-crafted results so navigation/decision logic can
be exercised on a Mac without the GraphHopper or Photon services running.
"""
from indepensense.routing.base import (
    Coordinate,
    GeocodingResult,
    Route,
    RouteInstruction,
)


class MockRouter:
    def route(
        self,
        start: Coordinate,
        end: Coordinate,
        profile: str = "foot",
    ) -> Route:
        instructions = [
            RouteInstruction(text="Head east on a fake street", distance_m=120.0, street_name="Fake St"),
            RouteInstruction(text="Arrive at destination", distance_m=0.0, street_name=None),
        ]
        return Route(
            distance_m=120.0,
            duration_s=90.0,
            instructions=instructions,
            points=[start, end],
        )


class MockGeocoder:
    def geocode(self, query: str, limit: int = 5) -> list[GeocodingResult]:
        return [
            GeocodingResult(
                name=query,
                coordinate=Coordinate(lat=14.5995, lon=120.9842),
                country="Philippines",
                city="Manila",
                feature_type="city",
            )
        ]

    def reverse(self, coordinate: Coordinate) -> GeocodingResult | None:
        return GeocodingResult(
            name="Mock Place",
            coordinate=coordinate,
            country="Philippines",
            city="Mock City",
            feature_type="city",
        )
