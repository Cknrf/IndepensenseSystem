"""Unit tests for the Mistral cloud intent parser.

No network: `requests.Session.post` is monkeypatched throughout.

Two groups carry most of the weight. The first pins the **request
shape**, because it is the cache contract and the statelessness
guarantee at once — two messages, system first and byte-identical,
transcript last — and both are the kind of invariant a well-meaning
edit erases without any test noticing. The second pins the **failure
mapping**: everything that goes wrong must become
`failure="transport"`, never an exception and never a bare `UNKNOWN`.
That distinction is what stops a timed-out request from reaching
`cloud.py` dressed as a genuine decline, and it is what tells
`FallbackIntentParser` to try the local model.
"""
import json

import pytest
import requests

from indepensense.intents.base import Intent
from indepensense.intents.mistral import MistralIntentParser

# Contains a `{brace}` on purpose. If anyone ever reaches for
# `.format()` on the system prompt — the obvious way to add a language
# or a timestamp — this prompt makes it fail loudly instead of silently
# splitting the server-side cache into one variant per substitution.
PROMPT_TEXT = 'Classify the utterance. Return {"intent": "...", "parameters": {}}.'


@pytest.fixture
def prompt_path(tmp_path):
    path = tmp_path / "nlu_system.md"
    path.write_text(PROMPT_TEXT)
    return path


@pytest.fixture
def parser(prompt_path):
    return MistralIntentParser(
        api_key="test-key", model="mistral-small-2603", prompt_path=prompt_path,
    )


