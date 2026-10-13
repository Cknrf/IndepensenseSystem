"""The cloud answerer must only claim to be offline when it is.

`cloud.offline` speaks "I need an internet connection to answer that",
and a blind user acts on that by walking somewhere else to find signal.
It is the one message in the catalogue whose falseness costs the user a
journey, so the conditions that produce it are pinned here rather than
left to the breaker's internals.

The hazard is structural, not hypothetical: `CLOUD_LLM_PROBE_URL` and
`CLOUD_LLM_URL` are the same host, so the answerer shares a breaker with
the intent parser. Most of what opens it is a failed *classification* —
and under the current rules most of those are not connectivity failures
at all.
"""
import json

import pytest
import requests

from indepensense import net
from indepensense.config import (CLOUD_LLM_PROBE_URL, CLOUD_LLM_URL,
                                 NLU_CLOUD_PROMPT_PATH)
from indepensense.intents.base import CloudAnswer
from indepensense.intents.cloud import OfflineGuard
from indepensense.intents.mistral import MistralIntentParser


class Answerer:
    def __init__(self):
        self.calls = []

    def answer(self, question, language, previous=None):
        self.calls.append(question)
        return CloudAnswer(text="Mount Apo is 2,954 metres.", reason="ok")


def _http(status):
    response = requests.Response()
    response.status_code = status
    response._content = json.dumps({"error": "x"}).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _fail_parse_with(monkeypatch, post):
    """Put the shared breaker into whatever state a real failure leaves."""
    monkeypatch.setattr(requests.Session, "post", post)
    parser = MistralIntentParser(api_key="k", model="m",
                                 prompt_path=NLU_CLOUD_PROMPT_PATH,
                                 url=CLOUD_LLM_URL)
    parser.parse("dalhin mo ako sa Jollibee")


@pytest.fixture
def guard(monkeypatch):
    monkeypatch.setattr(net, "has_network_route", lambda: True)
    monkeypatch.setattr(requests, "head", lambda *a, **kw: None)
    return OfflineGuard(Answerer(), probe_url=CLOUD_LLM_PROBE_URL)


@pytest.mark.parametrize("label,post", [
    ("rate limited", lambda self, *a, **kw: _http(429)),
    ("bad api key", lambda self, *a, **kw: _http(401)),
])
def test_a_reachable_server_refusing_us_is_not_offline(guard, monkeypatch, label, post):
    """429 and 401 mean the link is fine and the provider is not. Saying
    "I need an internet connection" would send the user to find signal
    they already have."""
    _fail_parse_with(monkeypatch, post)

    assert guard.answer("how tall is Mount Apo", "en").reason == "error"


def test_a_slow_classification_is_not_offline(guard, monkeypatch):
    """A read timeout means the provider answered too slowly for the
    parser's 2.5 s budget. The link carried the request fine."""
    def _timeout(self, *a, **kw):
        raise requests.ReadTimeout("past the read budget")

    _fail_parse_with(monkeypatch, _timeout)

    assert guard.answer("how tall is Mount Apo", "en").reason == "error"


def test_an_unreachable_provider_is_offline(guard, monkeypatch):
    """The one case where the sentence is true, and must still be said."""
    def _refused(self, *a, **kw):
        raise requests.ConnectionError("no route to host")

    _fail_parse_with(monkeypatch, _refused)

    assert guard.answer("how tall is Mount Apo", "en").reason == "offline"


def test_no_route_is_offline(monkeypatch):
    """Nothing has failed yet, but there is demonstrably no way out."""
    monkeypatch.setattr(net, "has_network_route", lambda: False)
    inner = Answerer()

    result = OfflineGuard(inner, probe_url=CLOUD_LLM_PROBE_URL).answer("q", "en")

    assert result.reason == "offline"
    assert inner.calls == []


def test_a_server_error_does_not_stop_the_answerer_at_all(guard, monkeypatch):
    """5xx never opens the breaker, so the question still goes out — the
    next request may well land on a healthy worker."""
    _fail_parse_with(monkeypatch, lambda self, *a, **kw: _http(500))

    assert guard.answer("how tall is Mount Apo", "en").reason == "ok"


def test_every_reason_the_breaker_can_hold_maps_to_a_sentence():
    """A new reason added without a mapping would fall to the `error`
    branch silently. This fails instead, so the choice is deliberate."""
    spoken = {
        net.UNREACHABLE: "offline",
        net.SLOW: "error",
        net.BACKOFF: "error",
        net.REJECTED: "error",
    }

    assert set(spoken) == set(net.BREAKER_REASONS), (
        f"unmapped breaker reasons: {set(net.BREAKER_REASONS) - set(spoken)}"
    )
