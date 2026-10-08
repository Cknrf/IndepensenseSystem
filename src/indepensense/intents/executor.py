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
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Callable

from indepensense.intents import messages
from indepensense.intents.base import CloudAnswerer, Intent, IntentResult
from indepensense.language import LanguageState
from indepensense.routing.base import (
    Coordinate,
    Geocoder,
    GeocodingResult,
    Route,
    Router,
    haversine_m,
)
from indepensense.routing.places import SavedPlaces
from indepensense.routing.ranking import rank_candidates
from indepensense.navigation.monitor import NavigationMonitor
from indepensense.power.base import BatteryReader
from indepensense.sensors.base import GPSSensor
from indepensense.telemetry.base import AlertEvent, EventType, TelemetryClient
from indepensense.vision.base import Camera, Detection, Detector, OCR
from indepensense.voice.volume import VolumeState


def _place_parts(hit: GeocodingResult, *fields: str) -> list[str]:
    """Pull the named `GeocodingResult` fields, skipping blanks and repeats.

    Photon regularly returns the same string as `name` and `district`, or
    `name` and `city`, and speaking "Jollibee, Jollibee, Lipa City" sounds
    broken. De-duplication is case-insensitive; the first spelling wins.
    """
    parts: list[str] = []
    seen: set[str] = set()
    for field in fields:
        value = getattr(hit, field, None)
        if not value:
            continue
        key = value.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        parts.append(value.strip())
    return parts


def _describe_destination(hit: GeocodingResult) -> str:
    """Name a geocoded place precisely enough to tell branches apart.

    Street is what actually distinguishes one Jollibee from another, so it
    matters more here than in `_format_location_response` — this string is
    the user's only chance to catch a wrong pick before they start walking.
    Comma-joined rather than run through `join_items`: this is an address,
    and "Jollibee, B. Morada Avenue, and Lipa City" reads as a list of three
    separate places.
    """
    parts = _place_parts(hit, "name", "street", "city")
    return ", ".join(parts) if parts else hit.name


