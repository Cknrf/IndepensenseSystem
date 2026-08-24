"""Intent executor — runs the action described by an IntentResult.

Takes the running system's services (router, geocoder, GPS, telemetry)
via constructor injection so it can be unit-tested with mocks. Returns
the response text to be spoken to the user; the caller (polling loop) is
responsible for handing that text to a TTS engine.

Language
--------

No response text lives in this file. Everything spoken comes from
`messages.get(key, language)`, and the language is read from a shared
`LanguageState` on every call rather than captured at construction —
the executor is built once at startup but must answer in whatever
language is active when a command arrives, including immediately after
it has just handled a switch request itself.

Sentence *structure* can differ per language too, not just wording: see
`_describe_scene`, where Tagalog's uninflected nouns take a different
path from English pluralisation.
"""
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from indepensense.intents import messages
from indepensense.intents.base import Intent, IntentResult
from indepensense.language import LanguageState
from indepensense.routing.base import Coordinate, Geocoder, GeocodingResult, Route, Router
from indepensense.navigation.monitor import NavigationMonitor, round_speech_distance
from indepensense.power.base import BatteryReader
from indepensense.sensors.base import GPSSensor
from indepensense.telemetry.base import AlertEvent, EventType, TelemetryClient
from indepensense.vision.base import Camera, Detection, Detector, OCR


def _format_location_response(hit: GeocodingResult, language: str) -> str:
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
        return messages.get(
            "location.near_coordinates",
            language,
            lat=f"{hit.coordinate.lat:.4f}",
            lon=f"{hit.coordinate.lon:.4f}",
        )
    return messages.get(
        "location.near_places",
        language,
        places=messages.join_items(parts, language),
    )


def _first_action_description(route: Route, language: str) -> str:
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
        return messages.get("nav.start_walking", language)

    # Find the first non-straight instruction and sum distances up to it.
    distance_to_action = 0.0
    for idx, instr in enumerate(route.instructions):
        if instr.direction in ("left", "right", "arrive"):
            if instr.direction == "arrive":
                if distance_to_action == 0.0:
                    return messages.get("nav.already_at_destination", language)
                return messages.get(
                    "nav.walk_to_arrive",
                    language,
                    distance=round_speech_distance(distance_to_action),
                )
            # left or right
            if distance_to_action == 0.0:
                return messages.get(
                    "nav.turn_immediately", language, instruction=instr.text,
                )
            return messages.get(
                "nav.turn_in_distance",
                language,
                distance=round_speech_distance(distance_to_action),
                instruction=instr.text,
            )
        distance_to_action += instr.distance_m

    # Fell through — no turns found at all. Return the first instruction
    # text as a fallback ("Head north on Elm Street").
    return route.instructions[0].text


# --- vision scene-description helpers ---------------------------------------

# Cap how many distinct object classes we mention in one description.
# YOLO can detect 20+ things in a crowded scene; reading them all takes
# too long and overwhelms the listener. Cap at 5 most-frequent classes.
_MAX_SCENE_ITEMS = 5


def _describe_scene(detections: list[Detection], language: str) -> str:
    """Build a spoken description from a list of YOLO detections.

    Groups by class label, counts instances, orders by frequency, caps to
    `_MAX_SCENE_ITEMS` classes so the response stays short.

    Number grammar is delegated to `messages.count_label` because it is
    genuinely different per language, not just differently worded:
    English inflects the noun ("2 chairs"), Tagalog leaves it bare with a
    counter ("2 upuan"). Pluralising Tagalog the English way would
    produce words that do not exist.
    """
    if not detections:
        return messages.get("vision.nothing_recognized", language)

    counts = Counter(d.class_name for d in detections)
    # `most_common` returns [(label, count), ...] sorted by count desc.
    ordered = counts.most_common(_MAX_SCENE_ITEMS)
    items = [messages.count_label(label, n, language) for label, n in ordered]
    return messages.get(
        "vision.i_see", language, items=messages.join_items(items, language),
    )


