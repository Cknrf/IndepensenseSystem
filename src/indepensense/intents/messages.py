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
import sys

# Languages this catalogue covers. Keep in step with `config.PIPER_VOICES`,
# `config.WHISPER_MODELS` and `config.OCR_LANGUAGES`.
LANGUAGES = ("en", "tl")

FALLBACK_LANGUAGE = "en"


MESSAGES: dict[str, dict[str, str]] = {
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
        "en": "Navigating to {destination}. Total distance {distance} meters. {first_action}",
        "tl": "Papunta na tayo sa {destination}. Ang kabuuang distansya ay {distance} metro. {first_action}",
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
        "en": "Walk {distance} meters to arrive at your destination.",
        "tl": "Maglakad ng {distance} metro para makarating sa destinasyon.",
    },
    "nav.turn_immediately": {
        "en": "{instruction} immediately.",
        "tl": "{instruction} kaagad.",
    },
    "nav.turn_in_distance": {
        "en": "In {distance} meters, {instruction}.",
        "tl": "Sa {distance} metro, {instruction}.",
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
