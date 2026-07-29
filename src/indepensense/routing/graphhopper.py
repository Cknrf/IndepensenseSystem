"""HTTP client for a local GraphHopper routing service.

See `docs/graphhopper.md` for the service setup. This module assumes a server
listening on `GRAPHHOPPER_URL` with the `foot` profile configured.
"""
from typing import Any

from indepensense.routing.base import Coordinate, Route, RouteInstruction

_DEFAULT_TIMEOUT_S = 10.0


def _direction_from_sign(sign: int) -> str:
    """Map GraphHopper's turn `sign` code to our simplified direction.

    GraphHopper's codes (v11):
      -8 KEEP_LEFT, -7 TURN_SHARP_LEFT, -3 TURN_SHARP_LEFT (older),
      -2 TURN_LEFT, -1 TURN_SLIGHT_LEFT, 0 CONTINUE_ON_STREET,
      1 TURN_SLIGHT_RIGHT, 2 TURN_RIGHT, 3 TURN_SHARP_RIGHT,
      4 FINISH, 5 REACHED_VIA, 6 U_TURN_UNKNOWN, 7 KEEP_RIGHT.

    We collapse the granularity to what the three-motor wearable can
    actually express: any left turn → "left", any right → "right",
    continue-on-street → "straight", finish → "arrive", via-point →
    "waypoint". A wearable that can't distinguish "slight" from "sharp"
    left doesn't gain much from a five-way direction taxonomy.
    """
    if sign == 4:
        return "arrive"
    if sign == 5:
        return "waypoint"
    if sign == 0:
        return "straight"
    if sign < 0:
        return "left"
    return "right"


def parse_graphhopper_response(payload: dict[str, Any]) -> Route:
    """Parse a GraphHopper /route response into a Route.

    GraphHopper returns `paths` as a list (alternatives are possible); we
    take the first. Times are in milliseconds, coordinates are GeoJSON order
    (lon, lat) — we flip them to (lat, lon) at this boundary.

    Each instruction gains a `location` (turn point) derived from the
    instruction's `interval` field: `interval[0]` is the index into
    `points` where the described action occurs. Some instructions may
    lack `interval` — in that case `location` stays `None`.
    """
    path = payload["paths"][0]
    points = [
        Coordinate(lat=lat, lon=lon)
        for lon, lat in path["points"]["coordinates"]
    ]

    instructions: list[RouteInstruction] = []
    for step in path["instructions"]:
        # interval = [start_point_index, end_point_index]. The turn/action
        # happens at the START of the segment described by this step.
        location: Coordinate | None = None
        interval = step.get("interval")
        if interval and len(interval) >= 1 and 0 <= interval[0] < len(points):
            location = points[interval[0]]

        instructions.append(RouteInstruction(
            text=step["text"],
            distance_m=step["distance"],
            street_name=step.get("street_name") or None,
            location=location,
            direction=_direction_from_sign(step.get("sign", 0)),
        ))

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