def _clean_ocr_text(text: str) -> str:
    """Turn Tesseract's raw output into a speech-friendly string.

    Tesseract emits real line breaks inside paragraphs (matching the
    source layout of the image). Piper reads those as awkward pauses.
    We flatten single line breaks to spaces, keep paragraph breaks
    (double line breaks) as a natural full stop + pause, and collapse
    runs of whitespace.
    """
    # Split into paragraphs on 2+ newlines, then rejoin single line
    # breaks within each paragraph as spaces.
    import re
    paragraphs = re.split(r"\n\s*\n", text)
    cleaned_paras = []
    for p in paragraphs:
        # Replace any remaining internal newlines/tabs with spaces,
        # then collapse multiple spaces into one.
        p = re.sub(r"[\n\t]+", " ", p)
        p = re.sub(r" {2,}", " ", p).strip()
        if p:
            cleaned_paras.append(p)
    # Join paragraphs with a full stop + space so Piper takes a real
    # pause between them.
    return ". ".join(cleaned_paras)


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
        ocr: OCR | None = None,
        language: LanguageState | None = None,
        ocr_max_chars: int = 500,
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
        self._ocr = ocr
        # Shared, mutable. Read via `self._lang` on every response so a
        # switch handled by this executor takes effect immediately.
        self._language = language or LanguageState(
            default=messages.FALLBACK_LANGUAGE, supported=messages.LANGUAGES,
        )
        self._ocr_max_chars = ocr_max_chars

        self._current_route: Route | None = None

        # Last spoken response from any intent — repeated on demand
        # by NAVIGATION_REPEAT. We update this on every execute() call
        # EXCEPT when the intent itself is NAVIGATION_REPEAT (otherwise
        # the "nothing to repeat yet" message would become the last
        # response forever).
        self._last_response: str | None = None

    @property
    def _lang(self) -> str:
        """The language to answer in, right now."""
        return self._language.current

    def execute(self, result: IntentResult) -> str:
        handler = self._handlers().get(result.intent, self._handle_unknown)
        try:
            response = handler(result)
        except Exception as exc:
            response = messages.get("generic.error", self._lang, error=exc)

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
            Intent.VISION_READ:         self._handle_vision_read,
            Intent.SYSTEM_LANGUAGE:     self._handle_system_language,
        }

    # --- handlers -----------------------------------------------------------

    def _handle_navigation_start(self, result: IntentResult) -> str:
        location = (result.parameters.get("location") or "").strip()
        if not location:
            return messages.get("nav.no_destination_heard", self._lang)

        start = self._current_position()
        if start is None:
            return messages.get("nav.no_gps_for_start", self._lang)

        # Always pass the user's position as a proximity bias. For chain
        # names ("Jollibee", "7-Eleven"), this returns the local branch
        # instead of a random one across the country. For specific named
        # places ("SM Manila"), Photon's text-match relevance still wins.
        hits = self._geocoder.geocode(location, limit=1, near=start)
        if not hits:
            return messages.get("nav.place_not_found", self._lang, location=location)
        destination = hits[0]

        route = self._router.route(start, destination.coordinate, profile="foot")
        self._current_route = route

        # Hand the route to the navigation monitor so the app can start
        # firing turn-by-turn audio + haptic cues as the user walks.
        if self._monitor is not None:
            self._monitor.set_route(route, destination.name)

        return messages.get(
            "nav.started",
            self._lang,
            destination=destination.name,
            distance=f"{route.distance_m:.0f}",
            first_action=_first_action_description(route, self._lang),
        )

    def _handle_navigation_stop(self, result: IntentResult) -> str:
        if self._current_route is None:
            return messages.get("nav.none_active", self._lang)
        self._current_route = None
        if self._monitor is not None:
            self._monitor.clear()
        return messages.get("nav.cancelled", self._lang)

    def _handle_navigation_repeat(self, result: IntentResult) -> str:
        """Replay the wearable's last spoken response, regardless of
        which intent produced it.

        This is broader than "repeat the last navigation instruction" —
        any prior response (time query, location, error message,
        emergency confirmation) can be repeated. Handy when the user
        misses what the wearable said (traffic noise, distraction).
        """
        if self._last_response is None:
            return messages.get("nav.nothing_to_repeat", self._lang)
        return self._last_response

    def _handle_navigation_location(self, result: IntentResult) -> str:
        position = self._current_position()
        if position is None:
            return messages.get("location.no_gps", self._lang)

        hit = self._geocoder.reverse(position)
        if hit is None:
            return messages.get(
                "location.near_coordinates",
                self._lang,
                lat=f"{position.lat:.4f}",
                lon=f"{position.lon:.4f}",
            )
        return _format_location_response(hit, self._lang)

    def _handle_emergency_trigger(self, result: IntentResult) -> str:
        # If no telemetry client is wired up (dev / early integration),
        # acknowledge the intent locally without pretending we sent
        # anything to a guardian.
        if self._telemetry is None or not self._device_id:
            return messages.get("emergency.local_only", self._lang)

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
            return messages.get("emergency.sent", self._lang)
        return messages.get("emergency.queued", self._lang)

    def _handle_device_status(self, result: IntentResult) -> str:
        field = result.parameters.get("status_field", "")

        if field == "battery":
            return self._describe_battery()

        if field == "gps":
            if self._gps is None:
                return messages.get("gps.not_configured", self._lang)
            fix = self._gps.read()
            if fix is None or fix.fix_quality == 0:
                return messages.get("gps.no_fix", self._lang)
            return messages.get(
                "gps.locked", self._lang, satellites=fix.satellites or 0,
            )

        if field == "signal":
            return self._describe_cellular_signal()

        return messages.get("generic.unknown_status_field", self._lang, field=field)

    def _describe_battery(self) -> str:
        """Build a spoken description of current battery state.

        Prefers the real UPS HAT reading; falls back to a stub message
        when no reader is wired (dev on Mac, HAT missing).
        """
        if self._battery is None:
            return messages.get("battery.unavailable", self._lang)
        try:
            reading = self._battery.read()
        except Exception:
            return messages.get("battery.read_failed", self._lang)
        if reading is None:
            return messages.get("battery.read_failed", self._lang)

        pct = reading.percentage
        if reading.is_charging:
            return messages.get("battery.charging", self._lang, percent=pct)
        if reading.time_to_empty_min > 0:
            hours = reading.time_to_empty_min // 60
            minutes = reading.time_to_empty_min % 60
            if hours > 0:
                return messages.get(
                    "battery.level_with_hours",
                    self._lang, percent=pct, hours=hours, minutes=minutes,
                )
            return messages.get(
                "battery.level_with_minutes", self._lang, percent=pct, minutes=minutes,
            )
        return messages.get("battery.level", self._lang, percent=pct)

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
            return messages.get("cellular.unavailable", self._lang)

        if r.returncode != 0:
            return messages.get("cellular.no_modem", self._lang)

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
            return messages.get("cellular.check_sim", self._lang)
        if state in ("disabled", "disabling"):
            return messages.get("cellular.disabled", self._lang)
        if state in ("searching", "enabling"):
            return messages.get("cellular.connecting", self._lang)

        if quality is None:
            return messages.get("cellular.no_quality", self._lang)
        if quality >= 60:
            return messages.get("cellular.strong", self._lang, quality=quality)
        if quality >= 30:
            return messages.get("cellular.medium", self._lang, quality=quality)
        return messages.get("cellular.weak", self._lang, quality=quality)

    def _handle_system_time(self, result: IntentResult) -> str:
        now = datetime.now()
        # e.g. "It's currently 2:34 PM." / "Ganap na 2:34 PM ngayon."
        return messages.get(
            "time.current", self._lang, time=now.strftime("%I:%M %p").lstrip("0"),
        )

    def _handle_vision_describe(self, result: IntentResult) -> str:
        """Capture a frame from the camera, run YOLO, describe what was found.

        Total latency on Pi 5: ~50 ms capture + ~500-1000 ms YOLOv8n
        inference. Runs on the voice thread so it doesn't block the
        main polling loop. Fails gracefully when the camera or detector
        is missing (dev on Mac, hardware not wired).
        """
        if self._camera is None or self._detector is None:
            return messages.get("vision.camera_unavailable", self._lang)

        try:
            frame = self._camera.capture()
        except Exception as exc:
            print(f"[vision] camera error: {exc}", file=sys.stderr, flush=True)
            return messages.get("vision.capture_failed", self._lang)
        if frame is None:
            return messages.get("vision.no_image", self._lang)

        try:
            detections = self._detector.detect(frame)
        except Exception as exc:
            print(f"[vision] detector error: {exc}", file=sys.stderr, flush=True)
            return messages.get("vision.analyze_failed", self._lang)

        return _describe_scene(detections, self._lang)

    def _handle_vision_read(self, result: IntentResult) -> str:
        """Capture a frame, run Tesseract OCR, speak the extracted text.

        Fails gracefully when the camera or OCR is missing (dev on Mac,
        Tesseract not installed). Truncates long text so a full receipt
        doesn't turn into a 90-second Piper monologue.

        Uses `self._system_language` to pick which Tesseract language
        pack to invoke — same code the rest of the wearable uses for
        STT and TTS, so all language-aware components stay in sync.
        """
        if self._camera is None or self._ocr is None:
            return messages.get("vision.camera_unavailable", self._lang)

        try:
            frame = self._camera.capture()
        except Exception as exc:
            print(f"[ocr] camera error: {exc}", file=sys.stderr, flush=True)
            return messages.get("vision.capture_failed", self._lang)
        if frame is None:
            return messages.get("vision.no_image", self._lang)

        try:
            text = self._ocr.read_text(frame, language=self._lang)
        except Exception as exc:
            print(f"[ocr] tesseract error: {exc}", file=sys.stderr, flush=True)
            return messages.get("vision.read_failed", self._lang)

        text = text.strip()
        if not text:
            return messages.get("vision.no_text", self._lang)

        # Collapse internal whitespace — Tesseract emits raw line breaks
        # that sound choppy when Piper reads them. Preserve paragraphs
        # but replace newlines within a paragraph with spaces.
        text = _clean_ocr_text(text)

        if len(text) > self._ocr_max_chars:
            text = text[: self._ocr_max_chars].rstrip() + messages.get(
                "vision.truncated_suffix", self._lang,
            )
        return text

    def _handle_system_language(self, result: IntentResult) -> str:
        """Switch the system language.

        The confirmation is deliberately spoken in the language being
        switched *to*, so hearing it verifies the switch actually took
        effect. A user who asks for English and hears Tagalog knows
        immediately that something is wrong — which matters for a device
        whose user cannot read a settings screen.
        """
        target = (result.parameters.get("language") or "").strip().lower()
        if not self._language.is_supported(target):
            return messages.get("language.unsupported", self._lang)
        if not self._language.set(target):
            # Supported but unchanged — already speaking it.
            return messages.get("language.already", target)
        return messages.get("language.switched", target)

    def _handle_unknown(self, result: IntentResult) -> str:
        return messages.get("generic.unknown_intent", self._lang)

    # --- helpers ------------------------------------------------------------

    def _current_position(self) -> Coordinate | None:
        if self._gps is None:
            return None
        fix = self._gps.read()
        if fix is None or fix.fix_quality == 0:
            return None
        return Coordinate(lat=fix.lat, lon=fix.lon)
