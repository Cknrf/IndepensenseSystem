"""HTTP client for a local GraphHopper routing service.

See `docs/graphhopper.md` for the service setup. This module assumes a server
listening on `GRAPHHOPPER_URL` with the `foot` profile configured.
"""
from typing import Any

from indepensense.routing.base import Coordinate, Route, RouteInstruction

_DEFAULT_TIMEOUT_S = 10.0


# GraphHopper's `sign` codes, from `Instruction.java` in the 11.0 source
# that `docs/graphhopper.md` pins. Three of these were previously
# documented wrong and two of those were acted on: -8 is U_TURN_LEFT (not
# KEEP_LEFT), -7 is KEEP_LEFT (not TURN_SHARP_LEFT), and 6 is
# USE_ROUNDABOUT (not U_TURN_UNKNOWN).
#
# 6 was the one that mattered. It fell through to the old `sign > 0`
# catch-all and came out as "turn right", which at a rotonda — and they
# are common here — is an instruction to walk into the circle. The error
# got worse rather than better when cue wording moved into `messages.py`:
# the router's own text used to carry the truth alongside the wrong
# direction, and now the direction is all there is.
#
# The collapse itself is deliberate. Slight, sharp and normal all become
# one word, because GraphHopper's split comes from road geometry and is
# not reliably the distinction a pedestrian sees at a real Batangas
# intersection, and because the cue at the junction is two words by
# design. What must not collapse is a turn into a different *kind* of
# manoeuvre, which is exactly what the roundabout and u-turn codes are.
_SIGN_DIRECTIONS = {
    -99: "straight",     # UNKNOWN — the router declining to say
    -98: "uturn",        # U_TURN_UNKNOWN
    -8:  "uturn",        # U_TURN_LEFT
    -7:  "left",         # KEEP_LEFT — a fork, close enough to a left
    -6:  "straight",     # LEAVE_ROUNDABOUT — reserved, never emitted
    -3:  "left",         # TURN_SHARP_LEFT
    -2:  "left",         # TURN_LEFT
    -1:  "left",         # TURN_SLIGHT_LEFT
    0:   "straight",     # CONTINUE_ON_STREET
    1:   "right",        # TURN_SLIGHT_RIGHT
    2:   "right",        # TURN_RIGHT
    3:   "right",        # TURN_SHARP_RIGHT
    4:   "arrive",       # FINISH
    5:   "waypoint",     # REACHED_VIA
    6:   "roundabout",   # USE_ROUNDABOUT
    7:   "right",        # KEEP_RIGHT
    8:   "uturn",        # U_TURN_RIGHT
}


def _direction_from_sign(sign: int) -> str:
    """Map GraphHopper's turn `sign` code to our simplified direction.

    An unlisted code keeps GraphHopper's own convention that negative is
    leftward and positive rightward. That is a guess, and it is only
    reachable if the router gains a code this table does not know — the
    public-transport signs (101-103) being the live example, which the
    foot profile never emits. Guessing a side beats saying nothing for a
    user who is walking and has to do *something* at the junction.
    """
    direction = _SIGN_DIRECTIONS.get(sign)
    if direction is not None:
        return direction
    return "left" if sign < 0 else "right"


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
        point_index: int | None = None
        interval = step.get("interval")
        if interval and len(interval) >= 1 and 0 <= interval[0] < len(points):
            point_index = interval[0]
            location = points[point_index]

        instructions.append(RouteInstruction(
            text=step["text"],
            distance_m=step["distance"],
            street_name=step.get("street_name") or None,
            location=location,
            point_index=point_index,
            direction=_direction_from_sign(step.get("sign", 0)),
            # Only roundabout instructions carry this.
            exit_number=step.get("exit_number"),
        ))

    return Route(
        distance_m=path["distance"],
        duration_s=path["time"] / 1000.0,
        instructions=instructions,
        points=points,
    )


def _error_detail(response) -> str:
    """GraphHopper's own explanation for a failed request.

    `raise_for_status()` reports only "500 Server Error for url: ...",
    which is the one thing the caller already knew. GraphHopper puts the
    actual reason in the body — "Cannot find point 1", "Unknown profile",
    the summary of a server-side exception — and throwing that away sent
    a field test to `journalctl` for something that had already been
    returned over the wire, and spoke "Sorry, something went wrong" to a
    user who could have been told the destination was unreachable.

    Falls back to raw text, then to nothing at all: this runs while
    something is already broken, and it must not add a second failure on
    top of the first.
    """
    try:
        payload = response.json()
    except Exception:
        return (response.text or "").strip()[:300] or "no detail in response"
    if isinstance(payload, dict):
        message = payload.get("message")
        if message:
            hints = payload.get("hints") or []
            extra = [
                h["details"] for h in hints
                if isinstance(h, dict) and h.get("details")
                and h.get("details") != message
            ]
            return f"{message} ({'; '.join(extra)})" if extra else str(message)
    return str(payload)[:300]


class GraphHopperRouter:
    def __init__(self, base_url: str, timeout_s: float = _DEFAULT_TIMEOUT_S):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def route(
        self,
        start: Coordinate,
        end: Coordinate,
        profile: str = "foot",
        heading: float | None = None,
    ) -> Route:
        """Ask GraphHopper for a pedestrian route.

        `heading` biases the departure direction. GraphHopper applies a
        `heading_penalty` (300 s by default) to paths that set off against
        it, which makes "carry on the way you are facing" win unless going
        back is genuinely much shorter. Omitted entirely when None, so a
        request without a heading is byte-identical to what this sent
        before the parameter existed.
        """
        import requests  # lazy: keeps imports cheap on cold starts

        params = [
            ("point", f"{start.lat},{start.lon}"),
            ("point", f"{end.lat},{end.lon}"),
            ("profile", profile),
            ("points_encoded", "false"),
            ("instructions", "true"),
        ]
        if heading is not None:
            # Normalised because GraphHopper rejects values outside 0-360,
            # and a heading arriving as -10 or 375 is a caller's arithmetic
            # rather than a reason to fail the whole route request.
            params.append(("heading", f"{heading % 360:.0f}"))
            # `heading` is incompatible with contraction hierarchies, and
            # GraphHopper rejects the pair outright:
            #
            #   400 ... The 'heading' parameter is currently not supported
            #   for speed mode, you need to disable speed mode with
            #   `ch.disable=true`. See issue #483
            #
            # CH pre-computes shortest paths between contracted nodes, so
            # the first edge out of the start is already baked in and
            # cannot be biased after the fact. Asking for both is asking
            # for a shortcut that was never computed.
            #
            # Latent until the compass was calibrated: with
            # `COMPASS_CALIBRATED = False` the caller passed None, no
            # heading was sent, and CH served every route. Turning the
            # compass on turned every navigation request into a 400.
            #
            # The cost is real but small here. Without CH, GraphHopper
            # falls back to a bidirectional A* over the raw graph —
            # slower, but this graph is one province, not a continent,
            # and a departure bias that stops the wearer being told to
            # turn around is worth more than the milliseconds.
            params.append(("ch.disable", "true"))
        response = requests.get(
            f"{self._base_url}/route",
            params=params,
            timeout=self._timeout_s,
        )
        if not response.ok:
            raise requests.HTTPError(
                f"{response.status_code} from GraphHopper: "
                f"{_error_detail(response)}",
                response=response,
            )
        return parse_graphhopper_response(response.json())
