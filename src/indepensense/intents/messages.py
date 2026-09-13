"""Every spoken response, in every supported language.

Response text used to be inline string literals in `executor.py`. That
made English structural: adding Tagalog would have meant a conditional at
each of ~45 return statements. Here each message has one key and one
entry per language, so a missing translation is visible at a glance and
the executor reads as logic rather than as prose.

Keys are namespaced by the intent that speaks them (`nav.*`, `battery.*`,
`vision.*`). Placeholders use `str.format` fields, and the *same* field
names must appear in every language — the tests enforce both that and
full translation coverage, because a `KeyError` here would surface as the
wearable going silent mid-sentence.

On the Tagalog
--------------

Two deliberate choices a reader should know about.

**Object labels stay in English.** YOLO emits COCO class names
("person", "traffic light"), and Manila speech code-switches freely —
"Nakikita ko ang 2 tao at isang chair" is how people actually talk, while
forcing "ilaw ng trapiko" for traffic light is stilted. `_TL_LABELS`
translates a small set of high-frequency and safety-relevant nouns and
everything else falls through to English on purpose, not by omission.

**Tagalog nouns are not inflected for number.** English needs
"a chair" / "2 chairs"; Tagalog uses the bare noun with a counter
("isang upuan", "2 upuan"). So the scene description takes a different
code path per language rather than a shared pluraliser — see
`count_label`.
"""
import math
import sys

# Languages this catalogue covers. Keep in step with `config.PIPER_VOICES`,
# `config.WHISPER_MODELS` and `config.OCR_LANGUAGES`.
LANGUAGES = ("en", "tl")

FALLBACK_LANGUAGE = "en"


