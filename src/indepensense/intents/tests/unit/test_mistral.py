"""Unit tests for the Mistral cloud answerer.

No network: `requests.Session.post` is monkeypatched. These verify the
request we send and, more importantly, that every malformed response
becomes a `CloudAnswer(reason="error")` rather than an exception — this
runs on the voice thread, where a raise reaches the user as silence.
"""
import json

import pytest
import requests

from indepensense.intents.cloud import OfflineGuard
from indepensense.intents.mistral import MistralAnswerer


def _response(status_code=200, payload=None, body=None):
    response = requests.Response()
    response.status_code = status_code
    if body is not None:
        response._content = body.encode()
    else:
        response._content = json.dumps(payload or {}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _ok_payload(text="Mount Apo is 2,954 meters tall."):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture
def answerer():
    return MistralAnswerer(api_key="test-key", model="mistral-small-latest")


def _capture(monkeypatch, response=None, raises=None):
    """Patch Session.post and record what was sent."""
    sent = {}

    def _post(self, url, json=None, headers=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        sent["timeout"] = timeout
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(requests.Session, "post", _post)
    return sent


# --- construction ------------------------------------------------------------

def test_an_empty_api_key_is_rejected_at_construction():
    """Fail loudly at startup rather than on the first question a user
    asks, which would be far from the cause."""
    with pytest.raises(ValueError):
        MistralAnswerer(api_key="", model="mistral-small-latest")


def test_construction_does_no_io(monkeypatch):
    """The session is created lazily, so building the answerer during
    startup cannot block on the network."""
    def _explode(*args, **kwargs):
        raise AssertionError("no I/O should happen at construction")

    monkeypatch.setattr(requests, "Session", _explode)
    MistralAnswerer(api_key="k", model="m")


# --- the request -------------------------------------------------------------

def test_a_successful_answer_is_returned(answerer, monkeypatch):
    _capture(monkeypatch, response=_response(payload=_ok_payload()))

    result = answerer.answer("How tall is Mount Apo", "en")
    assert result.reason == "ok"
    assert result.text == "Mount Apo is 2,954 meters tall."


def test_the_key_is_sent_as_a_bearer_token(answerer, monkeypatch):
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("q", "en")
    assert sent["headers"]["Authorization"] == "Bearer test-key"


def test_the_question_is_the_user_message(answerer, monkeypatch):
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("How tall is Mount Apo", "en")

    messages = sent["json"]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[1] == {"role": "user", "content": "How tall is Mount Apo"}


def test_the_target_language_reaches_the_system_prompt(answerer, monkeypatch):
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))

    answerer.answer("q", "tl")
    assert "Tagalog" in sent["json"]["messages"][0]["content"]

    answerer.answer("q", "en")
    assert "English" in sent["json"]["messages"][0]["content"]


def test_an_unknown_language_falls_back_to_english(answerer, monkeypatch):
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("q", "de")
    assert "English" in sent["json"]["messages"][0]["content"]


def test_the_system_prompt_forbids_markdown(answerer, monkeypatch):
    """The answer goes straight to Piper — asterisks and bullets would be
    read aloud as literal characters."""
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("q", "en")

    prompt = sent["json"]["messages"][0]["content"].lower()
    assert "markdown" in prompt
    assert "spoken aloud" in prompt or "speech" in prompt


def test_output_length_is_capped(monkeypatch):
    """The largest single lever on latency: generation time scales with
    output length."""
    answerer = MistralAnswerer(api_key="k", model="m", max_tokens=64)
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("q", "en")
    assert sent["json"]["max_tokens"] == 64


def test_the_timeout_is_passed_through(monkeypatch):
    answerer = MistralAnswerer(api_key="k", model="m", timeout_s=7.5)
    sent = _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("q", "en")
    assert sent["timeout"] == 7.5


def test_the_connection_is_reused_across_calls(answerer, monkeypatch):
    """A cold TLS handshake is ~3 round trips — 0.75 s at EU distance from
    the Philippines. One session per instance pays that once."""
    _capture(monkeypatch, response=_response(payload=_ok_payload()))
    answerer.answer("first", "en")
    first_session = answerer._get_session()
    answerer.answer("second", "en")
    assert answerer._get_session() is first_session


# --- failure paths -----------------------------------------------------------

def test_a_network_error_becomes_an_error_answer(answerer, monkeypatch):
    _capture(monkeypatch, raises=requests.ConnectionError("boom"))

    result = answerer.answer("q", "en")
    assert result.reason == "error"
    assert result.text is None


def test_a_timeout_becomes_an_error_answer(answerer, monkeypatch):
    _capture(monkeypatch, raises=requests.Timeout("slow"))
    assert answerer.answer("q", "en").reason == "error"


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
def test_http_errors_become_error_answers(answerer, monkeypatch, status):
    """401 is a bad key, 429 is rate limiting, 5xx is their problem — none
    of them should raise into the voice thread."""
    _capture(monkeypatch, response=_response(status_code=status, payload={"error": "x"}))
    assert answerer.answer("q", "en").reason == "error"


def test_a_non_json_body_becomes_an_error_answer(answerer, monkeypatch):
    """A proxy or captive portal returning an HTML error page."""
    _capture(monkeypatch, response=_response(body="<html>gateway timeout</html>"))
    assert answerer.answer("q", "en").reason == "error"


@pytest.mark.parametrize("payload", [
    {},                                     # no choices
    {"choices": []},                        # empty choices
    {"choices": [{}]},                      # no message
    {"choices": [{"message": {}}]},         # no content
    {"choices": "not-a-list"},              # wrong type
])
def test_malformed_shapes_become_error_answers(answerer, monkeypatch, payload):
    _capture(monkeypatch, response=_response(payload=payload))
    assert answerer.answer("q", "en").reason == "error"


@pytest.mark.parametrize("text", ["", "   ", None, 42])
def test_empty_or_non_string_content_becomes_an_error(answerer, monkeypatch, text):
    """A model that returns nothing while reporting success must not leave
    the wearable silent."""
    _capture(monkeypatch, response=_response(
        payload={"choices": [{"message": {"content": text}}]},
    ))
    assert answerer.answer("q", "en").reason == "error"


def test_surrounding_whitespace_is_stripped(answerer, monkeypatch):
    _capture(monkeypatch, response=_response(payload=_ok_payload("\n  Manila.  \n")))
    assert answerer.answer("q", "en").text == "Manila."


# --- composition with the guard ----------------------------------------------

def test_the_guard_prevents_a_call_when_offline(answerer, monkeypatch):
    """Offline is decided before the provider is touched, so the voice
    pipeline can skip the thinking cue and answer immediately."""
    def _refuse_head(url, **kwargs):
        raise requests.ConnectionError("offline")

    def _unexpected_post(self, *args, **kwargs):
        raise AssertionError("provider must not be called while offline")

    monkeypatch.setattr(requests, "head", _refuse_head)
    monkeypatch.setattr(requests.Session, "post", _unexpected_post)

    guard = OfflineGuard(answerer, probe_url="http://probe.test")
    assert guard.answer("q", "en").reason == "offline"


def test_the_guard_closes_the_provider_session(answerer):
    """Shutdown releases the socket rather than logging an AttributeError."""
    answerer._get_session()
    OfflineGuard(answerer, probe_url="http://probe.test").close()
    assert answerer._session is None


def test_the_guard_tolerates_a_provider_without_close():
    class _Bare:
        def answer(self, question, language):
            raise AssertionError("not called")

    OfflineGuard(_Bare(), probe_url="http://probe.test").close()
