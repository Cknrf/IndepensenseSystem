"""Unit tests for the response catalogue.

The coverage tests here are the point of the file. A missing translation
or a mismatched placeholder would surface at runtime as the wearable
saying the wrong thing, or saying nothing at all — and only for the
language the developer wasn't testing in. These assertions make that a
test failure instead.
"""
import re
import string

import pytest

from indepensense.intents import messages


def _placeholders(template: str) -> set[str]:
    """Field names used by a `str.format` template."""
    return {
        field
        for _, field, _, _ in string.Formatter().parse(template)
        if field
    }


# --- coverage ----------------------------------------------------------------

@pytest.mark.parametrize("key", sorted(messages.MESSAGES))
def test_every_message_covers_every_language(key):
    """A key missing a language would fall back mid-conversation, so the
    user hears one sentence in the wrong language."""
    missing = [lang for lang in messages.LANGUAGES if lang not in messages.MESSAGES[key]]
    assert not missing, f"{key!r} is missing: {missing}"


@pytest.mark.parametrize("key", sorted(messages.MESSAGES))
def test_placeholders_match_across_languages(key):
    """Every language's template must take the same fields.

    A translation that renamed or dropped a field would raise KeyError
    inside the voice pipeline, which the user experiences as silence.
    """
    entry = messages.MESSAGES[key]
    expected = _placeholders(entry[messages.FALLBACK_LANGUAGE])
    for language, template in entry.items():
        assert _placeholders(template) == expected, (
            f"{key!r} [{language}] has {_placeholders(template)}, "
            f"expected {expected}"
        )


@pytest.mark.parametrize("key", sorted(messages.MESSAGES))
def test_no_message_is_empty(key):
    for language, template in messages.MESSAGES[key].items():
        assert template.strip(), f"{key!r} [{language}] is empty"


def test_tagalog_is_actually_translated():
    """Guards against a placeholder commit that copied English into the
    Tagalog slot. A handful of entries legitimately match (proper nouns,
    loanwords), so this asserts on the proportion, not on every row."""
    identical = [
        key
        for key, entry in messages.MESSAGES.items()
        if entry["en"] == entry["tl"]
    ]
    assert len(identical) < 3, f"suspiciously untranslated: {identical}"


# --- number grammar ----------------------------------------------------------

def test_english_inflects_nouns():
    assert messages.count_label("chair", 1, "en") == "a chair"
    assert messages.count_label("chair", 3, "en") == "3 chairs"
    assert messages.count_label("umbrella", 1, "en") == "an umbrella"


def test_english_irregular_plurals():
    """COCO's most common label is "person", whose plural is irregular."""
    assert messages.count_label("person", 1, "en") == "a person"
    assert messages.count_label("person", 4, "en") == "4 people"


def test_tagalog_does_not_inflect_nouns():
    """Tagalog marks number with a counter, not by changing the noun.
    Pluralising the English way would invent words that don't exist."""
    assert messages.count_label("chair", 1, "tl") == "isang upuan"
    assert messages.count_label("chair", 3, "tl") == "tatlong upuan"
    assert messages.count_label("person", 4, "tl") == "apat na tao"


def test_class_key_and_spoken_noun_can_differ():
    """The key is the model's contract; the value is what a listener hears."""
    assert messages.count_label("dining_table", 1, "en") == "a table"
    assert messages.count_label("stairs", 2, "en") == "2 staircases"
    assert messages.count_label("open_manhole", 1, "en") == "an open manhole"
    assert messages.count_label("jeepney", 2, "tl") == "dalawang dyip"


def test_unlabelled_class_is_spoken_not_dropped():
    """A class missing from `OBJECT_LABELS` is a bug the model-coverage test
    catches; if one slips through, saying its name beats saying nothing.
    The counter is still Tagalog."""
    assert messages.count_label("hot_air_balloon", 2, "tl") == "dalawang hot air balloon"


def test_every_label_has_every_language():
    for key, entry in messages.OBJECT_LABELS.items():
        assert set(entry) == set(messages.MESSAGES["vision.i_see"]), key


def test_join_uses_the_right_conjunction():
    assert messages.join_items(["a", "b"], "en") == "a and b"
    assert messages.join_items(["a", "b"], "tl") == "a at b"
    assert messages.join_items(["a", "b", "c"], "en") == "a, b, and c"
    assert messages.join_items(["a", "b", "c"], "tl") == "a, b, at c"


def test_join_edge_cases():
    assert messages.join_items([], "en") == ""
    assert messages.join_items(["only"], "en") == "only"


# --- lookup behaviour --------------------------------------------------------

def test_get_fills_placeholders():
    text = messages.get("nav.place_not_found", "en", location="Jollibee")
    assert "Jollibee" in text


