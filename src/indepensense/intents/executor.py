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
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from indepensense.intents.base import Intent, IntentResult
from indepensense.routing.base import Coordinate, Geocoder, GeocodingResult, Route, Router
from indepensense.navigation.monitor import NavigationMonitor, round_speech_distance
from indepensense.power.base import BatteryReader
from indepensense.sensors.base import GPSSensor
from indepensense.telemetry.base import AlertEvent, EventType, TelemetryClient
from indepensense.vision.base import Camera, Detection, Detector


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


def _first_action_description(route: Route) -> str:
    """Build the "what to do first" sentence for the initial nav response.

    GraphHopper's first instruction is usually "Head [direction] on
    [street]" — a starter, not a turn. If we said just that, the user
    would only hear about the starter and miss knowing when the first
    TURN is coming. So this helper looks for the first non-straight
    instruction (a left, right, or arrive) and phrases the response
    around it:

      "In 120 meters, turn left onto Second Avenue."     (turn follows starter)
      "Walk 120 meters to arrive."                        (short route, no turns)
      "Turn left onto Second Avenue immediately."         (rare — no starter)

    Distance is rounded to a speech-friendly number so Piper says
    "120 meters" rather than "117 point 3 meters".
    """
    if not route.instructions:
        return "Start walking."

    # Find the first non-straight instruction and sum distances up to it.
    distance_to_action = 0.0
    for idx, instr in enumerate(route.instructions):
        if instr.direction in ("left", "right", "arrive"):
            if instr.direction == "arrive":
                if distance_to_action == 0.0:
                    return "You are already at your destination."
                rounded = round_speech_distance(distance_to_action)
                return f"Walk {rounded} meters to arrive at your destination."
            # left or right
            if distance_to_action == 0.0:
                return f"{instr.text} immediately."
            rounded = round_speech_distance(distance_to_action)
            return f"In {rounded} meters, {instr.text}."
        distance_to_action += instr.distance_m

    # Fell through — no turns found at all. Return the first instruction
    # text as a fallback ("Head north on Elm Street").
    return route.instructions[0].text


# --- vision scene-description helpers ---------------------------------------

# COCO class labels that need irregular plural forms. Everything else
# gets the naive suffix rules in `_pluralize()`.
_IRREGULAR_PLURALS: dict[str, str] = {
    "person": "people",
    "child": "children",
    "mouse": "mice",       # COCO's "mouse" is a computer mouse
    "foot": "feet",
    "tooth": "teeth",
}

# Cap how many distinct object classes we mention in one description.
# YOLO can detect 20+ things in a crowded scene; reading them all takes
# too long and overwhelms the listener. Cap at 5 most-frequent classes.
_MAX_SCENE_ITEMS = 5


def _pluralize(label: str, count: int) -> str:
    """English plural + article. "1 chair" → "a chair", "2 chairs" → "2 chairs"."""
    if count == 1:
        article = "an" if label[:1].lower() in "aeiou" else "a"
        return f"{article} {label}"
    plural = _IRREGULAR_PLURALS.get(label)
    if plural is None:
        # Basic English pluralization rules — good enough for COCO labels.
        if label.endswith(("s", "x", "z", "ch", "sh")):
            plural = label + "es"
        elif label.endswith("y") and len(label) >= 2 and label[-2] not in "aeiou":
            plural = label[:-1] + "ies"
        else:
            plural = label + "s"
    return f"{count} {plural}"


def _join_items(items: list[str]) -> str:
    """Comma-and join for spoken lists: [a, b, c] → 'a, b, and c'."""
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + ", and " + items[-1]


def _describe_scene(detections: list[Detection]) -> str:
    """Build a spoken description from a list of YOLO detections.

    Groups by class label, counts instances, orders by frequency, caps
    to `_MAX_SCENE_ITEMS` classes so the response stays short. Uses
    natural English plurals and articles.
    """
    if not detections:
        return "I don't see anything I recognize right now."

    counts = Counter(d.class_name for d in detections)
    # `most_common` returns [(label, count), ...] sorted by count desc.
    ordered = counts.most_common(_MAX_SCENE_ITEMS)
    items = [_pluralize(label, n) for label, n in ordered]
    return "I see " + _join_items(items) + "."


