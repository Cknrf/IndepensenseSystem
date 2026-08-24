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
    assert messages.count_label("chair", 3, "tl") == "3 upuan"
    assert messages.count_label("person", 4, "tl") == "4 tao"


def test_untranslated_labels_fall_through_to_english():
    """Deliberate: Manila speech code-switches, and forcing a Tagalog
    coinage for every COCO class would sound worse than the English word."""
    assert messages.count_label("skateboard", 2, "tl") == "2 skateboard"


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