MESSAGES: dict[str, dict[str, str]] = {
    # --- distances ----------------------------------------------------------
    # The unit is its own message rather than part of every sentence that
    # mentions a distance, because which unit applies depends on the value:
    # `speak_distance` picks one of these three. Baking "meters" into the
    # templates is what made the wearable announce a cross-province geocode
    # as "five hundred thirteen thousand six hundred meters".
    #
    # English inflects the noun and Tagalog does not, so the one-kilometre
    # case gets its own key rather than a shared "{value} kilometer(s)"
    # template that would only be correct in one of the two languages.
    "distance.meters": {
        "en": "{value} meters",
        "tl": "{value} metro",
    },
    "distance.kilometers": {
        "en": "{value} kilometers",
        "tl": "{value} kilometro",
    },
    "distance.one_kilometer": {
        "en": "1 kilometer",
        "tl": "1 kilometro",
    },

    # --- hardware the user is told to touch ---------------------------------
    # Where the push-to-talk button physically sits on the enclosure, as a
    # word the wearer can act on. Separate from the sentences that use it so
    # that re-fabricating the enclosure — or discovering PTT is actually the
    # middle button — is a single edit that cannot leave the two languages
    # disagreeing. See docs/hardware.md for the layout this describes.
    "button.ptt_position": {
        "en": "left",
        "tl": "kaliwang",
    },

    # --- language switching -------------------------------------------------
    # Spoken in the language being switched TO, so hearing the confirmation
    # verifies the switch worked. A wrong switch is immediately audible.
    "language.switched": {
        "en": "I am now speaking English.",
        "tl": "Tagalog na ang gagamitin ko ngayon.",
    },
    "language.already": {
        "en": "I am already speaking English.",
        "tl": "Tagalog na ang ginagamit ko.",
    },
    "language.unsupported": {
        "en": "I can only speak English and Tagalog.",
        "tl": "Ingles at Tagalog lamang ang kaya kong gamitin.",
    },
    "language.greeting": {
        "en": "IndepenSense is ready. I am speaking English.",
        "tl": "Handa na ang IndepenSense. Tagalog ang ginagamit ko.",
    },

    # --- navigation ---------------------------------------------------------
    "nav.no_destination_heard": {
        "en": "I didn't hear where you want to go. Please try again.",
        "tl": "Hindi ko narinig kung saan ka gustong pumunta. Pakiulit po.",
    },
    "nav.no_gps_for_start": {
        "en": "I can't start navigation without a GPS fix yet.",
        "tl": "Hindi pa ako makakapagsimula ng nabigasyon dahil wala pang GPS signal.",
    },
    "nav.place_not_found": {
        "en": "I couldn't find any place matching '{location}'.",
        "tl": "Wala akong nakitang lugar na tumutugma sa '{location}'.",
    },
    "nav.started": {
        "en": "Navigating to {destination}. Total distance {distance}. {first_action}",
        "tl": "Papunta na tayo sa {destination}. Ang kabuuang distansya ay {distance}. {first_action}",
    },
    "nav.none_active": {
        "en": "You don't have an active navigation.",
        "tl": "Wala kang aktibong nabigasyon.",
    },
    "nav.cancelled": {
        "en": "Navigation cancelled.",
        "tl": "Kinansela na ang nabigasyon.",
    },
    "nav.nothing_to_repeat": {
        "en": "There is nothing to repeat yet.",
        "tl": "Wala pa akong maiuulit.",
    },
    "nav.start_walking": {
        "en": "Start walking.",
        "tl": "Maglakad na po kayo.",
    },
    "nav.already_at_destination": {
        "en": "You are already at your destination.",
        "tl": "Nasa destinasyon ka na.",
    },
    "nav.walk_to_arrive": {
        "en": "Walk {distance} to arrive at your destination.",
        "tl": "Maglakad ng {distance} para makarating sa destinasyon.",
    },
    "nav.turn_immediately": {
        "en": "{instruction} immediately.",
        "tl": "{instruction} kaagad.",
    },
    "nav.turn_in_distance": {
        "en": "In {distance}, {instruction}.",
        "tl": "Sa {distance}, {instruction}.",
    },

    # Turn verification. Names the turn rather than issuing an order: the
    # wearable cannot reroute, so "turn around" would be advice it has no
    # basis for — the user may be mid-crossing, or may have a reason. What
    # it can honestly do is say what it believes happened.
    "nav.missed_turn": {
        "en": "It looks like you missed the turn. The instruction was: {instruction}.",
        "tl": "Mukhang nalampasan mo ang liko. Ang tagubilin ay: {instruction}.",
    },

    # Turn-to-face. Only two spoken lines in the whole interaction — the
    # turning itself is haptic, because a spoken angle lags the movement it
    # describes and competes with traffic. See navigation/orientation.py.
    "nav.walk_straight_ahead": {
        "en": "Walk straight ahead.",
        "tl": "Dumiretso ka na po.",
    },
    # The give-up line. Says what to do rather than reporting a failure:
    # the user is standing in the street and needs an instruction, not a
    # diagnosis.
    "nav.orientation_gave_up": {
        "en": "Start walking, and I will guide you from there.",
        "tl": "Maglakad na po kayo, at gagabayan ko kayo mula roon.",
    },

    # Progress. Distance only, no time estimate: the remaining seconds
    # would have to come from an assumed walking speed, and GraphHopper's
    # pedestrian profile assumes a brisk 5 km/h that a cane user is
    # unlikely to match. A confident wrong number would have them hurrying.
    "nav.progress": {
        "en": "{destination} is {distance} away.",
        "tl": "{distance} pa ang layo ng {destination}.",
    },

    # Destination confirmation. The geocoder returns the best *guess*, and a
    # user who cannot read a map has no way to notice it picked the branch in
    # the next province — so the wearable reads its choice back and waits for
    # a deliberate press before routing anywhere.
    #
    # `{button}` is filled from `button.ptt_position` rather than written into
    # the sentence, so a rebuilt enclosure is one edit in one place instead of
    # a hunt through every message that names a button.
    "nav.confirm_destination": {
        "en": "{place}, {distance} away. Press the {button} button to "
              "confirm, or wait to cancel.",
        # "kaliwang pindutan", not "kaliwa na pindutan" — the ligature is
        # baked into the `button.ptt_position` value so the template stays a
        # plain substitution rather than growing per-language grammar glue.
        "tl": "{place}, {distance} ang layo. Pindutin ang {button} "
              "pindutan para kumpirmahin, o maghintay para kanselahin.",
    },
    "nav.confirm_timed_out": {
        "en": "Cancelled. Please say where you want to go.",
        "tl": "Kinansela. Pakisabi po kung saan kayo gustong pumunta.",
    },

    # --- saved places -------------------------------------------------------
    # The label is always spoken back. It is the only confirmation the user
    # gets that the wearable heard "my sister's house" and not something
    # else, and a place saved under a misheard label is unreachable —
    # they would have to guess the mishearing to navigate to it.
    "place.saved": {
        "en": "Saved this place as {label}.",
        "tl": "Na-save ko ang lugar na ito bilang {label}.",
    },
    "place.updated": {
        "en": "Updated {label} to this place.",
        "tl": "Na-update ko ang {label} sa lugar na ito.",
    },
    "place.no_label_heard": {
        "en": "I didn't hear what to call this place. Please try again.",
        "tl": "Hindi ko narinig kung ano ang itatawag dito. Pakiulit po.",
    },
    "place.no_gps_to_save": {
        "en": "I can't save this place without a GPS fix yet.",
        "tl": "Hindi ko masi-save ang lugar na ito dahil wala pang GPS signal.",
    },
    "place.deleted": {
        "en": "Forgot the place saved as {label}.",
        "tl": "Kinalimutan ko na ang lugar na naka-save bilang {label}.",
    },
    "place.not_found": {
        "en": "I don't have a place saved as {label}.",
        "tl": "Wala akong lugar na naka-save bilang {label}.",
    },
    "place.unavailable": {
        "en": "I can't save places right now.",
        "tl": "Hindi ako makakapag-save ng lugar sa ngayon.",
    },

    # --- volume -------------------------------------------------------------
    # The confirmation is spoken AT the new volume, the same trick the
    # language switch uses: hearing it is the verification. A user who asks
    # for louder and hears the same level knows immediately it did not work.
    "volume.set": {
        "en": "Volume is now {percent} percent.",
        "tl": "{percent} porsyento na ang lakas ng tunog.",
    },
    "volume.at_maximum": {
        "en": "Volume is already at the maximum, {percent} percent.",
        "tl": "Nasa pinakamataas na ang lakas ng tunog, {percent} porsyento.",
    },
    # Says the floor AND why it exists. "I can't" on its own would read as
    # the device being broken; the reason makes it a decision.
    "volume.at_minimum": {
        "en": "I can't go below {percent} percent, or you might not hear me.",
        "tl": "Hindi ko puwedeng ibaba sa {percent} porsyento, baka hindi mo "
              "na ako marinig.",
    },
    "volume.not_understood": {
        "en": "I didn't catch what volume you want. Say louder, quieter, "
              "or a number from {minimum} to {maximum}.",
        "tl": "Hindi ko naintindihan kung anong lakas ang gusto mo. Sabihin "
              "mong palakasin, pahinaan, o isang numero mula {minimum} "
              "hanggang {maximum}.",
    },
    "volume.unavailable": {
        "en": "I can't change the volume right now.",
        "tl": "Hindi ko mababago ang lakas ng tunog sa ngayon.",
    },

    # --- help ---------------------------------------------------------------
    # A user who cannot see a screen also cannot read a manual, so the only
    # place the wearable's capabilities can live is in its own voice.
    #
    # Four things, not twelve. Reading a full catalogue aloud is roughly
    # forty-five seconds nobody sits through and nobody remembers; these are
    # the highest-value asks, and anything else is discoverable by trying.
    #
    # No button is named. The emergency button's position on the enclosure
    # is still unrecorded (see docs/hardware.md), and telling a blind user
    # to press a button we cannot locate is worse than not mentioning it.
    # Add that sentence once the layout is confirmed.
    "help.capabilities": {
        "en": "I am IndepenSense. I help you walk safely and independently. "
              "You can ask me where you are, what is around you, have me read "
              "text out loud, or tell me where you want to go. You can also "
              "say save this place as home, and later say take me home.",
        "tl": "Ako si IndepenSense. Tinutulungan kitang makapaglakad nang "
              "ligtas at malaya. Puwede mong itanong kung nasaan ka, kung ano "
              "ang nasa paligid mo, pabasahin ang nakasulat, o sabihin kung "
              "saan mo gustong pumunta. Puwede mo ring sabihing i-save mo ito "
              "bilang bahay, at mamaya ay dalhin mo ako sa bahay.",
    },

    # --- location -----------------------------------------------------------
    "location.no_gps": {
        "en": "I don't have a GPS fix yet.",
        "tl": "Wala pa akong GPS signal.",
    },
    "location.near_places": {
        "en": "You are near {places}.",
        "tl": "Malapit ka sa {places}.",
    },
    "location.near_coordinates": {
        "en": "You are near latitude {lat}, longitude {lon}.",
        "tl": "Ang iyong lokasyon ay latitude {lat}, longitude {lon}.",
    },

    # --- emergency ----------------------------------------------------------
    # Spoken to the *wearer* when the system acts on its own, as opposed to
    # `emergency.sent` which answers a button they deliberately pressed.
    # Automatic fall detection used to notify guardians and say nothing at
    # all to the person lying on the ground, who then had no way to know
    # whether help was coming.
    #
    # Phrased as a statement, not a question: there is no cancel window by
    # design — someone knocked unconscious cannot decline one — so implying
    # they have a choice would be a lie.
    "fall.detected": {
        "en": "I detected a fall. I have alerted your guardian.",
        "tl": "May natukoy akong pagkahulog. Naabisuhan ko na ang inyong tagabantay.",
    },

    # --- battery warnings spoken to the wearer ------------------------------
    # The guardian has had an SMS and a dashboard alert since the first
    # threshold; the person carrying the device was the only one not told.
    "battery.low_warning": {
        "en": "Battery is low, {percent} percent remaining. "
              "Please charge the device soon.",
        "tl": "Mababa na ang baterya, {percent} porsyento na lang. "
              "Pakisingil na po ang device.",
    },
    "battery.critical_warning": {
        "en": "Battery critically low at {percent} percent. "
              "The device will shut down soon.",
        "tl": "Kritikal na ang baterya, {percent} porsyento na lang. "
              "Malapit nang mag-shut down ang device.",
    },

    "emergency.local_only": {
        "en": "Emergency alert triggered locally. Guardian dashboard not connected.",
        "tl": "Naitala ang emergency sa device. Hindi konektado ang dashboard ng tagapag-alaga.",
    },
    "emergency.sent": {
        "en": "Emergency alert sent to your guardian.",
        "tl": "Naipadala na ang emergency alert sa iyong tagapag-alaga.",
    },
    "emergency.queued": {
        "en": "Emergency alert could not be sent right now. The system will keep trying in the background.",
        "tl": "Hindi maipadala ngayon ang emergency alert. Patuloy itong susubukan ng sistema.",
    },

    # --- battery ------------------------------------------------------------
    "battery.unavailable": {
        "en": "Battery monitoring is not available on this device.",
        "tl": "Hindi available ang pagsubaybay sa baterya sa device na ito.",
    },
    "battery.read_failed": {
        "en": "I couldn't read the battery status right now.",
        "tl": "Hindi ko mabasa ngayon ang estado ng baterya.",
    },
    "battery.charging": {
        "en": "Battery is at {percent} percent and charging.",
        "tl": "Ang baterya ay {percent} porsyento at nagcha-charge.",
    },
    "battery.level": {
        "en": "Battery is at {percent} percent.",
        "tl": "Ang baterya ay {percent} porsyento.",
    },
    "battery.level_with_hours": {
        "en": "Battery is at {percent} percent, about {hours} hours and {minutes} minutes remaining.",
        "tl": "Ang baterya ay {percent} porsyento, mga {hours} oras at {minutes} minuto pa ang natitira.",
    },
    "battery.level_with_minutes": {
        "en": "Battery is at {percent} percent, about {minutes} minutes remaining.",
        "tl": "Ang baterya ay {percent} porsyento, mga {minutes} minuto pa ang natitira.",
    },

    # --- GPS status ---------------------------------------------------------
    "gps.not_configured": {
        "en": "GPS is not configured on this device.",
        "tl": "Hindi nakaayos ang GPS sa device na ito.",
    },
    "gps.no_fix": {
        "en": "GPS has no fix at the moment.",
        "tl": "Wala pang GPS signal sa ngayon.",
    },
    "gps.locked": {
        "en": "GPS is locked with {satellites} satellites. Signal quality is good.",
        "tl": "Naka-lock ang GPS sa {satellites} satellite. Maayos ang signal.",
    },

    # --- cellular -----------------------------------------------------------
    "cellular.unavailable": {
        "en": "Cellular status is not available on this device.",
        "tl": "Hindi available ang estado ng cellular sa device na ito.",
    },
    "cellular.no_modem": {
        "en": "No cellular modem is detected.",
        "tl": "Walang na-detect na cellular modem.",
    },
    "cellular.check_sim": {
        "en": "Cellular is unavailable. Check that the SIM card is inserted.",
        "tl": "Hindi available ang cellular. Tiyaking nakakabit ang SIM card.",
    },
    "cellular.disabled": {
        "en": "Cellular is disabled.",
        "tl": "Naka-disable ang cellular.",
    },
    "cellular.connecting": {
        "en": "Cellular is still connecting.",
        "tl": "Kumokonekta pa ang cellular.",
    },
    "cellular.no_quality": {
        "en": "Cellular is connected, but signal strength is not reported.",
        "tl": "Konektado ang cellular, ngunit hindi maipakita ang lakas ng signal.",
    },
    "cellular.strong": {
        "en": "Cellular signal is strong, at {quality} percent.",
        "tl": "Malakas ang cellular signal, {quality} porsyento.",
    },
    "cellular.medium": {
        "en": "Cellular signal is medium, at {quality} percent.",
        "tl": "Katamtaman ang cellular signal, {quality} porsyento.",
    },
    "cellular.weak": {
        "en": "Cellular signal is weak, at {quality} percent.",
        "tl": "Mahina ang cellular signal, {quality} porsyento.",
    },

    # --- time ---------------------------------------------------------------
    "time.current": {
        "en": "It's currently {time}.",
        "tl": "Ganap na {time} ngayon.",
    },

    # --- vision -------------------------------------------------------------
    "vision.camera_unavailable": {
        "en": "The camera is not available on this device.",
        "tl": "Hindi available ang camera sa device na ito.",
    },
    "vision.capture_failed": {
        "en": "I couldn't take a photo right now. Please try again.",
        "tl": "Hindi ako makakuha ng larawan ngayon. Pakiulit po.",
    },
    "vision.no_image": {
        "en": "The camera returned no image.",
        "tl": "Walang larawang naibigay ang camera.",
    },
    "vision.analyze_failed": {
        "en": "I couldn't analyze the image right now. Please try again.",
        "tl": "Hindi ko masuri ang larawan ngayon. Pakiulit po.",
    },
    "vision.nothing_recognized": {
        "en": "I don't see anything I recognize right now.",
        "tl": "Wala akong nakikilalang bagay sa ngayon.",
    },
    "vision.i_see": {
        "en": "I see {items}.",
        "tl": "Nakikita ko ang {items}.",
    },
    "vision.read_failed": {
        "en": "I couldn't read the text right now. Please try again.",
        "tl": "Hindi ko mabasa ang teksto ngayon. Pakiulit po.",
    },
    "vision.no_text": {
        "en": "I don't see any readable text.",
        "tl": "Wala akong nakikitang mababasang teksto.",
    },
    "vision.truncated_suffix": {
        "en": "... and more.",
        "tl": "... at iba pa.",
    },

    # --- cloud LLM fallback -------------------------------------------------
    # "offline" and "error" are deliberately different. Being offline is
    # actionable — the user can move somewhere with signal — while a
    # provider failure is not, and conflating them sends the user to look
    # for a signal that was never the problem.
    "cloud.offline": {
        "en": "I need an internet connection to answer that, and I don't have one right now.",
        "tl": "Kailangan ko ng internet para masagot iyan, at wala ako ngayon.",
    },
    "cloud.error": {
        "en": "I couldn't get an answer for that right now. Please try again.",
        "tl": "Hindi ako makakuha ng sagot diyan ngayon. Pakiulit po.",
    },
    "cloud.thinking": {
        "en": "Let me think about that.",
        "tl": "Pag-iisipan ko muna iyan.",
    },

    # --- generic ------------------------------------------------------------
    "generic.unknown_intent": {
        "en": "Sorry, I didn't catch that. Could you try again?",
        "tl": "Paumanhin, hindi ko naintindihan. Pakiulit po.",
    },
    "generic.unknown_status_field": {
        "en": "I don't know how to report on '{field}'.",
        "tl": "Hindi ko alam kung paano iuulat ang '{field}'.",
    },
    "generic.error": {
        "en": "Sorry, something went wrong: {error}",
        "tl": "Paumanhin, may naganap na problema: {error}",
    },
}