def test_get_returns_the_requested_language():
    assert messages.get("nav.cancelled", "en") != messages.get("nav.cancelled", "tl")


def test_unknown_key_returns_the_key_rather_than_raising():
    """Raising here would propagate into the voice pipeline and the user
    would just hear nothing. Saying something odd is strictly better."""
    assert messages.get("no.such.key", "en") == "no.such.key"


def test_missing_translation_falls_back_to_english(monkeypatch):
    monkeypatch.setitem(messages.MESSAGES, "test.partial", {"en": "English only"})
    assert messages.get("test.partial", "tl") == "English only"


def test_missing_placeholder_does_not_raise():
    """A caller that forgot a field gets the raw template, not a crash."""
    result = messages.get("nav.place_not_found", "en")
    assert "location" in result


# --- distance rendering ------------------------------------------------------
#
# The wearable used to announce a cross-province geocode as "513600 meters",
# which Piper reads out in full. Under a kilometre stays in metres because
# that is the resolution a walking user acts on.

def test_short_distances_stay_in_meters():
    assert messages.speak_distance(412, "en") == "400 meters"
    assert messages.speak_distance(87, "en") == "90 meters"


def test_just_under_a_kilometre_is_still_meters():
    assert messages.speak_distance(900, "en") == "900 meters"


def test_a_kilometre_and_over_switches_unit():
    assert messages.speak_distance(1500, "en") == "1.5 kilometers"
    assert messages.speak_distance(8200, "en") == "8.2 kilometers"


def test_rounding_up_across_the_boundary_switches_unit_too():
    """950 m rounds to 1000 m, so the unit has to be chosen from the
    rounded value or it would say "1000 meters"."""
    assert messages.speak_distance(950, "en") == "1 kilometer"


def test_exactly_one_kilometre_is_singular_in_english():
    assert messages.speak_distance(1000, "en") == "1 kilometer"


def test_whole_kilometres_drop_the_decimal():
    """"2.0 kilometers" is not how anyone says it."""
    assert messages.speak_distance(2000, "en") == "2 kilometers"


def test_long_distances_drop_the_decimal_entirely():
    """513.6 km is noise on a number whose only job is to say "too far"."""
    assert messages.speak_distance(513_580, "en") == "514 kilometers"


def test_tagalog_uses_its_own_unit_words():
    assert messages.speak_distance(412, "tl") == "apat na raang metro"
    assert messages.speak_distance(8200, "tl") == "walo punto dalawang kilometro"


def test_tagalog_does_not_inflect_the_singular():
    """Tagalog nouns are not inflected for number, so one kilometre reads
    the same as any other count — unlike English, where the unit changes."""
    assert messages.speak_distance(1000, "tl") == "isang kilometro"
    assert messages.speak_distance(2000, "tl") == "dalawang kilometro"


def test_english_distances_stay_as_digits():
    """espeak-ng expands digits correctly for the English voice, so there
    is nothing to gain from spelling them out — and a regression here would
    mean the Tagalog path had leaked into English."""
    assert messages.speak_distance(412, "en") == "400 meters"
    assert messages.speak_distance(8200, "en") == "8.2 kilometers"


def test_every_language_renders_every_magnitude():
    """A missing translation here would surface as the wearable speaking a
    raw key mid-sentence."""
    for language in messages.LANGUAGES:
        for metres in (5, 87, 412, 900, 950, 1000, 1500, 8200, 513_580):
            rendered = messages.speak_distance(metres, language)
            assert "{" not in rendered, (language, metres, rendered)
            assert "distance." not in rendered, (language, metres, rendered)


# --- close-range distances ---------------------------------------------------
#
# `speak_distance` is built for navigation and floors at 10 metres, so an
# obstacle 40 cm away came out as "10 meters" — worse than saying nothing.

@pytest.mark.parametrize("centimetres,expected", [
    (42.0, "40"),
    (43.0, "40"),
    (45.0, "50"),       # halves go up, as everywhere else here
    (38.0, "40"),
    (12.0, "10"),
])
def test_proximity_rounds_to_ten_centimetres(centimetres, expected):
    assert expected in messages.speak_proximity(centimetres, "en")


def test_proximity_floors_at_ten_centimetres():
    """Below that the obstacle is already touching, the exact number has
    stopped mattering, and the sensor's own minimum range is 2 cm."""
    assert messages.speak_proximity(3.0, "en") == messages.speak_proximity(10.0, "en")
    assert messages.speak_proximity(0.0, "en").startswith("10")


def test_proximity_switches_to_metres_at_a_metre():
    """A metre is where centimetres stop being the natural unit."""
    assert "centimeter" not in messages.speak_proximity(150.0, "en")


