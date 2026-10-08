"""Unit tests for the boot-time NLU warmup tool.

Ollama is stubbed at the `requests` boundary. What matters is that the
tool waits for the model to be listed, sends the *parser's* request —
system prompt included — and reports the outcome through its exit code.
"""
import json

import pytest
import requests

from indepensense.tools import warm_nlu


class _Response:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self.ok = status < 400
        self._body = body or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(warm_nlu.time, "sleep", lambda s: None)


@pytest.fixture
def ollama(monkeypatch, tmp_path):
    """A fake Ollama: a scripted catalogue and a recorder for generate."""
    prompt = tmp_path / "nlu_system.md"
    prompt.write_text("You classify intents.")
    monkeypatch.setattr(warm_nlu, "NLU_PROMPT_PATH", prompt)
    monkeypatch.setattr(warm_nlu, "NLU_MODEL", "qwen3:1.7b")
    monkeypatch.setattr(warm_nlu, "OLLAMA_URL", "http://ollama.test")
    monkeypatch.setattr(warm_nlu, "NLU_COMPACT_PREFILL", False)

    state = {"tags": [], "posts": [], "post_status": 200}

    def get(url, timeout):
        assert url == "http://ollama.test/api/tags"
        if not state["tags"]:
            raise requests.ConnectionError("not up yet")
        return _Response(200, {"models": [{"name": n} for n in state["tags"].pop(0)]})

    def post(url, json=None, timeout=None):
        state["posts"].append((url, json))
        return _Response(state["post_status"])

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    return state


def test_it_waits_for_the_model_to_be_catalogued_then_warms_it(ollama):
    ollama["tags"] = [["other:1b"], ["other:1b"], ["other:1b", "qwen3:1.7b"]]

    assert warm_nlu.main(["--catalogue-timeout", "10"]) == 0

    assert len(ollama["posts"]) == 1


def test_the_request_is_the_parsers_own_with_the_system_prompt(ollama):
    ollama["tags"] = [["qwen3:1.7b"]]

    warm_nlu.main([])

    url, body = ollama["posts"][0]
    assert url == "http://ollama.test/api/generate"
    assert body["model"] == "qwen3:1.7b"
    assert body["system"] == "You classify intents."
    assert body["keep_alive"] == -1, "the model would be evicted after five minutes"


def test_a_model_nobody_pulled_fails_with_the_pull_command(ollama, monkeypatch, capsys):
    ollama["tags"] = [["other:1b"]] * 3
    monkeypatch.setattr(warm_nlu.time, "monotonic", _ticking(0.0, 1.0))

    assert warm_nlu.main(["--catalogue-timeout", "2"]) == 1

    assert "ollama pull qwen3:1.7b" in capsys.readouterr().err
    assert ollama["posts"] == []


def test_a_failed_generate_is_a_non_zero_exit(ollama):
    ollama["tags"] = [["qwen3:1.7b"]]
    ollama["post_status"] = 500

    assert warm_nlu.main([]) == 1


def test_ollama_answering_garbage_while_starting_is_not_fatal(ollama, monkeypatch):
    calls = {"n": 0}

    def get(url, timeout):
        calls["n"] += 1
        if calls["n"] == 1:
            response = _Response(200)
            response.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
            return response
        return _Response(200, {"models": [{"name": "qwen3:1.7b"}]})
    monkeypatch.setattr(requests, "get", get)

    assert warm_nlu.wait_for_model("http://ollama.test", "qwen3:1.7b", timeout_s=10, poll_s=0)


def _ticking(start, step):
    clock = {"now": start - step}

    def monotonic():
        clock["now"] += step
        return clock["now"]
    return monotonic