# Tagalog for a small set of frequently-seen and safety-relevant COCO
# labels. Everything absent falls through to the English label, which is
# natural in Filipino speech — see the module docstring.
_TL_LABELS: dict[str, str] = {
    "person": "tao",
    "car": "kotse",
    "bus": "bus",
    "truck": "trak",
    "motorcycle": "motorsiklo",
    "bicycle": "bisikleta",
    "dog": "aso",
    "cat": "pusa",
    "chair": "upuan",
    "bench": "bangko",
    "table": "mesa",
    "door": "pinto",
    "stairs": "hagdan",
    "bottle": "bote",
    "cup": "tasa",
    "book": "libro",
    "bag": "bag",
    "tree": "puno",
    "traffic light": "traffic light",
}

# Vowels that take "an" instead of "a" in English.
_ENGLISH_VOWELS = "aeiou"

# COCO labels whose English plural is irregular.
_IRREGULAR_PLURALS: dict[str, str] = {
    "person": "people",
    "child": "children",
    "mouse": "mice",       # COCO's "mouse" is a computer mouse
    "foot": "feet",
    "tooth": "teeth",
}


def english_plural(label: str, count: int) -> str:
    """English plural + article. 1 -> "a chair", 2 -> "2 chairs"."""
    if count == 1:
        article = "an" if label[:1].lower() in _ENGLISH_VOWELS else "a"
        return f"{article} {label}"
    plural = _IRREGULAR_PLURALS.get(label)
    if plural is None:
        if label.endswith(("s", "x", "z", "ch", "sh")):
            plural = label + "es"
        elif label.endswith("y") and len(label) >= 2 and label[-2] not in _ENGLISH_VOWELS:
            plural = label[:-1] + "ies"
        else:
            plural = label + "s"
    return f"{count} {plural}"


