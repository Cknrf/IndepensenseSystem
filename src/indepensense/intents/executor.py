"""Intent executor — runs the action described by an IntentResult.

Takes the running system's services (router, geocoder, GPS, telemetry)
via constructor injection so it can be unit-tested with mocks. Returns
the response text to be spoken to the user; the caller (polling loop) is
responsible for handing that text to a TTS engine.

For features that touch systems we haven't wired end-to-end yet (real
battery reading, cellular signal), the handler currently returns a
placeholder message. TODO comments mark the ones that need real
integration when those subsystems land.
"""
from datetime import datetime, timezone
from typing import Any

from indepensense.intents.base import Intent, IntentResult
from indepensense.routing.base import Coordinate, Geocoder, GeocodingResult, Route, Router
from indepensense.navigation.monitor import NavigationMonitor
from indepensense.sensors.base import GPSSensor
from indepensense.telemetry.base import AlertEvent, EventType, TelemetryClient


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
        telemetry: TelemetryClient | None = None,
        device_id: str = "",
        monitor: NavigationMonitor | None = None,
    ):
        self._router = router
        self._geocoder = geocoder
        self._gps = gps
        self._telemetry = telemetry
        self._device_id = device_id
        self._monitor = monitor

        self._current_route: Route | None = None

        # Last spoken response from any intent — repeated on demand
        # by NAVIGATION_REPEAT. We update this on every execute() call
        # EXCEPT when the intent itself is NAVIGATION_REPEAT (otherwise
        # the "nothing to repeat yet" message would become the last
        # response forever).
        self._last_response: str | None = None

    def execute(self, result: IntentResult) -> str:
        handler = self._handlers().get(result.intent, self._handle_unknown)
        try:
            response = handler(result)
        except Exception as exc:
            response = f"Sorry, something went wrong: {exc}"

        # Track the last spoken response so Repeat can replay it.
        # Skip when repeating so consecutive Repeats stay stable
        # (return the original response, not a chain of themselves).
        if result.intent != Intent.NAVIGATION_REPEAT:
            self._last_response = response
        return response

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

        # Always pass the user's position as a proximity bias. For chain
        # names ("Jollibee", "7-Eleven"), this returns the local branch
        # instead of a random one across the country. For specific named
        # places ("SM Manila"), Photon's text-match relevance still wins.
        hits = self._geocoder.geocode(location, limit=1, near=start)
        if not hits:
            return f"I couldn't find any place matching '{location}'."
        destination = hits[0]

        route = self._router.route(start, destination.coordinate, profile="foot")
        self._current_route = route

        # Hand the route to the navigation monitor so the app can start
        # firing turn-by-turn audio + haptic cues as the user walks.
        if self._monitor is not None:
            self._monitor.set_route(route, destination.name)

        first_instruction = (
            route.instructions[0].text if route.instructions else "Start walking."
        )

        return (
            f"Navigating to {destination.name}. "
            f"Total distance {route.distance_m:.0f} meters. "
            f"{first_instruction}"
        )

    def _handle_navigation_stop(self, result: IntentResult) -> str:
        if self._current_route is None:
            return "You don't have an active navigation."
        self._current_route = None
        if self._monitor is not None:
            self._monitor.clear()
        return "Navigation cancelled."

    def _handle_navigation_repeat(self, result: IntentResult) -> str:
        """Replay the wearable's last spoken response, regardless of
        which intent produced it.

        This is broader than "repeat the last navigation instruction" —
        any prior response (time query, location, error message,
        emergency confirmation) can be repeated. Handy when the user
        misses what the wearable said (traffic noise, distraction).
        """
        if self._last_response is None:
            return "There is nothing to repeat yet."
        return self._last_response

    def _handle_navigation_location(self, result: IntentResult) -> str:
        position = self._current_position()
        if position is None:
            return "I don't have a GPS fix yet."

        hit = self._geocoder.reverse(position)
        if hit is None:
            return f"You are near latitude {position.lat:.4f}, longitude {position.lon:.4f}."
        return _format_location_response(hit)

    def _handle_emergency_trigger(self, result: IntentResult) -> str:
        # If no telemetry client is wired up (dev / early integration),
        # acknowledge the intent locally without pretending we sent
        # anything to a guardian.
        if self._telemetry is None or not self._device_id:
            return "Emergency alert triggered locally. Guardian dashboard not connected."

        position = self._current_position()
        # If we have no GPS fix we still fire the alert — knowing WHERE the
        # user is helps the guardian, but knowing an emergency happened at
        # all is more important than knowing where. Backend accepts 0.0/0.0
        # as a valid coordinate; guardian dashboard shows a "location
        # unknown" marker.
        # TODO: replace with last-known GPS fix rather than 0.0/0.0 once
        # we cache the previous fix in the sensor layer.
        lat = position.lat if position is not None else 0.0
        lon = position.lon if position is not None else 0.0

        event = AlertEvent(
            device_id=self._device_id,
            event_type=EventType.EMERGENCY_ALERT,
            latitude=lat,
            longitude=lon,
            occurred_at=datetime.now(timezone.utc),
        )
        if self._telemetry.send_alert(event):
            return "Emergency alert sent to your guardian."
        return (
            "Emergency alert could not be sent right now. "
            "The system will keep trying in the background."
        )

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
        return "Sorry, I didn't catch that. Could you try again?"

    # --- helpers ------------------------------------------------------------

    def _current_position(self) -> Coordinate | None:
        if self._gps is None:
            return None
        fix = self._gps.read()
        if fix is None or fix.fix_quality == 0:
            return None
        return Coordinate(lat=fix.lat, lon=fix.lon)
