"""Unit tests for the cloud LLM fallback on unknown intents."""
import pytest
import requests

from indepensense.intents import messages
from indepensense.intents.base import CloudAnswer, Intent, IntentResult
from indepensense.intents.cloud import OfflineGuard
from indepensense.intents.executor import IntentExecutor
from indepensense.intents.mock import MockCloudAnswerer
from indepensense.language import LanguageState
from indepensense.routing.mock import MockGeocoder, MockRouter

SUPPORTED = ("en", "tl")


def _executor(cloud=None, default="en", **kwargs):
    return IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        language=LanguageState(default, SUPPORTED),
        cloud=cloud,
        **kwargs,
    )


def _unknown(transcript="how tall is Mount Apo") -> IntentResult:
    return IntentResult(Intent.UNKNOWN, {}, transcript, "")


# --- no cloud configured -----------------------------------------------------

def test_without_cloud_unknown_behaves_as_before():
    """The fallback must be additive — with no answerer wired the wearable
    answers exactly as it did before this feature existed."""
    executor = _executor(cloud=None)
    assert executor.execute(_unknown()) == messages.get("generic.unknown_intent", "en")


# --- forwarding --------------------------------------------------------------

def test_unknown_is_forwarded_and_the_answer_spoken():
    cloud = MockCloudAnswerer(text="Mount Apo is 2,954 meters tall.")
    executor = _executor(cloud=cloud)

    assert executor.execute(_unknown()) == "Mount Apo is 2,954 meters tall."
    assert cloud.asked == [("how tall is Mount Apo", "en")]


def test_the_active_language_is_passed_to_the_provider():
    """The provider answers in the user's language rather than us
    translating afterwards."""
    cloud = MockCloudAnswerer()
    executor = _executor(cloud=cloud, default="tl")

    executor.execute(_unknown("gaano katangkad ang Bundok Apo"))
    assert cloud.asked == [("gaano katangkad ang Bundok Apo", "tl")]


def test_a_switched_language_reaches_the_provider():
    cloud = MockCloudAnswerer()
    executor = _executor(cloud=cloud, default="tl")
    executor.execute(IntentResult(Intent.SYSTEM_LANGUAGE, {"language": "en"}))

    executor.execute(_unknown("what is the capital of Japan"))
    assert cloud.asked[-1][1] == "en"


def test_only_unknown_intents_are_forwarded():
    """The whole design rests on this: a real command must never reach the
    cloud instead of its handler."""
    cloud = MockCloudAnswerer()
    executor = _executor(cloud=cloud)

    executor.execute(IntentResult(Intent.NAVIGATION_STOP, {}, "cancel navigation", ""))
    executor.execute(IntentResult(Intent.SYSTEM_TIME, {}, "what time is it", ""))
    assert cloud.asked == []


@pytest.mark.parametrize("failure", ["transport", "malformed"])
def test_a_parse_failure_is_not_forwarded(failure):
    """The premise of the whole fallback is that the cloud only ever sees
    what the local model declined. A timeout or unreadable JSON means the
    model never usably answered, so the utterance might have been a real
    command — observed on the Pi, where a 30 s Ollama timeout sent "how
    tall is Mount Apo" to Mistral and would have sent a navigation command
    just the same."""
    cloud = MockCloudAnswerer()
    executor = _executor(cloud=cloud)
    result = IntentResult(
        Intent.UNKNOWN, {}, "take me to the hospital", "", failure=failure,
    )

    assert executor.execute(result) == messages.get("generic.unknown_intent", "en")
    assert cloud.asked == []


def test_a_genuine_decline_is_still_forwarded():
    """The guard must not close the door on the case the feature exists
    for: the model ran, understood it was not a command, and said so."""
    cloud = MockCloudAnswerer()
    executor = _executor(cloud=cloud)

    executor.execute(_unknown("how tall is Mount Apo"))
    assert cloud.asked == [("how tall is Mount Apo", "en")]


def test_empty_transcript_is_not_forwarded():
    """Sending an empty string would spend a paid API call to be told
    nothing."""
    cloud = MockCloudAnswerer()
    executor = _executor(cloud=cloud)

    assert executor.execute(_unknown("   ")) == messages.get(
        "generic.unknown_intent", "en"
    )
    assert cloud.asked == []


# --- failure paths -----------------------------------------------------------