def count_label(label: str, count: int, language: str) -> str:
    """Render "<count> <label>" with that language's number grammar.

    English inflects the noun. Tagalog does not — it uses the bare noun
    with a counter, and "isang" for one. This is why scene description
    cannot share a single pluraliser across languages.
    """
    if language == "tl":
        translated = _TL_LABELS.get(label, label)
        if count == 1:
            return f"isang {translated}"
        return f"{count} {translated}"
    return english_plural(label, count)


def round_speech_distance(m: float) -> int:
    """Round a distance in metres to a value pleasant for speech synthesis.

    "In 87 meters, turn left" sounds robotic. "In 90 meters..." sounds
    natural. Rounds to the nearest 10 m for distances under 100 m,
    nearest 50 m up to 500 m, nearest 100 m beyond. Never returns 0.

    Halves round up (25 -> 30, 650 -> 700). We deliberately avoid the
    builtin `round()` here: it uses banker's rounding (round-half-to-
    even), so `round(6.5)` is 6, not 7 — which would speak 650 m as
    "600 meters". Overstating the remaining distance by a half-step is
    also the safer error for a walking user: they arrive slightly
    early rather than being told to turn after they have passed it.

    Returns a bare number. `speak_distance` is what turns it into words.
    """
    if m < 100:
        return max(10, _round_half_up(m, 10))
    if m < 500:
        return _round_half_up(m, 50)
    return _round_half_up(m, 100)


