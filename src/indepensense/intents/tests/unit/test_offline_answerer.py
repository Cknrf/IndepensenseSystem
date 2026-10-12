"""The path a declined utterance takes when the cloud is unreachable.

This is the chain the breaker nearly missed. When the cloud parser is on
cooldown the local model answers instead, and a local `unknown` is a
genuine decline — which is the *cloud answerer's* trigger. So an offline
device walks straight back out to the network on the one path neither
the parser's breaker nor its route check was guarding.

The outcome was always correct: `OfflineGuard` reports offline and the
user is told there is no internet. What was wrong is how long it took to
say so, because `probe_reachable` paid a full DNS stall first.
"""
import pytest
import requests

from indepensense import net
from indepensense.intents.cloud import OfflineGuard

PROBE = "https://api.mistral.ai/v1/chat/completions"


class FakeAnswerer:
    def __init__(self):
        self.calls = []

    def answer(self, question, language, previous=None):
        self.calls.append(question)
        from indepensense.intents.base import CloudAnswer
        return CloudAnswer(text="an answer", reason="ok")


@pytest.fixture
def no_route(monkeypatch):
    monkeypatch.setattr(net, "has_network_route", lambda: False)


def test_with_no_route_the_question_is_never_sent(no_route):
    """And, critically, no DNS lookup is attempted — that was the stall."""
    inner = FakeAnswerer()
    guard = OfflineGuard(inner, probe_url=PROBE)

    result = guard.answer("how tall is Mount Apo", "en")

    assert result.reason == "offline"
    assert result.text is None
    assert inner.calls == [], "nothing should reach the provider"


def test_with_no_route_the_probe_itself_makes_no_request(no_route, monkeypatch):
    def _explode(*a, **kw):
        raise AssertionError("probe_reachable tried the network with no route")

    monkeypatch.setattr(requests, "head", _explode)

    assert net.probe_reachable(PROBE) is False


def test_a_failed_probe_puts_the_host_on_cooldown(monkeypatch):
    """So the next declined utterance answers instantly instead of
    repeating the wait."""
    calls = []

    def _head(url, timeout=None):
        calls.append(url)
        raise requests.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "head", _head)

    assert net.probe_reachable(PROBE) is False
    assert net.probe_reachable(PROBE) is False
    assert net.probe_reachable(PROBE) is False

    assert len(calls) == 1, "only the first probe should touch the network"


def test_the_parser_and_the_answerer_share_one_cooldown():
    """They are the same host. A failed classification already proves the
    provider is unreachable, so the answerer should not re-discover it."""
    from indepensense.config import CLOUD_LLM_PROBE_URL, CLOUD_LLM_URL

    assert net.breaker_for(CLOUD_LLM_URL) is net.breaker_for(CLOUD_LLM_PROBE_URL)


def test_the_guard_still_answers_when_the_link_is_up(monkeypatch):
    """The protections must not strand a working device."""
    monkeypatch.setattr(net, "has_network_route", lambda: True)
    monkeypatch.setattr(requests, "head", lambda url, timeout=None: None)
    inner = FakeAnswerer()

    result = OfflineGuard(inner, probe_url=PROBE).answer("question", "en")

    assert result.reason == "ok"
    assert inner.calls == ["question"]
