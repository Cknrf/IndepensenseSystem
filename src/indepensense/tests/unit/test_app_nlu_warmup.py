"""The LLM warmup runs after the safety features are up, not before them.

It used to run inline in `start()`: 56-87 s on the Pi for Qwen 3 1.7B,
before the main loop and before the buttons were opened. For that long at
every boot there was no fall detection, no obstacle warning and no
emergency button. These tests hold the warmup open and check that startup
finishes underneath it.
"""
import threading
import time

import pytest

from indepensense.app_mock import MockApp
from indepensense.intents.base import Intent, IntentResult


class _SlowWarmParser:
    """A parser whose warmup blocks until the test releases it."""

    def __init__(self, raises=False):
        self.release = threading.Event()
        self.warming = threading.Event()
        self.raises = raises

    def warm_up(self, timeout_s):
        self.warming.set()
        self.release.wait(timeout=5.0)
        if self.raises:
            raise RuntimeError("ollama is down")

    def parse(self, transcript):
        return IntentResult(intent=Intent.UNKNOWN, parameters={},
                            raw_transcript=transcript)


def _wait_for(condition, timeout_s=3.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def started(monkeypatch):
    def _start(parser):
        app = MockApp()
        greetings = []
        monkeypatch.setattr(app, "_open_parser", lambda: parser)
        monkeypatch.setattr(app, "_speak_greeting", lambda: greetings.append(True))
        monkeypatch.setattr(app, "_render_boot_clips", lambda: None)
        app.start()
        return app, greetings
    apps = []

    def factory(parser):
        app, greetings = _start(parser)
        apps.append((app, parser))
        return app, greetings

    yield factory
    for app, parser in apps:
        parser.release.set()
        app._shutdown.set()
        app.stop()


def test_startup_finishes_while_the_llm_is_still_warming(started):
    parser = _SlowWarmParser()

    app, greetings = started(parser)            # returns despite the held warmup

    assert parser.warming.is_set()
    assert app.emergency_button is not None, "the emergency button waited on the LLM"
    assert app.imu is not None
    assert greetings == [], "ready was announced before voice commands work"


def test_ready_is_announced_once_the_warmup_finishes(started):
    parser = _SlowWarmParser()
    app, greetings = started(parser)

    parser.release.set()

    assert _wait_for(lambda: greetings == [True])


def test_a_failed_warmup_still_announces_ready(started):
    """As before: a warmup failure degrades the first command, it does not
    leave the user waiting for a greeting that never comes."""
    parser = _SlowWarmParser(raises=True)
    app, greetings = started(parser)

    parser.release.set()

    assert _wait_for(lambda: greetings == [True])