def _round_half_up(m: float, step: int) -> int:
    """Round `m` to the nearest multiple of `step`, halves going up."""
    return int(math.floor(m / step + 0.5)) * step


# Above this many metres, speak kilometres instead. One kilometre is the
# point where the metre count stops being something a walker can picture:
# "eight hundred meters" is a distance you can feel, "eight thousand two
# hundred meters" is arithmetic.
_KILOMETRE_M = 1000

# And above this, drop the decimal. "8.2 kilometers" is useful precision
# for a walk; "513.6 kilometers" is noise on a number whose only job is to
# tell the user this destination is absurd.
_WHOLE_KILOMETRE_M = 10_000


def speak_distance(metres: float, language: str) -> str:
    """Render a distance as words, choosing the unit to suit the magnitude.

    Under a kilometre it stays in metres, because that is the resolution a
    walking user acts on. At or above, it switches to kilometres — the
    wearable used to announce a cross-province geocode as "513600 meters",
    which Piper reads out in full and nobody can parse.

    The unit word comes from the catalogue above rather than being
    concatenated here, so Tagalog is a translation rather than a special
    case, and the one-kilometre singular stays correct in English.
    """
    rounded_m = round_speech_distance(metres)
    if rounded_m < _KILOMETRE_M:
        return get("distance.meters", language, value=rounded_m)

    km = rounded_m / 1000.0
    if rounded_m >= _WHOLE_KILOMETRE_M:
        value: float | int = int(_round_half_up(km, 1))
    else:
        value = round(km, 1)
        if value == int(value):
            # 2.0 -> 2, so it is spoken "2 kilometers" not "2.0 kilometers".
            value = int(value)

    if value == 1:
        return get("distance.one_kilometer", language)
    return get("distance.kilometers", language, value=value)


def join_items(items: list[str], language: str) -> str:
    """Comma-and join for spoken lists, with the language's conjunction."""
    conjunction = "at" if language == "tl" else "and"
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} {conjunction} {items[1]}"
    return ", ".join(items[:-1]) + f", {conjunction} " + items[-1]


def get(key: str, language: str, **fields) -> str:
    """Look up a message and fill in its placeholders.

    Falls back to `FALLBACK_LANGUAGE` for a missing translation and to the
    key itself for a missing message: speaking something odd beats
    raising inside the voice pipeline, where the exception would surface
    to the user as silence.
    """
    entry = MESSAGES.get(key)
    if entry is None:
        print(f"[messages] unknown key {key!r}", file=sys.stderr)
        return key

    template = entry.get(language)
    if template is None:
        print(
            f"[messages] {key!r} has no {language!r} translation; using "
            f"{FALLBACK_LANGUAGE!r}",
            file=sys.stderr,
        )
        template = entry[FALLBACK_LANGUAGE]

    try:
        return template.format(**fields)
    except (KeyError, IndexError) as exc:
        print(f"[messages] {key!r} missing placeholder {exc}", file=sys.stderr)
        return template
