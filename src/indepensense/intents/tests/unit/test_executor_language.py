"""Unit tests for language switching and per-language responses.

These assert on *behaviour* — that the executor answers in the active
language and that a switch takes effect immediately — rather than on the
exact Tagalog wording, which lives in `messages.py` and should be free to
be reworded without breaking tests.
"""
from indepensense.intents import messages
from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.language import LanguageState
from indepensense.routing.mock import MockGeocoder, MockRouter
from indepensense.vision.mock import MockCamera, MockDetector, MockOCR

SUPPORTED = ("en", "tl")


def _executor(default="tl", **kwargs):
    return IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        language=LanguageState(default, SUPPORTED),
        **kwargs,
    )


def _switch(language: str) -> IntentResult:
    return IntentResult(Intent.SYSTEM_LANGUAGE, {"language": language})


# --- switching ---------------------------------------------------------------

def test_switch_to_english_confirms_in_english():
    """The confirmation is spoken in the language being switched TO, so
    hearing it verifies the switch worked — the user cannot read a screen."""
    executor = _executor(default="tl")
    assert executor.execute(_switch("en")) == messages.get("language.switched", "en")


def test_switch_to_tagalog_confirms_in_tagalog():
    executor = _executor(default="en")
    assert executor.execute(_switch("tl")) == messages.get("language.switched", "tl")


def test_switch_takes_effect_on_the_very_next_response():
    """The executor is built once at startup; a switch it handles itself
    must be visible immediately, which is why language is shared state
    rather than a constructor copy."""
    executor = _executor(default="tl")
    executor.execute(_switch("en"))

    response = executor.execute(IntentResult(Intent.NAVIGATION_STOP))
    assert response == messages.get("nav.none_active", "en")


def test_switching_to_the_active_language_says_so():
    executor = _executor(default="en")
    assert executor.execute(_switch("en")) == messages.get("language.already", "en")


def test_unsupported_language_is_refused_in_the_current_language():
    """Answering in the *current* language matters here — the user still
    understands the refusal, and we haven't switched to anything."""
    executor = _executor(default="tl")
    assert executor.execute(_switch("de")) == messages.get("language.unsupported", "tl")


def test_missing_language_parameter_is_refused():
    executor = _executor(default="tl")
    result = executor.execute(IntentResult(Intent.SYSTEM_LANGUAGE, {}))
    assert result == messages.get("language.unsupported", "tl")


def test_switching_back_and_forth_works():
    executor = _executor(default="tl")
    executor.execute(_switch("en"))
    executor.execute(_switch("tl"))
    assert executor.execute(IntentResult(Intent.NAVIGATION_STOP)) == messages.get(
        "nav.none_active", "tl"
    )


# --- responses follow the active language ------------------------------------

def test_unknown_intent_answers_in_the_active_language():
    assert _executor("tl").execute(IntentResult(Intent.UNKNOWN)) == messages.get(
        "generic.unknown_intent", "tl"
    )
    assert _executor("en").execute(IntentResult(Intent.UNKNOWN)) == messages.get(
        "generic.unknown_intent", "en"
    )


def test_navigation_without_destination_answers_in_active_language():
    executor = _executor("tl")
    response = executor.execute(IntentResult(Intent.NAVIGATION_START, {"location": ""}))
    assert response == messages.get("nav.no_destination_heard", "tl")


def test_scene_description_uses_tagalog_number_grammar():
    """Tagalog leaves the noun bare with a counter. The mock detector
    returns one person and one chair."""
    executor = _executor("tl", camera=MockCamera(), detector=MockDetector())
    response = executor.execute(IntentResult(Intent.VISION_DESCRIBE))

    assert "isang tao" in response
    assert "isang upuan" in response
    assert " at " in response          # Tagalog conjunction, not "and"
    assert "chairs" not in response    # no English pluralisation leaked


def test_scene_description_uses_english_pluralisation():
    executor = _executor("en", camera=MockCamera(), detector=MockDetector())
    response = executor.execute(IntentResult(Intent.VISION_DESCRIBE))

    assert "a person" in response
    assert "a chair" in response
    assert " and " in response


def test_ocr_reads_in_the_active_language():
    """`vision.read` must pass the *active* language to Tesseract, not the
    one that was active at construction."""
    ocr = MockOCR()
    executor = _executor("tl", camera=MockCamera(), ocr=ocr)

    assert "LABASAN" in executor.execute(IntentResult(Intent.VISION_READ))

    executor.execute(_switch("en"))
    assert "EXIT" in executor.execute(IntentResult(Intent.VISION_READ))


def test_repeat_replays_the_response_as_spoken():
    """Repeat returns the stored text verbatim. It does not re-translate —
    the user asked to hear the same thing again."""
    executor = _executor("tl")
    first = executor.execute(IntentResult(Intent.NAVIGATION_STOP))
    assert executor.execute(IntentResult(Intent.NAVIGATION_REPEAT)) == first


def test_switch_confirmation_is_repeatable():
    """A switch response is a normal response, so Repeat should replay it
    rather than reporting nothing to repeat."""
    executor = _executor("tl")
    confirmation = executor.execute(_switch("en"))
    assert executor.execute(IntentResult(Intent.NAVIGATION_REPEAT)) == confirmation
