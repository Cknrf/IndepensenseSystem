"""Unit tests for the request `OllamaIntentParser` actually sends.

Separate from `test_parser.py`, which covers `parse_llm_response` — a pure
function needing no server. These cover the other half: the payload, and
what happens when the server does not answer.

`requests` is monkeypatched throughout. Nothing here touches the network,
and construction passes `warmup=False` so no test depends on an Ollama
being up.
"""
import json
import sys
import types

import pytest

from indepensense.config import NLU_PROMPT_PATH
from indepensense.intents.base import Intent
from indepensense.intents.parser import _MAX_OUTPUT_TOKENS, OllamaIntentParser


class _FakeRequestException(Exception):
    pass


def _fake_requests(monkeypatch, *, raises=None, response_json=None):
    """Stub the `requests` module and capture the outgoing payload.

    `parser.py` imports `requests` lazily inside each method, so replacing
    the entry in `sys.modules` is enough — no import-time coupling to work
    around.
    """
    sent: dict = {}

    class _Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"response": json.dumps(response_json or {})}

    module = types.ModuleType("requests")
    module.RequestException = _FakeRequestException

    def _post(url, json=None, timeout=None):
        sent["url"] = url
        sent["json"] = json
        sent["timeout"] = timeout
        if raises is not None:
            raise raises
        return _Response()

    module.post = _post
    monkeypatch.setitem(sys.modules, "requests", module)
    return sent


@pytest.fixture
def parser():
    return OllamaIntentParser(
        model="qwen3:1.7b",
        ollama_url="http://127.0.0.1:11434",
        prompt_path=NLU_PROMPT_PATH,
        warmup=False,
    )


# --- the payload --------------------------------------------------------------

def test_generation_is_capped(parser, monkeypatch):
    """Uncapped, a model that never emits a stop token generates until the
    context window fills — which on a Pi outlasts the query timeout, so the
    user waits the full 30 s only to be told "I didn't understand"."""
    sent = _fake_requests(monkeypatch, response_json={"intent": "system.time"})

    parser.parse("what time is it")

    assert sent["json"]["options"]["num_predict"] == _MAX_OUTPUT_TOKENS


def test_the_cap_leaves_room_for_the_largest_real_reply(monkeypatch):
    """A `navigation.start` with a long place name is the biggest JSON any
    intent produces. If the cap ever drops below it, replies truncate
    mid-object and every navigation command silently becomes unknown."""
    largest = json.dumps({
        "intent": "navigation.start",
        "parameters": {
            "destination": "Southwestern University PHINMA Urgello Campus",
            "nearest": False,
        },
    })
    # ~4 characters per token is the usual rule of thumb for this kind of
    # text; the assertion is deliberately loose because the exact
    # tokenisation is the model's business, not ours.
    assert len(largest) / 4 < _MAX_OUTPUT_TOKENS / 2


def test_the_model_is_pinned_and_thinking_stays_off(parser, monkeypatch):
    """Both are latency controls: an unpinned model costs a 25-40 s reload
    after five idle minutes, and Qwen 3's `<think>` block is pure generated
    text this parser would then have to strip."""
    sent = _fake_requests(monkeypatch, response_json={"intent": "system.time"})

    parser.parse("what time is it")

    assert sent["json"]["keep_alive"] == -1
    assert sent["json"]["think"] is False
    assert sent["json"]["format"] == "json"
    assert sent["json"]["stream"] is False


def test_the_system_prompt_is_sent_with_every_query(parser, monkeypatch):
    """Ollama's prefix cache makes this cheap after the first call, and
    sending it per-request is what keeps the parser stateless."""
    sent = _fake_requests(monkeypatch, response_json={"intent": "system.time"})

    parser.parse("what time is it")

    assert sent["json"]["system"] == NLU_PROMPT_PATH.read_text()
    assert sent["json"]["prompt"] == "what time is it"


# --- failure ------------------------------------------------------------------

def test_a_transport_failure_becomes_unknown(parser, monkeypatch):
    """The intent still degrades to `UNKNOWN` — every caller switches on
    `Intent`, and a failure is not a thing the user asked for. What tells
    the two apart is `failure`, asserted further down."""
    _fake_requests(monkeypatch, raises=_FakeRequestException("read timed out"))

    result = parser.parse("take me to the hospital")

    assert result.intent is Intent.UNKNOWN
    assert result.raw_transcript == "take me to the hospital"
    assert result.raw_llm_response == ""


def test_a_transport_failure_does_not_raise_on_the_voice_thread(parser, monkeypatch):
    """A raise here surfaces to the user as silence — the worst failure
    mode on a device whose only output channel is speech."""
    _fake_requests(monkeypatch, raises=_FakeRequestException("connection refused"))

    parser.parse("what time is it")     # must not raise


# --- failure is distinguishable from a decline --------------------------------

def test_a_transport_failure_is_marked_as_one(parser, monkeypatch):
    """`unknown` alone cannot carry this: the executor has to tell "the
    model declined" from "the model never answered" before deciding
    whether the cloud may see the transcript."""
    _fake_requests(monkeypatch, raises=_FakeRequestException("read timed out"))

    assert parser.parse("take me to the hospital").failure == "transport"


def test_malformed_json_is_marked_as_a_failure(parser, monkeypatch):
    """A reply arrived but we cannot read it, so we hold no classification
    and cannot know the utterance was not a command."""
    sent = _fake_requests(monkeypatch)

    def _post(url, json=None, timeout=None):
        sent["json"] = json

        class _Bad:
            def raise_for_status(self):
                pass

            def json(self):
                return {"response": "I think the user wants directions"}

        return _Bad()

    monkeypatch.setattr(sys.modules["requests"], "post", _post)

    assert parser.parse("take me to the hospital").failure == "malformed"


def test_a_good_reply_carries_no_failure(parser, monkeypatch):
    _fake_requests(monkeypatch, response_json={"intent": "system.time"})

    result = parser.parse("what time is it")
    assert result.intent is Intent.SYSTEM_TIME
    assert result.failure is None


def test_a_genuine_unknown_carries_no_failure(parser, monkeypatch):
    """The model ran and declined. This is the case the cloud exists for,
    so it must stay distinguishable from the two above."""
    _fake_requests(monkeypatch, response_json={"intent": "unknown"})

    result = parser.parse("how tall is Mount Apo")
    assert result.intent is Intent.UNKNOWN
    assert result.failure is None
