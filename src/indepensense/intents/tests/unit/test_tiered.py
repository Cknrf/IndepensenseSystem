"""Unit tests for the two-stage parser.

No model and no Ollama. Both stages are stubbed, because what is under
test is the *routing* — which engine answers, what the result claims
about itself, and what happens when a stage misbehaves. The matcher's
own accuracy is measured by `tests/manual/embedding_probe.py`; asserting
it here would be asserting against a stub.
"""
import pytest

from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.embeddings import Match
from indepensense.intents.tiered import TieredIntentParser, describe


class StubMatcher:
    """Returns a scripted `Match` (or None) and records what it saw."""

    def __init__(self, result=None, raises=None):
        self._result = result
        self._raises = raises
        self.seen: list[str] = []

    def match(self, transcript: str):
        self.seen.append(transcript)
        if self._raises:
            raise self._raises
        return self._result


class StubLLM:
    def __init__(self, result=None):
        self._result = result or IntentResult(
            intent=Intent.UNKNOWN, raw_transcript="", failure=None
        )
        self.calls = 0

    def parse(self, transcript: str) -> IntentResult:
        self.calls += 1
        return IntentResult(
            intent=self._result.intent,
            parameters=dict(self._result.parameters),
            raw_transcript=transcript,
            raw_llm_response=self._result.raw_llm_response,
            failure=self._result.failure,
        )


def a_match(intent=Intent.VISION_READ, parameters=None) -> Match:
    return Match(
        intent=intent,
        parameters=parameters or {},
        score=0.93,
        margin=0.05,
        matched_example="Read the text",
    )


# ------------------------------------------------------------- fast path

def test_a_hit_answers_without_calling_the_llm():
    llm = StubLLM()
    parser = TieredIntentParser(StubMatcher(a_match()), llm)

    result = parser.parse("Read the label")

    assert result.intent is Intent.VISION_READ
    assert result.source == "embedding"
    assert llm.calls == 0


def test_a_hit_carries_an_enum_slot_through():
    match = a_match(Intent.DEVICE_STATUS, {"status_field": "battery"})
    parser = TieredIntentParser(StubMatcher(match), StubLLM())

    assert parser.parse("battery?").parameters == {"status_field": "battery"}


def test_a_hit_is_not_a_failure():
    """`failure` must stay None, or `cloud.py`'s premise breaks.

    `failure` means "we hold no usable classification". A fast-path
    answer is the opposite of that, and a non-None value here would make
    a successful classification indistinguishable from an Ollama
    timeout.
    """
    parser = TieredIntentParser(StubMatcher(a_match()), StubLLM())
    assert parser.parse("Read the label").failure is None


def test_a_hit_records_an_audit_trail():
    """A wrong fast-path action must be explainable after the fact."""
    parser = TieredIntentParser(StubMatcher(a_match()), StubLLM())
    raw = parser.parse("Read the label").raw_llm_response
    assert "Read the text" in raw and "0.93" in raw


# ------------------------------------------------------------ escalation

def test_a_miss_falls_through_to_the_llm():
    llm = StubLLM(IntentResult(intent=Intent.NAVIGATION_START))
    parser = TieredIntentParser(StubMatcher(None), llm)

    result = parser.parse("Take me to SM Lipa")

    assert result.intent is Intent.NAVIGATION_START
    assert result.source == "llm"
    assert llm.calls == 1


def test_no_matcher_sends_everything_to_the_llm():
    """The degraded state is the pre-existing behaviour, not an error."""
    llm = StubLLM()
    parser = TieredIntentParser(None, llm)

    parser.parse("anything")

    assert llm.calls == 1


def test_a_broken_matcher_degrades_instead_of_failing_the_utterance(capsys):
    """The user is mid-command; the LLM can still answer."""
    llm = StubLLM()
    parser = TieredIntentParser(StubMatcher(raises=RuntimeError("model gone")), llm)

    result = parser.parse("Read the label")

    assert llm.calls == 1
    assert result.source == "llm"
    assert "model gone" in capsys.readouterr().err


def test_the_llms_failure_reason_survives_escalation():
    """An Ollama timeout must still read as a transport failure.

    This is the invariant `cloud.py` depends on: a transcript the LLM
    never classified must not reach the cloud. Escalating through the
    fast path may not launder that away.
    """
    llm = StubLLM(IntentResult(intent=Intent.UNKNOWN, failure="transport"))
    parser = TieredIntentParser(StubMatcher(None), llm)

    assert parser.parse("take me to the hospital").failure == "transport"


def test_the_transcript_reaches_both_stages_unmodified():
    matcher = StubMatcher(None)
    llm = StubLLM()
    parser = TieredIntentParser(matcher, llm)

    parser.parse("  Nasaan ako  ")

    assert matcher.seen == ["  Nasaan ako  "]


# -------------------------------------------------------------- describe

@pytest.mark.parametrize(
    "result, expected",
    [
        (
            IntentResult(intent=Intent.VISION_READ, source="embedding"),
            "vision.read via embedding",
        ),
        (
            IntentResult(intent=Intent.NAVIGATION_START),
            "navigation.start via llm",
        ),
        (
            IntentResult(intent=Intent.UNKNOWN),
            "unknown via llm [declined]",
        ),
        (
            IntentResult(intent=Intent.UNKNOWN, failure="transport"),
            "unknown via llm [transport]",
        ),
    ],
)
def test_describe_distinguishes_a_decline_from_a_failure(result, expected):
    """The two look identical in a log line otherwise, and they are not.

    A decline is the cloud fallback's entry point; a failure must never
    reach it. Debugging the difference from `journalctl` was expensive
    once already — see `parser.parse_llm_response`.
    """
    assert describe(result) == expected