def test_offline_says_so_specifically():
    """"No internet" is actionable — the user can move somewhere with
    signal. A generic error is not."""
    executor = _executor(cloud=MockCloudAnswerer(reason="offline"))
    assert executor.execute(_unknown()) == messages.get("cloud.offline", "en")


def test_provider_error_is_reported_differently_from_offline():
    executor = _executor(cloud=MockCloudAnswerer(reason="error"))
    response = executor.execute(_unknown())
    assert response == messages.get("cloud.error", "en")
    assert response != messages.get("cloud.offline", "en")


def test_failure_messages_follow_the_active_language():
    executor = _executor(cloud=MockCloudAnswerer(reason="offline"), default="tl")
    assert executor.execute(_unknown()) == messages.get("cloud.offline", "tl")


@pytest.mark.parametrize("text", [None, "", "   "])
def test_an_empty_answer_is_treated_as_an_error(text):
    """A provider that returns nothing while claiming success must not
    leave the wearable silent.

    Uses a local stub rather than `MockCloudAnswerer`, whose `text=None`
    means "use the default echo" — it cannot express "returned nothing".
    """
    class _Empty:
        def answer(self, question, language, previous=None):
            return CloudAnswer(text=text, reason="ok")

    assert _executor(cloud=_Empty()).execute(_unknown()) == messages.get(
        "cloud.error", "en"
    )


def test_a_raising_provider_does_not_break_the_pipeline():
    """The protocol says answerers don't raise, but a driver bug must
    surface as a spoken message rather than as silence."""
    class _Exploding:
        def answer(self, question, language, previous=None):
            raise RuntimeError("driver bug")

    response = _executor(cloud=_Exploding()).execute(_unknown())
    assert response  # something is spoken
    assert "driver bug" in response or response == messages.get("cloud.error", "en")


# --- length ------------------------------------------------------------------

def test_long_answers_are_truncated_for_speech():
    """The answer is spoken by Piper — three paragraphs is a 90-second
    monologue."""
    cloud = MockCloudAnswerer(text="x" * 900)
    executor = _executor(cloud=cloud, cloud_max_chars=100)

    response = executor.execute(_unknown())
    assert len(response) < 200
    assert response.endswith(messages.get("vision.truncated_suffix", "en"))


def test_short_answers_are_left_alone():
    cloud = MockCloudAnswerer(text="Manila.")
    assert _executor(cloud=cloud, cloud_max_chars=100).execute(_unknown()) == "Manila."


# --- the offline guard -------------------------------------------------------

def test_guard_short_circuits_when_offline(monkeypatch):
    """Nothing is sent anywhere when we're offline — the guard exists so
    the voice pipeline can skip the "thinking" cue too."""
    monkeypatch.setattr(requests, "head", _raising_head)
    inner = MockCloudAnswerer()
    guard = OfflineGuard(inner, probe_url="http://probe.test")

    result = guard.answer("anything", "en")
    assert result.reason == "offline"
    assert result.text is None
    assert inner.asked == []


def test_guard_forwards_when_online(monkeypatch):
    monkeypatch.setattr(requests, "head", _ok_head)
    inner = MockCloudAnswerer(text="an answer")
    guard = OfflineGuard(inner, probe_url="http://probe.test")

    assert guard.answer("anything", "en") == CloudAnswer(text="an answer", reason="ok")
    assert inner.asked == [("anything", "en")]


def test_guard_reports_online_state(monkeypatch):
    monkeypatch.setattr(requests, "head", _ok_head)
    guard = OfflineGuard(MockCloudAnswerer(), probe_url="http://probe.test")
    assert guard.is_online() is True

    monkeypatch.setattr(requests, "head", _raising_head)
    assert guard.is_online() is False


def _ok_head(url, **kwargs):
    response = requests.Response()
    response.status_code = 200
    return response


def _raising_head(url, **kwargs):
    raise requests.ConnectionError("simulated offline")


# --- follow-up context -------------------------------------------------------
#
# People ask follow-ups. The field log has a user asking "what about I
# want to know what's the answer regarding 5-7?", being told the device
# did not understand, and rephrasing the same question twice more. A
# second question that depends on the first was simply unanswerable.

def test_the_first_question_carries_no_context():
    cloud = MockCloudAnswerer(text="Mount Apo.")
    _executor(cloud=cloud).execute(_unknown("what is the tallest mountain"))

    assert cloud.context == [None]


