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
        def answer(self, question, language):
            return CloudAnswer(text=text, reason="ok")

    assert _executor(cloud=_Empty()).execute(_unknown()) == messages.get(
        "cloud.error", "en"
    )


def test_a_raising_provider_does_not_break_the_pipeline():
    """The protocol says answerers don't raise, but a driver bug must
    surface as a spoken message rather than as silence."""
    class _Exploding:
        def answer(self, question, language):
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