class IntentExecutor:
    def __init__(
        self,
        router: Router,
        geocoder: Geocoder,
        gps: GPSSensor | None = None,
        telemetry: TelemetryClient | None = None,
        device_id: str = "",
        monitor: NavigationMonitor | None = None,
        battery: BatteryReader | None = None,
        camera: Camera | None = None,
        detector: Detector | None = None,
    ):
        self._router = router
        self._geocoder = geocoder
        self._gps = gps
        self._telemetry = telemetry
        self._device_id = device_id
        self._monitor = monitor
        self._battery = battery
        self._camera = camera
        self._detector = detector

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
            Intent.VISION_DESCRIBE:     self._handle_vision_describe,
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

        return (
            f"Navigating to {destination.name}. "
            f"Total distance {route.distance_m:.0f} meters. "
            f"{_first_action_description(route)}"
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
            return self._describe_battery()

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
            return self._describe_cellular_signal()

        return f"I don't know how to report on '{field}'."

    def _describe_battery(self) -> str:
        """Build a spoken description of current battery state.

        Prefers the real UPS HAT reading; falls back to a stub message
        when no reader is wired (dev on Mac, HAT missing).
        """
        if self._battery is None:
            return "Battery monitoring is not available on this device."
        try:
            reading = self._battery.read()
        except Exception:
            return "I couldn't read the battery status right now."
        if reading is None:
            return "I couldn't read the battery status right now."

        pct = reading.percentage
        if reading.is_charging:
            return f"Battery is at {pct} percent and charging."
        if reading.time_to_empty_min > 0:
            hours = reading.time_to_empty_min // 60
            minutes = reading.time_to_empty_min % 60
            if hours > 0:
                return (
                    f"Battery is at {pct} percent, "
                    f"about {hours} hours and {minutes} minutes remaining."
                )
            return (
                f"Battery is at {pct} percent, "
                f"about {minutes} minutes remaining."
            )
        return f"Battery is at {pct} percent."

    def _describe_cellular_signal(self) -> str:
        """Query ModemManager for cellular state + signal quality.

        Uses `mmcli -m any -K` (key=value output) so the parse is
        stable across versions. Handles the common failure modes
        gracefully:

          - mmcli not installed → generic unavailable message
          - no modem detected → clear message
          - modem in `failed` state (e.g. SIM missing) → tells the user
          - modem disabled → tells the user
          - registered but no quality data → says so
          - connected with quality → strength as strong/medium/weak
        """
        import subprocess

        try:
            r = subprocess.run(
                ["mmcli", "-m", "any", "-K"],
                capture_output=True,
                text=True,
                timeout=3.0,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "Cellular status is not available on this device."

        if r.returncode != 0:
            return "No cellular modem is detected."

        state = ""
        quality: int | None = None
        for line in r.stdout.splitlines():
            if "modem.generic.state " in line and ":" in line:
                state = line.split(":", 1)[1].strip()
            elif "signal-quality.value" in line and ":" in line:
                try:
                    quality = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass

        if "failed" in state:
            return "Cellular is unavailable. Check that the SIM card is inserted."
        if state in ("disabled", "disabling"):
            return "Cellular is disabled."
        if state in ("searching", "enabling"):
            return "Cellular is still connecting."

        if quality is None:
            return "Cellular is connected, but signal strength is not reported."
        if quality >= 60:
            return f"Cellular signal is strong, at {quality} percent."
        if quality >= 30:
            return f"Cellular signal is medium, at {quality} percent."
        return f"Cellular signal is weak, at {quality} percent."

    def _handle_system_time(self, result: IntentResult) -> str:
        now = datetime.now()
        # e.g. "It's currently 2:34 PM."
        return f"It's currently {now.strftime('%I:%M %p').lstrip('0')}."

    def _handle_vision_describe(self, result: IntentResult) -> str:
        """Capture a frame from the camera, run YOLO, describe what was found.

        Total latency on Pi 5: ~50 ms capture + ~500-1000 ms YOLOv8n
        inference. Runs on the voice thread so it doesn't block the
        main polling loop. Fails gracefully when the camera or detector
        is missing (dev on Mac, hardware not wired).
        """
        if self._camera is None or self._detector is None:
            return "The camera is not available on this device."

        try:
            frame = self._camera.capture()
        except Exception as exc:
            print(f"[vision] camera error: {exc}", file=sys.stderr, flush=True)
            return "I couldn't take a photo right now. Please try again."
        if frame is None:
            return "The camera returned no image."

        try:
            detections = self._detector.detect(frame)
        except Exception as exc:
            print(f"[vision] detector error: {exc}", file=sys.stderr, flush=True)
            return "I couldn't analyze the image right now. Please try again."

        return _describe_scene(detections)

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