def test_proximity_spells_the_number_out_in_tagalog():
    """Digits are effectively untrained in the MMS Tagalog voice, so a
    bare "40" is dropped silently rather than spoken."""
    spoken = messages.speak_proximity(42.0, "tl")
    assert "40" not in spoken
    assert "sentimetro" in spoken


# --- the buttons the user is told to press -----------------------------------


@pytest.mark.parametrize("language", ("en", "tl"))
def test_confirm_and_cancel_are_different_buttons(language):
    """The whole point of naming them is to tell them apart. A copy-paste
    that left both as "left" would read perfectly and send every decline
    to the button that confirms."""
    assert (messages.get("button.ptt_position", language)
            != messages.get("button.cancel_position", language))


@pytest.mark.parametrize("language", ("en", "tl"))
def test_the_three_button_positions_are_all_distinct(language):
    """Help names all three. Two sharing a word would describe a device
    the user does not have, and one of the three calls a guardian."""
    positions = [
        messages.get(f"button.{name}_position", language)
        for name in ("ptt", "cancel", "emergency")
    ]
    assert len(set(positions)) == 3, positions


@pytest.mark.parametrize("language", ("en", "tl"))
def test_help_names_every_button(language):
    """The only place a user can learn the layout. Voice commands are
    guessable; three unlabelled buttons are not, and finding the
    emergency one by experiment rings a guardian's phone."""
    spoken = messages.get(
        "help.capabilities", language,
        button=messages.get("button.ptt_position", language),
        cancel=messages.get("button.cancel_position", language),
        emergency=messages.get("button.emergency_position", language),
    )
    assert "{" not in spoken, f"unsubstituted placeholder: {spoken}"
    for name in ("ptt", "cancel", "emergency"):
        assert messages.get(f"button.{name}_position", language) in spoken


@pytest.mark.parametrize("language", ("en", "tl"))
@pytest.mark.parametrize("key", ("nav.confirm_destination", "shutdown.confirm"))
def test_every_confirmation_prompt_offers_both_answers(key, language):
    """A prompt that only says how to say yes leaves the user waiting out
    a timeout to say no — which is what both of these used to do."""
    template = messages.MESSAGES[key][language]
    assert "{button}" in template, key
    assert "{cancel}" in template, key


# --- the clock ---------------------------------------------------------------


def test_english_time_keeps_the_familiar_clock_format():
    assert messages.speak_clock(13, 4, "en") == "1:04 PM"
    assert messages.speak_clock(0, 0, "en") == "12:00 AM"
    assert messages.speak_clock(12, 30, "en") == "12:30 PM"


@pytest.mark.parametrize("hour", range(24))
@pytest.mark.parametrize("minute", (0, 1, 4, 15, 30, 45, 59))
def test_tagalog_clock_never_emits_a_digit(hour, minute):
    """The bug this helper exists for. `_handle_system_time` passed a
    finished "1:04 PM" string, and `get()` leaves strings alone by design
    — so the digits reached a voice that cannot pronounce them."""
    spoken = messages.speak_clock(hour, minute, "tl")
    assert not any(character.isdigit() for character in spoken), spoken


def test_tagalog_drops_the_minute_clause_on_the_hour():
    """"Ikaisa at sero minuto" is not something anyone says. The sentence
    is shorter, not padded — which is why this is a helper and not a
    format string."""
    assert messages.speak_clock(13, 0, "tl") == "ikaisa ng hapon"
    assert "minuto" not in messages.speak_clock(9, 0, "tl")


def test_tagalog_hour_ordinals_are_not_derived_from_the_cardinals():
    """"ikalawa"/"ikatlo", not "ikadalawa"/"ikatatlo" — the reason the
    hours are a table rather than "ika-" + `tagalog_number`."""
    assert messages.speak_clock(14, 0, "tl").startswith("ikalawa")
    assert messages.speak_clock(15, 0, "tl").startswith("ikatlo")


@pytest.mark.parametrize("hour,expected", [
    (0, "madaling araw"), (4, "madaling araw"),
    (5, "umaga"), (11, "umaga"),
    (12, "tanghali"),
    (13, "hapon"), (17, "hapon"),
    (18, "gabi"), (23, "gabi"),
])
def test_tagalog_names_the_part_of_day(hour, expected):
    """Tagalog has five named stretches of day, not two halves, so there
    is no "AM" to translate — 2 a.m. is madaling araw, not umaga."""
    assert messages.speak_clock(hour, 0, "tl").endswith(f"ng {expected}")


def test_the_time_message_survives_the_helper_end_to_end():
    spoken = messages.get(
        "time.current", "tl", time=messages.speak_clock(13, 4, "tl"),
    )
    assert not any(character.isdigit() for character in spoken), spoken
    assert "ikaisa" in spoken


