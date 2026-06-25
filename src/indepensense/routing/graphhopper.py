"""HTTP client for a local GraphHopper routing service.

See `docs/graphhopper.md` for the service setup. This module assumes a server
listening on `GRAPHHOPPER_URL` with the `foot` profile configured.
"""
from typing import Any

from indepensense.routing.base import Coordinate, Route, RouteInstruction

_DEFAULT_TIMEOUT_S = 10.0


def parse_graphhopper_response(payload: dict[str, Any]) -> Route:
    """Parse a GraphHopper /route response into a Route.

    GraphHopper returns `paths` as a list (alternatives are possible); we
    take the first. Times are in milliseconds, coordinates are GeoJSON order
    (lon, lat) — we flip them to (lat, lon) at this boundary.
    """
    path = payload["paths"][0]
    instructions = [
        RouteInstruction(
            text=step["text"],
            distance_m=step["distance"],
            street_name=step.get("street_name") or None,
        )
        for step in path["instructions"]
    ]
    points = [
        Coordinate(lat=lat, lon=lon)
        for lon, lat in path["points"]["coordinates"]
    ]
    return Route(
        distance_m=path["distance"],
        duration_s=path["time"] / 1000.0,
        instructions=instructions,
        points=points,
    )


class GraphHopperRouter:
    def __init__(self, base_url: str, timeout_s: float = _DEFAULT_TIMEOUT_S):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def route(
        self,
        start: Coordinate,
        end: Coordinate,
        profile: str = "foot",
    ) -> Route:
        import requests  # lazy: keeps imports cheap on cold starts

        params = [
            ("point", f"{start.lat},{start.lon}"),
            ("point", f"{end.lat},{end.lon}"),
            ("profile", profile),
            ("points_encoded", "false"),
            ("instructions", "true"),
        ]
        response = requests.get(
            f"{self._base_url}/route",
            params=params,
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return parse_graphhopper_response(response.json())