def test_a_follow_up_carries_the_previous_exchange():
    cloud = MockCloudAnswerer(text="Mount Apo.")
    executor = _executor(cloud=cloud)

    executor.execute(_unknown("what is the tallest mountain"))
    executor.execute(_unknown("what about the second"))

    assert cloud.context[-1] == ("what is the tallest mountain", "Mount Apo.")


def test_only_one_turn_is_kept():
    """A history would cost tokens on every question to serve a
    conversation the user cannot scroll back through anyway."""
    cloud = MockCloudAnswerer(text="an answer")
    executor = _executor(cloud=cloud)

    executor.execute(_unknown("first"))
    executor.execute(_unknown("second"))
    executor.execute(_unknown("third"))

    assert cloud.context[-1] == ("second", "an answer")


def test_a_failed_exchange_is_not_remembered():
    """Remembering "I couldn't get an answer" as the assistant's turn
    would have the model build on an apology."""
    executor = _executor(cloud=MockCloudAnswerer(reason="error"))
    executor.execute(_unknown("what is the tallest mountain"))

    working = MockCloudAnswerer(text="Manila.")
    executor._cloud = working
    executor.execute(_unknown("what about the capital"))

    assert working.context == [None]


def test_the_full_answer_is_remembered_not_the_truncated_one():
    """Truncation exists so a long reply is not spoken at length. Feeding
    the clipped version back would have the model build on a sentence that
    stops mid-word."""
    cloud = MockCloudAnswerer(text="y" * 900)
    executor = _executor(cloud=cloud, cloud_max_chars=100)

    executor.execute(_unknown("tell me a long thing"))
    executor.execute(_unknown("and then"))

    assert cloud.context[-1][1] == "y" * 900


def test_context_expires():
    """A pronoun resolves against what was *just* said. Silently attaching
    a question asked ten minutes later to an old one is how "what about
    the second" gets answered about the wrong subject."""
    cloud = MockCloudAnswerer(text="Mount Apo.")
    executor = _executor(cloud=cloud, cloud_context_ttl_s=120.0)

    executor.execute(_unknown("what is the tallest mountain"))
    question, answer, asked_at = executor._last_exchange
    executor._last_exchange = (question, answer, asked_at - 600.0)

    executor.execute(_unknown("what about the second"))
    assert cloud.context[-1] is None


def test_context_inside_the_window_survives():
    cloud = MockCloudAnswerer(text="Mount Apo.")
    executor = _executor(cloud=cloud, cloud_context_ttl_s=120.0)

    executor.execute(_unknown("what is the tallest mountain"))
    question, answer, asked_at = executor._last_exchange
    executor._last_exchange = (question, answer, asked_at - 60.0)

    executor.execute(_unknown("what about the second"))
    assert cloud.context[-1] is not None


def test_a_language_switch_drops_the_context():
    """The stored turn is in the language just left. Replaying it while
    instructing the provider to answer in the new one is a contradiction
    the model resolves by guessing."""
    cloud = MockCloudAnswerer(text="Mount Apo.")
    executor = _executor(cloud=cloud, default="en")

    executor.execute(_unknown("what is the tallest mountain"))
    executor.execute(IntentResult(Intent.SYSTEM_LANGUAGE, {"language": "tl"}))
    executor.execute(_unknown("ano ang pangalawa"))

    assert cloud.context[-1] is None


def test_a_no_op_language_switch_keeps_the_context():
    """Asking for the language already in use changes nothing, so it must
    not quietly discard the conversation."""
    cloud = MockCloudAnswerer(text="Mount Apo.")
    executor = _executor(cloud=cloud, default="en")

    executor.execute(_unknown("what is the tallest mountain"))
    executor.execute(IntentResult(Intent.SYSTEM_LANGUAGE, {"language": "en"}))
    executor.execute(_unknown("what about the second"))

    assert cloud.context[-1] is not None


def test_a_local_intent_does_not_become_cloud_context():
    """A follow-up like "what about now" after `vision.describe` cannot be
    served by a cloud model — it has no camera — and handing it "I see a
    window" would invite a confident answer about a scene the provider
    never saw."""
    cloud = MockCloudAnswerer(text="Mount Apo.")
    executor = _executor(cloud=cloud)

    executor.execute(_unknown("what is the tallest mountain"))
    executor.execute(IntentResult(Intent.SYSTEM_TIME, {}, "what time is it", ""))
    executor.execute(_unknown("what about the second"))

    assert cloud.context[-1] == ("what is the tallest mountain", "Mount Apo.")