# --- Tagalog never receives a bare digit -------------------------------------
#
# The MMS Tagalog voice has digits in its vocabulary but they are
# effectively untrained — the MMS-lab corpus writes numbers as words — so
# "15 porsyento" reaches the speaker as something between garbled and
# missing. Every battery percentage, volume level, satellite count and
# signal strength was silently dropping its number; only `speak_distance`
# had been routed through `speak_number`.
#
# These tests enforce it at the `get()` boundary rather than per call
# site, because the failure is invisible from the code: passing
# `percent=15` looks correct, reads correctly in English, and is only
# wrong in a language the author may not speak.

_NUMERIC_SAMPLE = 15


def _tagalog_templates_with_fields():
    """Every Tagalog message and its placeholder names."""
    import re
    for key, langs in messages.MESSAGES.items():
        tl = langs.get("tl", "")
        fields = re.findall(r"\{(\w+)\}", tl)
        if fields:
            yield key, fields


@pytest.mark.parametrize("key,fields", list(_tagalog_templates_with_fields()))
def test_no_tagalog_message_emits_a_bare_digit(key, fields):
    """Hand every placeholder a number and assert none survives as one."""
    spoken = messages.get(key, "tl", **{name: _NUMERIC_SAMPLE for name in fields})

    assert not any(character.isdigit() for character in spoken), spoken


def test_english_keeps_its_digits():
    """espeak-ng expands digits correctly for the English voice, and
    "fifteen percent" read aloud is no clearer than "15 percent"."""
    assert "15" in messages.get("battery.low_warning", "en", percent=15)


def test_floats_are_spelled_out_too():
    """`speak_distance` passes a rounded float for sub-kilometre values."""
    spoken = messages.get("distance.kilometers", "tl", value=2.5)
    assert not any(character.isdigit() for character in spoken), spoken


def test_strings_pass_through_untouched():
    """A pre-formatted value — a clock time, a coordinate — stays exactly
    as the caller intended rather than being re-interpreted."""
    assert "2:34 PM" in messages.get("time.current", "tl", time="2:34 PM")


def test_a_boolean_is_not_treated_as_a_number():
    """`bool` is an `int` in Python, so an unguarded isinstance check
    would turn True into "isa"."""
    assert "True" in messages.get("generic.error", "tl", error=True)


# --- which messages can be rendered to audio ahead of time -------------------
#
# `static_keys()` decides what `tools/render_messages.py` builds. Getting
# it wrong in one direction wastes a synthesis; in the other it caches a
# sentence with a placeholder in it, and the wearable then speaks last
# week's battery percentage forever.

def test_a_message_with_no_placeholder_is_static():
    assert "emergency.sent" in messages.static_keys()


def test_a_templated_message_is_never_static():
    """The failure that matters: a cached clip of "Battery at {percent}
    percent" would be replayed with a stale number, or with the brace
    spoken aloud."""
    for key in messages.static_keys():
        for text in messages.MESSAGES[key].values():
            assert "{" not in text, f"{key} is templated but called static"


def test_a_message_templated_in_only_one_language_is_not_static():
    """Conservative on purpose — excluding it costs one synthesis,
    including it would cache a half-filled sentence."""
    partly = {"en": "ready", "tl": "handa {name}"}
    original = messages.MESSAGES.get("test.partly_templated")
    messages.MESSAGES["test.partly_templated"] = partly
    try:
        assert "test.partly_templated" not in messages.static_keys()
    finally:
        if original is None:
            del messages.MESSAGES["test.partly_templated"]
        else:
            messages.MESSAGES["test.partly_templated"] = original


def test_every_static_key_resolves_in_every_language():
    """The renderer calls `get()` for each; an unknown key would return
    the key itself and the device would say "emergency dot sent"."""
    for key in messages.static_keys():
        for language in messages.MESSAGES[key]:
            assert messages.get(key, language) == messages.MESSAGES[key][language]


def test_the_boot_clips_are_static():
    """`_BOOT_CLIPS` are rendered at the end of `start()` with no
    placeholder values available to fill in."""
    from indepensense.app import _BOOT_CLIPS
    assert set(_BOOT_CLIPS) <= set(messages.static_keys())


def test_every_class_the_deployed_detector_can_report_has_a_spoken_label():
    """Reads the committed model's own class list, so retraining with a new
    class fails here instead of on the device, where the class would be
    spoken as its raw key."""
    from indepensense.config import YOLO_MODEL_DIR
    from indepensense.vision.ncnn_detector import read_metadata

    names, _ = read_metadata(YOLO_MODEL_DIR)
    missing = [n for n in names if n not in messages.OBJECT_LABELS]
    assert not missing, f"detector classes without a spoken label: {missing}"
