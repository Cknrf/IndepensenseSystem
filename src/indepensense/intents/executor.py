"""Intent executor — runs the action described by an IntentResult.

Takes the running system's services (router, geocoder, GPS, ...) via
constructor injection so it can be unit-tested with mocks. Returns the
response text to be spoken to the user; the caller (polling loop) is
responsible for handing that text to a TTS engine.

For features that touch systems we haven't wired end-to-end yet (guardian
alerts, real battery reading, cellular signal), the handler currently
returns a placeholder message. TODO comments mark the ones that need real
integration when those subsystems land.
"""
from datetime import datetime
from typing import Any

from indepensense.intents.base import Intent, IntentResult
from indepensense.routing.base import Coordinate, Geocoder, GeocodingResult, Route, Router
from indepensense.sensors.base import GPSSensor


def _format_location_response(hit: GeocodingResult) -> str:
    """Build a spoken location description from a reverse-geocode hit.

    Combines up to four fields (name, street, district, city) into a natural
    "You are near A, B, C" sentence. De-duplicates so we never repeat the
    same string twice — Photon sometimes returns the same value as `name`
    and `district`, or `name` and `city`.
    """
    parts: list[str] = []
    seen: set[str] = set()

    def _add(value: str | None) -> None:
        if not value:
            return
        key = value.strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        parts.append(value.strip())

    _add(hit.name)
    _add(hit.street)
    _add(hit.district)
    _add(hit.city)

    if not parts:
        return (
            f"You are near latitude {hit.coordinate.lat:.4f}, "
            f"longitude {hit.coordinate.lon:.4f}."
        )
    return "You are near " + ", ".join(parts) + "."


class IntentExecutor:
    def __init__(
        self,
        router: Router,
        geocoder: Geocoder,
        gps: GPSSensor | None = None,
    ):
        self._router = router
        self._geocoder = geocoder
        self._gps = gps

        self._current_route: Route | None = None
        self._last_instruction: str | None = None

    def execute(self, result: IntentResult) -> str:
        handler = self._handlers().get(result.intent, self._handle_unknown)
        try:
            return handler(result)
        except Exception as exc:
            return f"Sorry, something went wrong: {exc}"

    def _handlers(self) -> dict[Intent, Any]:
        return {
            Intent.NAVIGATION_START:    self._handle_navigation_start,
            Intent.NAVIGATION_STOP:     self._handle_navigation_stop,
            Intent.NAVIGATION_REPEAT:   self._handle_navigation_repeat,
            Intent.NAVIGATION_LOCATION: self._handle_navigation_location,
            Intent.EMERGENCY_TRIGGER:   self._handle_emergency_trigger,
            Intent.DEVICE_STATUS:       self._handle_device_status,
            Intent.SYSTEM_TIME:         self._handle_system_time,
        }

    # --- handlers -----------------------------------------------------------

    def _handle_navigation_start(self, result: IntentResult) -> str:
        location = (result.parameters.get("location") or "").strip()
        if not location:
            return "I didn't hear where you want to go. Please try again."

        start = self._current_position()
        if start is None:
            return "I can't start navigation without a GPS fix yet."

        hits = self._geocoder.geocode(location, limit=1)
        if not hits:
            return f"I couldn't find any place matching '{location}'."
        destination = hits[0]

        route = self._router.route(start, destination.coordinate, profile="foot")
        self._current_route = route

        first_instruction = (
            route.instructions[0].text if route.instructions else "Start walking."
        )
        self._last_instruction = first_instruction

        return (
            f"Navigating to {destination.name}. "
            f"Total distance {route.distance_m:.0f} meters. "
            f"{first_instruction}"
        )

    def _handle_navigation_stop(self, result: IntentResult) -> str:
        if self._current_route is None:
            return "You don't have an active navigation."
        self._current_route = None
        self._last_instruction = None
        return "Navigation cancelled."

    def _handle_navigation_repeat(self, result: IntentResult) -> str:
        if self._last_instruction is None:
            return "There is no instruction to repeat yet."
        return self._last_instruction

    def _handle_navigation_location(self, result: IntentResult) -> str:
        position = self._current_position()
        if position is None:
            return "I don't have a GPS fix yet."

        hit = self._geocoder.reverse(position)
        if hit is None:
            return f"You are near latitude {position.lat:.4f}, longitude {position.lon:.4f}."
        return _format_location_response(hit)

    def _handle_emergency_trigger(self, result: IntentResult) -> str:
        # TODO: when telemetry / guardian dashboard lands, POST an alert here
        # including current GPS + timestamp + user context.
        return "Emergency alert triggered. Notifying your guardian now."

    def _handle_device_status(self, result: IntentResult) -> str:
        field = result.parameters.get("status_field", "")

        if field == "battery":
            # TODO: read from an actual power-monitoring HAT when installed.
            # Pi 5 has no built-in battery sensing.
            return "Battery status is not yet monitored on this prototype."

        if field == "gps":
            if self._gps is None:
                return "GPS is not configured on this device."
            fix = self._gps.read()
            if fix is None or fix.fix_quality == 0:
                return "GPS has no fix at the moment."
            return (
                f"GPS is locked with {fix.satellites or 0} satellites. "
                f"Signal quality is good."
            )

        if field == "signal":
            # TODO: read from ModemManager (mmcli -m any) for LTE signal.
            return "Cellular signal reporting is not yet implemented."

        return f"I don't know how to report on '{field}'."

    def _handle_system_time(self, result: IntentResult) -> str:
        now = datetime.now()
        # e.g. "It's currently 2:34 PM."
        return f"It's currently {now.strftime('%I:%M %p').lstrip('0')}."

    def _handle_unknown(self, result: IntentResult) -> str:
        return "Sorry, I didn't understand that. Please try again."

    # --- helpers ------------------------------------------------------------

    def _current_position(self) -> Coordinate | None:
        if self._gps is None:
            return None
        fix = self._gps.read()
        if fix is None or fix.fix_quality == 0:
            return None
        return Coordinate(lat=fix.lat, lon=fix.lon)
