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
        # Contrived three-instruction route so tests that exercise the
        # NavigationMonitor can advance through multiple waypoints.
        # Halfway point synthesised as the mid-lat/mid-lon of start+end.
        midpoint = Coordinate(
            lat=(start.lat + end.lat) / 2,
            lon=(start.lon + end.lon) / 2,
        )
        instructions = [
            RouteInstruction(
                text="Head east on a fake street",
                distance_m=60.0,
                street_name="Fake St",
                location=start,
                direction="straight",
            ),
            RouteInstruction(
                text="Turn left onto Mock Avenue",
                distance_m=60.0,
                street_name="Mock Avenue",
                location=midpoint,
                direction="left",
            ),
            RouteInstruction(
                text="Arrive at destination",
                distance_m=0.0,
                street_name=None,
                location=end,
                direction="arrive",
            ),
        ]
        return Route(
            distance_m=120.0,
            duration_s=90.0,
            instructions=instructions,
            points=[start, midpoint, end],
        )


class MockGeocoder:
    def geocode(
        self,
        query: str,
        limit: int = 5,
        near: Coordinate | None = None,
    ) -> list[GeocodingResult]:
        # `near` is accepted to match the Geocoder protocol but the mock
        # returns a fixed result regardless. Callers that want to verify
        # proximity behaviour should use a scripted fake in the test file.
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