def _format_location_response(hit: GeocodingResult, language: str) -> str:
    """Build a spoken location description from a reverse-geocode hit.

    Combines up to four fields (name, street, district, city) into a natural
    "You are near A, B, C" sentence.
    """
    parts = _place_parts(hit, "name", "street", "district", "city")

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
                    distance=messages.speak_distance(distance_to_action, language),
                )
            # left or right
            if distance_to_action == 0.0:
                return messages.get(
                    "nav.turn_immediately", language, instruction=instr.text,
                )
            return messages.get(
                "nav.turn_in_distance",
                language,
                distance=messages.speak_distance(distance_to_action, language),
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

# Cap on saved-place labels read aloud in one answer, for the same reason
# `_MAX_SCENE_ITEMS` exists: speech is serial and a long list is a wait,
# not information. The count of what was held back is spoken, so the
# number is never silently wrong — and the repeat button stops playback
# mid-sentence for anyone who has heard enough.
_MAX_SPOKEN_PLACES = 6

# ModemManager's access-technology names, mapped to the generation people
# actually say. mmcli reports the radio standard (`lte`, `umts`, `hspa`);
# nobody asks whether they are on UMTS.
#
# Spoken as a bare "4G" rather than translated, because the generation
# names are read identically in both languages — a Tagalog speaker asks
# for "apat G" no more than an English one asks for "fourth generation".
#
# Not in `messages.py` despite being user-facing: these are mmcli's
# vocabulary, and the mapping is protocol knowledge about what that tool
# emits rather than a sentence anyone would translate. An unrecognised
# value maps to nothing and the generation is simply left unsaid — a
# wrong generation is worse than no generation, and new radio standards
# keep arriving.
_NETWORK_GENERATIONS = {
    "5gnr": "5G",
    "lte": "4G",
    "hspa+": "3G",
    "hspa": "3G",
    "hsupa": "3G",
    "hsdpa": "3G",
    "umts": "3G",
    "edge": "2G",
    "gprs": "2G",
    "gsm": "2G",
}


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
        cloud: CloudAnswerer | None = None,
        # Asks the user to approve a destination and returns their answer.
        # Injected rather than called directly because confirming needs
        # speech and a button press, which this class must stay free of —
        # tests pass a lambda, `app.py` passes the real thing.
        confirmer: Callable[[str], bool] | None = None,
        # Arms the power-off. Called only after the user has confirmed,
        # and must NOT power the device off itself — the goodbye has not
        # been spoken yet at that point. `app.py` sets a flag here and
        # acts on it once playback finishes; tests pass a recorder.
        shutdown: Callable[[], None] | None = None,
        # Places the user named themselves. None disables saving and
        # falls back to geocoding every destination, which is what the
        # wearable did before this existed.
        places: SavedPlaces | None = None,
        # Speaker volume. None means the wearable cannot change it —
        # it stays at whatever the OS default is and says so.
        volume: VolumeState | None = None,
        # Returns the user's current heading in degrees, or None when
        # it is unknown or not yet trustworthy. A callable rather than
        # a value because the user turns; the executor is built once.
        heading: Callable[[], float | None] | None = None,
        # Distance in cm to whatever the forward ultrasonic sees, or None.
        # A callable for the same reason `heading` is one: the world moves
        # and the executor is built once. Lets `vision.describe` answer
        # with a distance when the camera recognised nothing, instead of
        # "I don't see anything I recognize" while a sensor on the same
        # device has an obstacle at 42 cm.
        obstacle_ahead: Callable[[], float | None] | None = None,
        ocr_max_chars: int = 500,
        cloud_max_chars: int = 500,
        # How long a cloud exchange stays usable as follow-up context.
        cloud_context_ttl_s: float = 120.0,
        geocode_candidate_limit: int = 10,
        # True when the telemetry client reports per-channel delivery
        # afterwards (see `telemetry/sms_alerts.py`), which the runtime
        # always wires — with or without an SMS sender. The emergency
        # response then only acknowledges the dispatch and lets that
        # report state the outcome. False — no notifier, as in unit tests
        # — answers from `send_alert`'s own result, because nothing else
        # is coming.
        reports_delivery: bool = False,
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
        self._cloud = cloud
        self._confirmer = confirmer
        self._shutdown = shutdown
        self._places = places
        self._volume = volume
        self._heading = heading
        self._obstacle_ahead = obstacle_ahead
        self._ocr_max_chars = ocr_max_chars
        self._cloud_max_chars = cloud_max_chars
        self._cloud_context_ttl_s = cloud_context_ttl_s
        self._geocode_candidate_limit = geocode_candidate_limit
        self._reports_delivery = reports_delivery

        self._current_route: Route | None = None

        # Last spoken response from any intent — repeated on demand
        # by NAVIGATION_REPEAT. We update this on every execute() call
        # EXCEPT when the intent itself is NAVIGATION_REPEAT (otherwise
        # the "nothing to repeat yet" message would become the last
        # response forever).
        self._last_response: str | None = None

        # The last cloud question, its answer, and when it was asked.
        # Passed back to the provider so a follow-up resolves — "what is
        # the tallest mountain" then "what about the second" — which
        # otherwise cannot be answered at all. One turn, not a history:
        # see `_recent_exchange`.
        self._last_exchange: tuple[str, str, float] | None = None

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
            Intent.NAVIGATION_PROGRESS: self._handle_navigation_progress,
            Intent.EMERGENCY_TRIGGER:   self._handle_emergency_trigger,
            Intent.GUARDIAN_STATUS_OK:  self._handle_guardian_status_ok,
            Intent.SYSTEM_SHUTDOWN:     self._handle_system_shutdown,
            Intent.DEVICE_STATUS:       self._handle_device_status,
            Intent.SYSTEM_TIME:         self._handle_system_time,
            Intent.VISION_DESCRIBE:     self._handle_vision_describe,
            Intent.VISION_READ:         self._handle_vision_read,
            Intent.SYSTEM_LANGUAGE:     self._handle_system_language,
            Intent.SYSTEM_HELP:         self._handle_system_help,
            Intent.SYSTEM_VOLUME:       self._handle_system_volume,
            Intent.PLACE_SAVE:          self._handle_place_save,
            Intent.PLACE_LIST:          self._handle_place_list,
            Intent.PLACE_LOCATE:        self._handle_place_locate,
            Intent.PLACE_DELETE:        self._handle_place_delete,
        }

    # --- handlers -----------------------------------------------------------

    def _handle_navigation_start(self, result: IntentResult) -> str:
        location = (result.parameters.get("location") or "").strip()
        if not location:
            return messages.get("nav.no_destination_heard", self._lang)

        start = self._current_position()
        if start is None:
            return messages.get("nav.no_gps_for_start", self._lang)

        # A place the user saved themselves wins outright, and skips both
        # the geocoder and the confirmation. There is nothing to
        # disambiguate — they named this exact spot while standing in it —
        # and asking them to approve their own "home" every time would be
        # noise. It is also the only destination that resolves with no
        # network at all, which is the point of the feature.
        destination = self._saved_destination(location)

        if destination is None:
            # Ask for several candidates and decide locally. Photon's own
            # ordering blends text relevance with an opaque location bias, so
            # taking its first result means accepting a choice we cannot
            # inspect — which is how "Jollibee" resolved to a branch 700 km
            # away. `near` still biases the search; ranking decides the answer.
            hits = self._geocoder.geocode(
                location, limit=self._geocode_candidate_limit, near=start,
            )
            if not hits:
                # Say so explicitly when the user keeps a list of their
                # own and this was not on it. They cannot glance at that
                # list, so without this a misheard label is
                # indistinguishable from a place that does not exist.
                key = (
                    "nav.place_not_found_nor_saved"
                    if self._places is not None and len(self._places) > 0
                    else "nav.place_not_found"
                )
                return messages.get(key, self._lang, location=location)

            ranked = rank_candidates(
                hits,
                origin=start,
                query=location,
                prefer_nearest=bool(result.parameters.get("nearest", False)),
            )
            destination = ranked[0]

            # Read the choice back before committing to it. Ranking makes the
            # right pick far more likely but cannot make it certain — the user
            # is the only one who knows which Jollibee they meant, and they
            # cannot glance at a map to check. Declining costs one repeated
            # command; walking the wrong way costs much more.
            if not self._confirm_destination(destination, start):
                return messages.get("nav.confirm_declined", self._lang)

        # Which way the user is facing, so the route does not open by
        # telling them to turn around. Unknown — including whenever the
        # compass is uncalibrated — simply omits the bias.
        route = self._router.route(
            start,
            destination.coordinate,
            profile="foot",
            heading=self._current_heading(),
        )
        self._current_route = route

        # Hand the route to the navigation monitor so the app can start
        # firing turn-by-turn audio + haptic cues as the user walks.
        if self._monitor is not None:
            self._monitor.set_route(route, destination.name)

        return messages.get(
            "nav.started",
            self._lang,
            destination=destination.name,
            distance=messages.speak_distance(route.distance_m, self._lang),
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

    def _handle_navigation_progress(self, result: IntentResult) -> str:
        """Say how much further there is to walk.

        Distinct from `navigation.location`, which answers "where am I" —
        this answers "how much longer", and is only meaningful while a
        route is active.

        The monitor measures along the route rather than straight to the
        destination, because a walker cannot go through buildings. See
        `NavigationMonitor.remaining_distance_m`.
        """
        if self._monitor is None or not self._monitor.is_active():
            return messages.get("nav.none_active", self._lang)

        position = self._current_position()
        if position is None:
            return messages.get("location.no_gps", self._lang)

        remaining = self._monitor.remaining_distance_m(position)
        if remaining is None:
            # Active route with no usable polyline — degenerate, but the
            # user asked a question and deserves an answer either way.
            return messages.get("nav.none_active", self._lang)

        return messages.get(
            "nav.progress",
            self._lang,
            destination=self._monitor.destination_name(),
            distance=messages.speak_distance(remaining, self._lang),
        )

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

    def emergency_acknowledgement(self) -> str | None:
        """What to speak *before* the alert is dispatched, or None.

        Exists to close an ordering race, not to add a feature. The
        caller used to run `execute()` — which dispatches the alert and
        starts the SMS fan-out — and announce the result afterwards. The
        fan-out can finish first, and then `_on_alert_delivery` queues
        "the alert arrived" *before* "sending your alert" is queued at
        all. That is not merely out of order: the acknowledgement is
        announced as critical, and a critical announcement drops every
        pending non-critical one, so it deletes the confirmation the
        wearer most needs — the one that tells them they can stop
        pressing the button.

        The window is microseconds against a real HTTP round trip, so it
        is rare in the field and routine on a unit with no modem, where
        the SMS leg resolves instantly. It also failed the unit suite
        about half the time, which is its own problem.

        Returning None means "there is no race here, announce the result
        as usual":

          * no telemetry wired — nothing is dispatched at all;
          * `reports_delivery` false — no delivery callback exists, and
            the wording depends on whether the send succeeded, so it
            cannot be known in advance anyway.

        With delivery reporting on, the wording is fixed in advance
        precisely because it no longer depends on the outcome, which is
        what makes announcing first possible. `_handle_emergency_trigger`
        returns the same string, and `test_executor` pins that.
        """
        if self._telemetry is None or not self._device_id:
            return None
        if not self._reports_delivery:
            return None
        return messages.get("emergency.sending", self._lang)

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
        sent = self._telemetry.send_alert(event)

        # With a delivery report coming, this response only acknowledges
        # that the alert went out. `send_alert`'s boolean covers the HTTP
        # leg alone, and answering from it was how the wearable came to
        # say "sent to your guardian" while every SMS was being refused.
        if self._reports_delivery:
            return messages.get("emergency.sending", self._lang)

        if sent:
            return messages.get("emergency.sent", self._lang)
        return messages.get("emergency.queued", self._lang)

    def _handle_guardian_status_ok(self, result: IntentResult) -> str:
        """Send a non-emergency status confirmation to the guardians.

        Lets guardians know the user is safe and there is no need for
        concern, especially useful after an emergency alert has been sent.
        This is fire-and-forget: no retry on failure, and the status is
        not persisted across restarts.
        """
        if self._telemetry is None or not self._device_id:
            return messages.get("guardian.status_ok", self._lang)

        position = self._current_position()
        lat = position.lat if position is not None else 0.0
        lon = position.lon if position is not None else 0.0

        event = AlertEvent(
            device_id=self._device_id,
            event_type=EventType.USER_STATUS_OK,
            latitude=lat,
            longitude=lon,
            occurred_at=datetime.now(timezone.utc),
        )
        self._telemetry.send_alert(event)

        return messages.get("guardian.status_ok", self._lang)

    def _handle_system_shutdown(self, result: IntentResult) -> str:
        """Confirm, then arm the power-off. Never powers off directly.

        Shutdown is the only non-navigation intent that asks first. The
        reason is asymmetry: every other misfire is recoverable by saying
        something else, whereas a wrong power-off leaves a blind user
        holding a dead cane on a street, with no device left to ask for
        help. The classifier is good but not perfect — `"shut up"` and
        `"turn the volume off"` live one word away from this intent — so
        the confirmation is the actual safety mechanism, not the
        classifier.

        Reuses the same confirmer as `navigation.start`: the question is
        spoken, a PTT press within the timeout means yes, and silence
        means no. Silence-as-decline fails in the right direction here for
        the same reason it does there — a user who did not hear the
        question, or is not holding the device, keeps their wearable.

        Returning the goodbye rather than powering off is deliberate. The
        caller still has to synthesise and play that sentence, and a
        device that cuts power mid-word would leave the user unsure
        whether it heard them at all.
        """
        if self._shutdown is None:
            # No hook wired (tests, or a host that cannot power itself
            # off). Say so rather than claiming a shutdown that will not
            # happen.
            return messages.get("shutdown.failed", self._lang)

        if self._confirmer is None:
            # Unlike navigation, a missing confirmer must NOT mean "go
            # ahead" — that would turn every misclassification into a
            # power-off. Refuse instead.
            print("[shutdown] no confirmer wired — refusing.", file=sys.stderr, flush=True)
            return messages.get("shutdown.cancelled", self._lang)

        prompt = messages.get(
            "shutdown.confirm", self._lang,
            button=messages.get("button.ptt_position", self._lang),
            cancel=messages.get("button.cancel_position", self._lang),
        )
        if not self._confirmer(prompt):
            return messages.get("shutdown.cancelled", self._lang)

        self._shutdown()
        return messages.get("shutdown.goodbye", self._lang)

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
        # Deliberately not spoken: `reading.time_to_empty_min`.
        #
        # The gauge offers an estimate and it is not good enough to say
        # out loud. It is derived from the same state-of-charge reading
        # that needed `BATTERY_EMPTY_RAW_PERCENT` to be usable at all —
        # a gauge that pins at 57% on a flat pack is not one whose
        # minutes-remaining can be trusted — and it swings with load, so
        # a camera capture or an LLM call moves it by tens of minutes.
        #
        # A percentage that is roughly right invites the user to judge
        # for themselves. "About 2 hours remaining" sounds measured, and
        # someone deciding whether to set out will act on it. Being
        # confidently wrong about that is worse than saying less: the
        # failure mode is a blind user stranded with a dead wearable.
        #
        # The field is still on the reading and still logged, so the
        # estimate can be evaluated against real discharges later. It
        # just does not get spoken until it has earned it.
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
        technology = ""
        for line in r.stdout.splitlines():
            if "modem.generic.state " in line and ":" in line:
                state = line.split(":", 1)[1].strip()
            elif "signal-quality.value" in line and ":" in line:
                try:
                    quality = int(line.split(":", 1)[1].strip())
                except ValueError:
                    pass
            elif "access-technologies.value" in line and ":" in line:
                # mmcli numbers these (`...value[1]`) and can list more
                # than one while handing over between networks. The first
                # non-empty is the one in use.
                value = line.split(":", 1)[1].strip()
                if value and value != "--" and not technology:
                    technology = value.lower()

        if "failed" in state:
            return messages.get("cellular.check_sim", self._lang)
        if state in ("disabled", "disabling"):
            return messages.get("cellular.disabled", self._lang)
        if state in ("searching", "enabling"):
            return messages.get("cellular.connecting", self._lang)

        if quality is None:
            return messages.get("cellular.no_quality", self._lang)

        # "Registered" is not "connected". The first means the modem has
        # a network; the second means a data bearer is actually up. They
        # used to share an answer, so a user asking "is there internet
        # right now" — a phrasing in the example bank — could be told the
        # signal was strong while nothing could reach the internet.
        if state == "registered":
            return messages.get(
                "cellular.registered_no_data", self._lang, quality=quality,
            )

        strength = "strong" if quality >= 60 else "medium" if quality >= 30 else "weak"
        spoken_technology = _NETWORK_GENERATIONS.get(technology, "")
        if spoken_technology:
            return messages.get(
                f"cellular.{strength}_on", self._lang,
                quality=quality, technology=spoken_technology,
            )
        return messages.get(f"cellular.{strength}", self._lang, quality=quality)

    def _handle_system_time(self, result: IntentResult) -> str:
        now = datetime.now()
        # The clock is built by `speak_clock`, not formatted here: Tagalog
        # names the part of day and counts the minutes as a noun phrase,
        # which is grammar and belongs in messages.py. Passing a finished
        # "2:34 PM" string is what dropped the digits in Tagalog.
        return messages.get(
            "time.current", self._lang,
            time=messages.speak_clock(now.hour, now.minute, self._lang),
        )

    def _handle_vision_describe(self, result: IntentResult) -> str:
        """Capture a frame from the camera, run YOLO, describe what was found.

        Latency on Pi 5: ~50 ms capture + ~70 ms YOLO26n NCNN inference
        (extrapolated from published benchmarks — `detector_benchmark`
        measures it on the device). Runs on the voice thread so it doesn't block the
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

        if not detections:
            # The camera recognised nothing. Before admitting that, ask
            # the sensor that does not need to recognise anything — the
            # wearable used to answer "I don't see anything I recognize"
            # with an obstacle at 42 cm in front of it.
            return self._describe_unrecognised()

        return _describe_scene(detections, self._lang)

    def _describe_unrecognised(self) -> str:
        """Fall back to the ultrasonic when the camera found nothing.

        Only when the camera found nothing, never alongside a detection:
        the ultrasonic measures whatever is in its cone, which is not
        necessarily the object YOLO boxed. "I see a person, one metre
        away" would read as one measurement and be two guesses.

        A failing sensor costs the extra detail, not the answer — the
        honest "I don't see anything I recognize" is still there
        underneath.
        """
        if self._obstacle_ahead is None:
            return messages.get("vision.nothing_recognized", self._lang)
        try:
            distance_cm = self._obstacle_ahead()
        except Exception as exc:
            print(f"[vision] obstacle distance unavailable: {exc}",
                  file=sys.stderr, flush=True)
            return messages.get("vision.nothing_recognized", self._lang)

        if distance_cm is None:
            return messages.get("vision.nothing_recognized", self._lang)
        return messages.get(
            "vision.unidentified_obstacle",
            self._lang,
            distance=messages.speak_proximity(distance_cm, self._lang),
        )

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

        # Drop the cloud follow-up context. It holds a question and answer
        # in the language just left, and replaying those to the provider
        # while instructing it to answer in the new one is a contradiction
        # the model resolves by guessing.
        self._last_exchange = None
        return messages.get("language.switched", target)

    def _handle_place_save(self, result: IntentResult) -> str:
        """Store the user's current position under a label they chose.

        No geocoding: the device already knows where it is, and the point
        of this feature is naming places OpenStreetMap does not have.
        """
        label = (result.parameters.get("label") or "").strip()
        if not label:
            return messages.get("place.no_label_heard", self._lang)
        if self._places is None:
            return messages.get("place.unavailable", self._lang)

        position = self._current_position()
        if position is None:
            return messages.get("place.no_gps_to_save", self._lang)

        replaced = self._places.save(label, position)
        key = "place.updated" if replaced else "place.saved"
        return messages.get(key, self._lang, label=label)

    def _handle_place_locate(self, result: IntentResult) -> str:
        """Say where a saved place is: its address, and how far off.

        **A miss falls through to the cloud, it does not report failure.**
        "Where is CN's house" and "Where is Jollibee" are the same
        sentence, and the NLU cannot tell them apart — it has no idea
        which labels this user saved. So the classifier decides the
        *form* and this decides the *referent*, which is the only place
        that can: an unsaved label hands the original transcript to
        `_handle_unknown`, and the cloud answers it exactly as it did
        before this intent existed. Answering "you have no place saved by
        that name" instead would have made the wearable worse at a
        question it already handled.

        The two halves of the answer fail independently and are reported
        independently. Reverse-geocoding needs Photon and a network; the
        distance needs a GPS fix. A saved place is the one destination
        that resolves with no network at all, so losing the address must
        not cost the whole answer.
        """
        label = (result.parameters.get("label") or "").strip()
        if not label:
            return messages.get("place.no_label_heard", self._lang)

        place = self._places.find(label) if self._places is not None else None
        if place is None:
            print(
                f"[place] {label!r} is not saved — handing it to the cloud.",
                file=sys.stderr, flush=True,
            )
            return self._handle_unknown(result)

        # Spoken back as the user said it, not as it was stored: labels
        # are normalised for lookup (see `_place_key`) and reading the
        # normalised form back would sound like a correction.
        parts: list[str] = []
        try:
            hit = self._geocoder.reverse(place.coordinate)
        except Exception as exc:
            print(f"[place] reverse geocode failed: {exc}",
                  file=sys.stderr, flush=True)
            hit = None
        if hit is not None:
            parts = _place_parts(hit, "name", "street", "district", "city")

        here = self._current_position()
        distance = None
        if here is not None:
            distance = messages.speak_distance(
                haversine_m(here, place.coordinate), self._lang,
            )

        if parts and distance:
            return messages.get(
                "place.located", self._lang, label=label,
                places=messages.join_items(parts, self._lang),
                distance=distance,
            )
        if parts:
            return messages.get(
                "place.located_address_only", self._lang, label=label,
                places=messages.join_items(parts, self._lang),
            )
        if distance:
            return messages.get(
                "place.located_distance_only", self._lang,
                label=label, distance=distance,
            )
        return messages.get(
            "place.located_coordinates", self._lang, label=label,
            lat=f"{place.coordinate.lat:.4f}",
            lon=f"{place.coordinate.lon:.4f}",
        )

    def _handle_place_list(self, result: IntentResult) -> str:
        """Read back the labels the user has saved.

        The only way someone without a screen can audit their own list.
        Without it a forgotten label is unreachable *and* undeletable:
        `place.delete` needs the name, and not knowing the name is exactly
        the situation they are in. They re-save under a name they do
        remember and the orphan stays forever.

        Capped at `_MAX_SPOKEN_PLACES`. Speech is serial — a dozen labels
        read at someone is a wait, not a list — and the count of what was
        held back is spoken rather than dropped, so the number is never
        quietly wrong. Alphabetical because `SavedPlaces.labels()` sorts:
        the order has to be stable across calls, or the "and four more"
        tail would hide a different four each time.
        """
        if self._places is None:
            return messages.get("place.unavailable", self._lang)

        labels = self._places.labels()
        if not labels:
            return messages.get("place.list_empty", self._lang)

        spoken = labels[:_MAX_SPOKEN_PLACES]
        remaining = len(labels) - len(spoken)
        places = messages.join_items(spoken, self._lang)
        if remaining:
            return messages.get(
                "place.list_truncated", self._lang,
                places=places, count=messages.speak_number(remaining, self._lang),
            )
        return messages.get("place.list", self._lang, places=places)

    def _handle_place_delete(self, result: IntentResult) -> str:
        label = (result.parameters.get("label") or "").strip()
        if not label:
            return messages.get("place.no_label_heard", self._lang)
        if self._places is None:
            return messages.get("place.unavailable", self._lang)

        if self._places.delete(label):
            return messages.get("place.deleted", self._lang, label=label)
        return messages.get("place.not_found", self._lang, label=label)

    def _handle_system_volume(self, result: IntentResult) -> str:
        """Raise, lower, or set the speaker volume.

        The response is spoken *at* the new volume by the caller, so
        hearing it is the verification — the same reason the language
        switch confirms in the language it switched to.

        Refusing to go below the floor gets its own message rather than a
        silent clamp. A user who asked for 10 percent and simply heard
        "volume is now 20 percent" would think they were misheard; being
        told why turns it into a decision they can understand.
        """
        if self._volume is None:
            return messages.get("volume.unavailable", self._lang)

        direction = (result.parameters.get("direction") or "").strip().lower()
        level = result.parameters.get("level")

        if direction == "up":
            if self._volume.at_maximum():
                return messages.get(
                    "volume.at_maximum", self._lang, percent=self._volume.current,
                )
            return messages.get(
                "volume.set", self._lang, percent=self._volume.louder(),
            )

        if direction == "down":
            if self._volume.at_minimum():
                return messages.get(
                    "volume.at_minimum", self._lang, percent=self._volume.minimum,
                )
            return messages.get(
                "volume.set", self._lang, percent=self._volume.quieter(),
            )

        if level is not None:
            try:
                requested = int(level)
            except (TypeError, ValueError):
                return self._volume_not_understood()
            applied = self._volume.set(requested)
            if requested < applied:
                # Asked below the floor — say the floor and why, not just
                # the number that happened instead.
                return messages.get(
                    "volume.at_minimum", self._lang, percent=applied,
                )
            return messages.get("volume.set", self._lang, percent=applied)

        return self._volume_not_understood()

    def _volume_not_understood(self) -> str:
        minimum = self._volume.minimum if self._volume else 0
        maximum = self._volume.maximum if self._volume else 100
        return messages.get(
            "volume.not_understood", self._lang, minimum=minimum, maximum=maximum,
        )

    def _handle_system_help(self, result: IntentResult) -> str:
        """Say what the wearable can do, in the language it is speaking.

        Deliberately static: no device state, no network, nothing that can
        fail. "What can you do?" is a question a confused or new user asks,
        and it would be a poor answer to have it depend on whether GPS has
        a fix.
        """
        return messages.get(
            "help.capabilities", self._lang,
            button=messages.get("button.ptt_position", self._lang),
            cancel=messages.get("button.cancel_position", self._lang),
            emergency=messages.get("button.emergency_position", self._lang),
        )

    def _handle_unknown(self, result: IntentResult) -> str:
        """Answer an utterance the local NLU declined to classify.

        With no cloud answerer wired this is the plain "I didn't catch
        that". With one, the transcript goes to a cloud LLM — the local
        model stays deliberately conservative and the cloud picks up what
        it defers, rather than competing with it for real commands. See
        `intents/cloud.py`.

        A parse *failure* is not a decline and never reaches the cloud. If
        Ollama timed out or returned unreadable JSON, the local model never
        got to claim the utterance, so forwarding it would mean a chance of
        sending "take me to the hospital" to a chatbot — the one thing the
        `unknown`-only entry point exists to prevent. The user hears the
        same "I didn't catch that" either way: the distinction is for the
        system, and inventing a separate spoken message would leak internal
        state to somebody who can only act on it by trying again anyway.
        """
        if result.failure is not None:
            print(
                f"[executor] not forwarding to cloud — parse failed "
                f"({result.failure})",
                file=sys.stderr,
                flush=True,
            )
            return messages.get("generic.unknown_intent", self._lang)

        if self._cloud is None:
            return messages.get("generic.unknown_intent", self._lang)

        question = (result.raw_transcript or "").strip()
        if not question:
            # Nothing was transcribed — there is no question to forward,
            # and sending an empty string would waste a paid API call to
            # be told nothing.
            return messages.get("generic.unknown_intent", self._lang)

        answer = self._cloud.answer(question, self._lang, self._recent_exchange())

        if answer.reason == "offline":
            return messages.get("cloud.offline", self._lang)
        if answer.reason != "ok" or not answer.text or not answer.text.strip():
            return messages.get("cloud.error", self._lang)

        text = answer.text.strip()
        if len(text) > self._cloud_max_chars:
            text = text[: self._cloud_max_chars].rstrip() + messages.get(
                "vision.truncated_suffix", self._lang,
            )

        # Remember the full answer, not the truncated one: the truncation
        # exists so a long reply is not spoken at length, and feeding the
        # clipped version back would have the model build on a sentence
        # that stops mid-word.
        self._last_exchange = (question, answer.text.strip(), time.monotonic())
        return text

    # --- helpers ------------------------------------------------------------

    def _recent_exchange(self) -> tuple[str, str] | None:
        """The last cloud question and answer, if still recent enough.

        Only cloud exchanges. A follow-up like "what about now" after
        `vision.describe` cannot be served by a cloud model — it has no
        camera — and handing it "I see a window" as context would invite
        a confident answer about a scene the provider never saw. Pairing
        cloud questions with cloud answers keeps the context honest about
        what it is.

        Expires after `CLOUD_CONTEXT_TTL_S`. A pronoun resolves against
        what was *just* said; a question asked ten minutes later is a new
        conversation, and silently attaching it to an old one is how
        "what about the second" gets answered about the wrong subject.
        """
        if self._last_exchange is None:
            return None
        question, answer, asked_at = self._last_exchange
        if time.monotonic() - asked_at > self._cloud_context_ttl_s:
            self._last_exchange = None
            return None
        return question, answer

    def _current_heading(self) -> float | None:
        """The user's facing direction, or None if it cannot be trusted.

        Swallows failures: a compass that throws must cost us a routing
        bias, not the route.
        """
        if self._heading is None:
            return None
        try:
            return self._heading()
        except Exception as exc:
            print(f"[nav] heading unavailable: {exc}", file=sys.stderr, flush=True)
            return None

    def _saved_destination(self, location: str) -> GeocodingResult | None:
        """A saved place matching `location`, shaped like a geocoder hit.

        Returning a `GeocodingResult` rather than a `SavedPlace` keeps
        `_handle_navigation_start` reading as one path: whether the
        destination came from the user's own list or from Photon, the
        routing and response code below it is identical.

        Street and city are None because a saved place has no address —
        the user named a coordinate, not a listing — so the spoken
        response falls back to their own label, which is what they would
        recognise anyway.
        """
        if self._places is None:
            return None
        place = self._places.find(location)
        if place is None:
            return None
        return GeocodingResult(
            name=place.label,
            coordinate=place.coordinate,
            country=None,
            city=None,
            feature_type="saved_place",
        )

    def _confirm_destination(
        self,
        destination: GeocodingResult,
        origin: Coordinate,
    ) -> bool:
        """Ask the user to approve a geocoded destination before routing.

        Returns True to proceed. With no `confirmer` wired — unit tests,
        and any future caller that has no way to ask — this returns True
        and navigation behaves exactly as it did before confirmation
        existed. That default is deliberate: a missing confirmation
        channel must not make navigation impossible, and the geocoder's
        answer is the same one the wearable would have used anyway.

        A confirmer that raises is treated as a decline. It runs on the
        voice thread and touches audio and GPIO, so it can fail in ways
        this executor has no business interpreting — and proceeding on a
        question the user may never have heard is the worse guess.
        """
        if self._confirmer is None:
            return True

        question = messages.get(
            "nav.confirm_destination",
            self._lang,
            place=_describe_destination(destination),
            distance=messages.speak_distance(
                haversine_m(origin, destination.coordinate), self._lang,
            ),
            button=messages.get("button.ptt_position", self._lang),
            cancel=messages.get("button.cancel_position", self._lang),
        )
        try:
            return bool(self._confirmer(question))
        except Exception as exc:
            print(f"[nav] confirmation failed: {exc}", file=sys.stderr, flush=True)
            return False

    def _current_position(self) -> Coordinate | None:
        if self._gps is None:
            return None
        fix = self._gps.read()
        if fix is None or fix.fix_quality == 0:
            return None
        return Coordinate(lat=fix.lat, lon=fix.lon)