def _response(status_code=200, payload=None):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps(payload or {}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _content(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


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

def test_an_empty_api_key_is_rejected_at_construction(prompt_path):
    """Fail at startup rather than on the first thing a user says."""
    with pytest.raises(ValueError):
        MistralIntentParser(
            api_key="", model="mistral-small-2603", prompt_path=prompt_path,
        )


# --- request shape: statelessness and the cache prefix -----------------------

def test_exactly_two_messages_are_sent_with_no_conversation_history(
    parser, monkeypatch,
):
    """Classification is independent per utterance.

    History would let a previous "take me to Jollibee" colour the next
    "stop", and could let context contaminate an emergency phrasing.
    Unlike `MistralAnswerer`, which replays one turn on purpose, this
    parser replays nothing — and the enforcement is the request body,
    not an instruction in the prompt.
    """
    sent = _capture(monkeypatch, _response(payload=_content('{"intent": "system.time"}')))

    parser.parse("what time is it")

    messages = sent["json"]["messages"]
    assert len(messages) == 2
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[1]["content"] == "what time is it"


def test_the_system_prompt_is_sent_byte_identical_to_the_file(parser, monkeypatch):
    """The server-side prompt cache keys on a stable prefix.

    Measured at 2,560 of 2,591 tokens cached. Any mutation here — a
    `.format()`, an interpolated language, a prepended timestamp —
    silently costs that on every utterance.
    """
    sent = _capture(monkeypatch, _response(payload=_content('{"intent": "system.time"}')))

    parser.parse("what time is it")

    assert sent["json"]["messages"][0]["content"] == PROMPT_TEXT


def test_successive_calls_send_an_identical_prefix(parser, monkeypatch):
    """The prefix must not drift between utterances, or the cache misses
    on every call while still appearing to work."""
    prefixes = []

    def _post(self, url, json=None, headers=None, timeout=None):
        prefixes.append(json["messages"][0]["content"])
        return _response(payload=_content('{"intent": "system.time"}'))

    monkeypatch.setattr(requests.Session, "post", _post)

    parser.parse("what time is it")
    parser.parse("dalhin mo ako sa Jollibee")

    assert prefixes[0] == prefixes[1] == PROMPT_TEXT


def test_the_request_pins_deterministic_json_output(parser, monkeypatch):
    """Temperature zero and JSON mode. A classifier must return the same
    label for the same words — the thesis quotes these numbers."""
    sent = _capture(monkeypatch, _response(payload=_content('{"intent": "system.time"}')))

    parser.parse("what time is it")

    assert sent["json"]["temperature"] == 0.0
    assert sent["json"]["response_format"] == {"type": "json_object"}


def test_the_configured_timeout_is_applied_to_the_request(prompt_path, monkeypatch):
    """The deadline is the whole fallback mechanism — if it were not
    passed through, a hung request would block the voice thread instead
    of handing over to the local model."""
    parser = MistralIntentParser(
        api_key="k", model="m", prompt_path=prompt_path, timeout_s=2.5,
    )
    sent = _capture(monkeypatch, _response(payload=_content('{"intent": "system.time"}')))

    parser.parse("what time is it")

    assert sent["timeout"] == 2.5


# --- success -----------------------------------------------------------------

def test_a_good_response_is_normalised_and_attributed_to_the_cloud(
    parser, monkeypatch,
):
    """`source` is what makes a wrong action in the journal attributable
    now that three engines can produce one."""
    _capture(monkeypatch, _response(payload=_content(
        '{"intent": "navigation.start", "parameters": {"location": "Jollibee"}}'
    )))

    result = parser.parse("dalhin mo ako sa Jollibee")

    assert result.intent is Intent.NAVIGATION_START
    assert result.parameters["location"] == "Jollibee"
    assert result.failure is None
    assert result.source == "cloud"
    assert result.raw_transcript == "dalhin mo ako sa Jollibee"


def test_normalisation_is_shared_with_the_local_parser(parser, monkeypatch):
    """`navigation.start` must always carry a boolean `nearest`.

    Delegating to `parse_llm_response` rather than reimplementing is what
    guarantees the executor sees one contract regardless of which engine
    answered.
    """
    _capture(monkeypatch, _response(payload=_content(
        '{"intent": "navigation.start", "parameters": {"location": "SM Lipa"}}'
    )))

    result = parser.parse("take me to SM Lipa")

    assert result.parameters["nearest"] is False


def test_a_genuine_decline_is_not_a_failure(parser, monkeypatch):
    """`unknown` with no failure is the cloud answerer's trigger.

    If this came back with a `failure` set, `cloud.py` would stop
    forwarding real questions — and `FallbackIntentParser` would burn a
    local inference re-answering something already answered correctly.
    """
    _capture(monkeypatch, _response(payload=_content('{"intent": "unknown"}')))

    result = parser.parse("how tall is Mount Apo")

    assert result.intent is Intent.UNKNOWN
    assert result.failure is None


# --- failure mapping ---------------------------------------------------------

@pytest.mark.parametrize("exc", [
    requests.ConnectionError("no route to host"),
    requests.Timeout("deadline exceeded"),
])
def test_network_failures_become_transport_and_never_raise(parser, monkeypatch, exc):
    """This runs on the voice thread, where a raise reaches the user as
    silence. A timeout is the expected case, not an exceptional one: the
    deadline exists to hand over to the local model."""
    _capture(monkeypatch, raises=exc)

    result = parser.parse("what time is it")

    assert result.failure == "transport"
    assert result.intent is Intent.UNKNOWN
    assert result.source == "cloud"


@pytest.mark.parametrize("status", [401, 429, 500, 503])
def test_error_statuses_become_transport(parser, monkeypatch, status):
    """A bad key, a rate limit and an outage are all "we hold no usable
    classification" — none of them may reach the cloud answerer as a
    decline."""
    _capture(monkeypatch, _response(status_code=status, payload={"error": "nope"}))

    result = parser.parse("what time is it")

    assert result.failure == "transport"


@pytest.mark.parametrize("payload", [
    {},
    {"choices": []},
    {"choices": [{"message": {}}]},
    {"choices": "not-a-list"},
])
def test_unexpected_response_shapes_become_transport(parser, monkeypatch, payload):
    """A `KeyError` escaping here would reach the user as silence."""
    _capture(monkeypatch, _response(payload=payload))

    result = parser.parse("what time is it")

    assert result.failure == "transport"


def test_a_non_json_reply_is_malformed_rather_than_transport(parser, monkeypatch):
    """The reply arrived and was readable — it just was not JSON. That is
    a different fault from the request failing, and `IntentResult`
    separates them so the journal can tell a misbehaving model from a
    broken link."""
    _capture(monkeypatch, _response(payload=_content("I think you want directions!")))

    result = parser.parse("what time is it")

    assert result.failure == "malformed"
    assert result.source == "cloud"


# --- warmup ------------------------------------------------------------------

def test_warmup_sends_the_same_prefix_real_queries_will_reuse(parser, monkeypatch):
    """A warmup that differed from the real request would warm nothing —
    the same trap `OllamaIntentParser.warm_up` avoids by building its
    request through `_payload`."""
    sent = _capture(monkeypatch, _response(payload=_content('{"intent": "unknown"}')))

    parser.warm_up(timeout_s=10.0)

    assert sent["json"]["messages"][0]["content"] == PROMPT_TEXT
    assert sent["timeout"] == 10.0


def test_a_failed_warmup_is_reported_not_raised(parser, monkeypatch):
    """Startup must survive a cold or absent link; the failure resurfaces
    on the next real query, where `parse` handles it."""
    _capture(monkeypatch, raises=requests.ConnectionError("down"))

    assert parser.warm_up(timeout_s=10.0) is False
