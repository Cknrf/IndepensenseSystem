"""Unit tests for the LLM-response parser.

These test `parse_llm_response`, the pure function that turns a JSON string
into a normalised `IntentResult`. No LLM or Ollama server is required.
"""
import json

from indepensense.intents.base import Intent
from indepensense.intents.parser import _normalise_parameters, parse_llm_response


def test_navigation_start_with_nearest_true():
    raw = json.dumps({
        "intent": "navigation.start",
        "parameters": {"location": "hospital", "nearest": True},
    })
    result = parse_llm_response(raw, "guide me to the nearest hospital")
    assert result.intent is Intent.NAVIGATION_START
    assert result.parameters == {"location": "hospital", "nearest": True}


def test_navigation_start_injects_missing_nearest_as_false():
    # LLM sometimes omits `nearest` when the user didn't say a modifier.
    # The parser must inject `nearest: False` so the executor never guesses.
    raw = json.dumps({
        "intent": "navigation.start",
        "parameters": {"location": "Jollibee"},
    })
    result = parse_llm_response(raw, "take me to Jollibee")
    assert result.intent is Intent.NAVIGATION_START
    assert result.parameters == {"location": "Jollibee", "nearest": False}


def test_navigation_start_string_nearest_coerced_to_bool():
    raw = json.dumps({
        "intent": "navigation.start",
        "parameters": {"location": "hospital", "nearest": "true"},
    })
    result = parse_llm_response(raw, "nearest hospital")
    assert result.parameters["nearest"] is True


def test_unknown_intent_strips_hallucinated_parameters():
    # LLM sometimes invents parameters for unknown intents.
    # The parser drops them so the executor can safely ignore them.
    raw = json.dumps({
        "intent": "unknown",
        "parameters": {"destination": "the moon", "reason": "hallucinated"},
    })
    result = parse_llm_response(raw, "send a rocket to the moon")
    assert result.intent is Intent.UNKNOWN
    assert result.parameters == {}


def test_unknown_intent_name_maps_to_unknown():
    # If the LLM invents an intent name we don't support, degrade to UNKNOWN
    # rather than raising ValueError.
    raw = json.dumps({"intent": "music.play", "parameters": {}})
    result = parse_llm_response(raw, "play some music")
    assert result.intent is Intent.UNKNOWN


def test_malformed_json_maps_to_unknown():
    result = parse_llm_response("this is not JSON", "some transcript")
    assert result.intent is Intent.UNKNOWN
    assert result.parameters == {}
    assert result.raw_transcript == "some transcript"
    assert result.raw_llm_response == "this is not JSON"


def test_missing_parameters_field_defaults_to_empty():
    raw = json.dumps({"intent": "system.time"})
    result = parse_llm_response(raw, "what time is it")
    assert result.intent is Intent.SYSTEM_TIME
    assert result.parameters == {}


def test_non_dict_parameters_field_becomes_empty():
    # Defensive against the LLM returning something weird for parameters.
    raw = json.dumps({"intent": "system.time", "parameters": "not a dict"})
    result = parse_llm_response(raw, "what time is it")
    assert result.intent is Intent.SYSTEM_TIME
    assert result.parameters == {}


def test_device_status_preserves_status_field():
    raw = json.dumps({
        "intent": "device.status",
        "parameters": {"status_field": "battery"},
    })
    result = parse_llm_response(raw, "how much battery")
    assert result.intent is Intent.DEVICE_STATUS
    assert result.parameters == {"status_field": "battery"}


# --- system.language normalisation ------------------------------------------

def test_language_name_is_folded_to_a_code():
    """Small models return "English" instead of "en" often enough that a
    switch failing on it would be an avoidable dead end for the user."""
    result = _normalise_parameters(Intent.SYSTEM_LANGUAGE, {"language": "English"})
    assert result["language"] == "en"


def test_tagalog_aliases_fold_to_tl():
    for name in ("Tagalog", "tagalog", "Filipino", "TL", "fil"):
        result = _normalise_parameters(Intent.SYSTEM_LANGUAGE, {"language": name})
        assert result["language"] == "tl", name


def test_unrecognised_language_is_passed_through_not_defaulted():
    """Substituting a supported language the user didn't ask for would be
    worse than telling them it's unsupported."""
    result = _normalise_parameters(Intent.SYSTEM_LANGUAGE, {"language": "German"})
    assert result["language"] == "german"


def test_missing_language_becomes_empty_string():
    result = _normalise_parameters(Intent.SYSTEM_LANGUAGE, {})
    assert result["language"] == ""


def test_non_string_language_becomes_empty_string():
    result = _normalise_parameters(Intent.SYSTEM_LANGUAGE, {"language": 42})
    assert result["language"] == ""
