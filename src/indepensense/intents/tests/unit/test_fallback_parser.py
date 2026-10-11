"""Unit tests for `FallbackIntentParser`.

Two fake parsers, no network, no Ollama. The behaviour under test is
entirely about *when* the handover happens, and the case that matters
most is the one where it must not: a clean `unknown` is a decline, not a
failure, and falling back on it would break the cloud answerer and hand
the utterance to the engine with the worse `unknown` recall.
"""
import pytest

from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.fallback import FallbackIntentParser


class FakeParser:
    """Returns a scripted result and records what it was asked."""

    def __init__(self, result=None, raises=None, warm_raises=None):
        self._result = result
        self._raises = raises
        self._warm_raises = warm_raises
        self.calls: list[str] = []
        self.warmed: list[float] = []
        self.closed = False

    def parse(self, transcript: str) -> IntentResult:
        self.calls.append(transcript)
        if self._raises is not None:
            raise self._raises
        return self._result

    def warm_up(self, timeout_s: float) -> None:
        self.warmed.append(timeout_s)
        if self._warm_raises is not None:
            raise self._warm_raises

    def close(self) -> None:
        self.closed = True


def _result(intent=Intent.SYSTEM_TIME, failure=None, source="cloud", **kw):
    return IntentResult(intent=intent, failure=failure, source=source, **kw)


# --- the primary answers ------------------------------------------------------

def test_a_successful_primary_result_is_returned_untouched():
    primary = FakeParser(_result(Intent.NAVIGATION_START, source="cloud"))
    fallback = FakeParser(_result(Intent.UNKNOWN, source="llm"))

    result = FallbackIntentParser(primary, fallback).parse("take me home")

    assert result.intent is Intent.NAVIGATION_START
    assert result.source == "cloud"
    assert fallback.calls == []


def test_a_clean_unknown_does_not_fall_back():
    """The case this class most has to get right.

    `unknown` with no failure is a decline, and it is the cloud
    answerer's trigger in `cloud.py`. Falling back would spend a local
    inference re-answering a correct answer, and the local model's much
    lower `unknown` recall would often turn a genuine open question into
    a bogus intent.
    """
    primary = FakeParser(_result(Intent.UNKNOWN, failure=None, source="cloud"))
    fallback = FakeParser(_result(Intent.SYSTEM_TIME, source="llm"))

    result = FallbackIntentParser(primary, fallback).parse("how tall is Mount Apo")

    assert result.intent is Intent.UNKNOWN
    assert result.source == "cloud"
    assert fallback.calls == [], "a decline is not a failure"


# --- the primary fails --------------------------------------------------------

@pytest.mark.parametrize("failure", ["transport", "malformed"])
def test_a_failed_primary_hands_over_to_the_fallback(failure):
    primary = FakeParser(_result(Intent.UNKNOWN, failure=failure, source="cloud"))
    fallback = FakeParser(_result(Intent.SYSTEM_TIME, source="llm"))

    result = FallbackIntentParser(primary, fallback).parse("what time is it")

    assert result.intent is Intent.SYSTEM_TIME
    assert result.source == "llm"
    assert fallback.calls == ["what time is it"]


def test_a_raising_primary_hands_over_rather_than_propagating():
    """This runs on the voice thread, where an escaping exception reaches
    the user as silence — with a working local model one line away."""
    primary = FakeParser(raises=RuntimeError("provider SDK blew up"))
    fallback = FakeParser(_result(Intent.SYSTEM_TIME, source="llm"))

    result = FallbackIntentParser(primary, fallback).parse("what time is it")

    assert result.intent is Intent.SYSTEM_TIME
    assert fallback.calls == ["what time is it"]


def test_the_fallbacks_own_failure_is_reported_honestly():
    """Both engines down must stay visible. Rewriting it into a bare
    decline would tell `cloud.py` the utterance was understood and
    refused, which is exactly the confusion `IntentResult.failure`
    exists to prevent."""
    primary = FakeParser(_result(Intent.UNKNOWN, failure="transport", source="cloud"))
    fallback = FakeParser(_result(Intent.UNKNOWN, failure="transport", source="llm"))

    result = FallbackIntentParser(primary, fallback).parse("what time is it")

    assert result.failure == "transport"
    assert result.source == "llm"


def test_the_transcript_reaches_the_fallback_unmodified():
    primary = FakeParser(_result(Intent.UNKNOWN, failure="transport"))
    fallback = FakeParser(_result(Intent.UNKNOWN))

    FallbackIntentParser(primary, fallback).parse("dalhin mo ako sa Jollibee")

    assert fallback.calls == ["dalhin mo ako sa Jollibee"]


# --- warmup and teardown ------------------------------------------------------

def test_both_engines_are_warmed_with_the_full_budget():
    """Not split between them: they warm different things, and halving
    the local model's allowance would time it out for no reason."""
    primary, fallback = FakeParser(), FakeParser()

    FallbackIntentParser(primary, fallback).warm_up(90.0)

    assert primary.warmed == [90.0]
    assert fallback.warmed == [90.0]


def test_a_failed_primary_warmup_does_not_stop_the_fallback_warming():
    """Startup must survive a cold link. The device is then slower, not
    broken — and the local model still needs its prefill."""
    primary = FakeParser(warm_raises=RuntimeError("no route"))
    fallback = FakeParser()

    FallbackIntentParser(primary, fallback).warm_up(90.0)

    assert fallback.warmed == [90.0]


def test_an_engine_without_warm_up_is_skipped():
    """`IntentParser` does not require `warm_up`; the mock parser has
    none."""
    class Bare:
        def parse(self, transcript):
            return _result()

    FallbackIntentParser(Bare(), FakeParser()).warm_up(10.0)   # must not raise


def test_close_releases_both_engines():
    primary, fallback = FakeParser(), FakeParser()

    FallbackIntentParser(primary, fallback).close()

    assert primary.closed and fallback.closed
