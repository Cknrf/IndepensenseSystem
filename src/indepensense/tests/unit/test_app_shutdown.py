"""The voice-commanded power-off fires only in the cycle that armed it.

`_request_shutdown` only sets a flag; `_voice_pipeline` powers off after
the goodbye has played. A cancel during the goodbye (stop, or the
emergency button) correctly skips the power-off — but the flag used to
outlive the cycle, so the next, unrelated command answered and then shut
the wearable down.
"""
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.intents.base import Intent, IntentResult
from indepensense.voice.base import Transcript, TranscriptSegment


class _STT:
    def __init__(self, text):
        self.text = text

    def transcribe(self, path, language="en", initial_prompt=None):
        return Transcript(
            text=self.text, language=language,
            segments=[TranscriptSegment(text=self.text, start_s=0, end_s=1)],
        )


class _Parser:
    def __init__(self, intent):
        self.intent = intent

    def parse(self, text):
        return IntentResult(intent=self.intent)


class _Executor:
    def __init__(self, response, on_execute=None):
        self.response = response
        self.on_execute = on_execute

    def execute(self, result):
        if self.on_execute:
            self.on_execute()
        return self.response


class _TTS:
    def __init__(self, on_synthesize=None):
        self.on_synthesize = on_synthesize

    def synthesize(self, text, path, language="en"):
        if self.on_synthesize:
            self.on_synthesize()


@pytest.fixture
def app(monkeypatch, tmp_path):
    instance = MockApp()
    instance.cloud = None
    monkeypatch.setattr(app_module, "record_until_button", lambda *a, **k: 3.0)
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)
    monkeypatch.setattr(instance, "_play_press_feedback",
                        lambda rising_chime: None)
    instance.powered_off = []
    monkeypatch.setattr(instance, "_perform_shutdown",
                        lambda: instance.powered_off.append(True))
    return instance


def _run_cycle(app, text, intent, executor, tts):
    app.stt, app.parser, app.executor, app.tts = (
        _STT(text), _Parser(intent), executor, tts,
    )
    app._voice_active.set()
    app._voice_cancel.clear()
    app._voice_pipeline()


def _cancel_as_emergency(app):
    app._voice_cancel_reason = "emergency"
    app._voice_cancel.set()


def test_a_confirmed_shutdown_powers_off_after_the_goodbye(app):
    _run_cycle(app, "turn off", Intent.SYSTEM_SHUTDOWN,
               _Executor("goodbye", on_execute=app._request_shutdown), _TTS())

    assert app.powered_off == [True]


def test_a_cancelled_shutdown_does_not_fire_on_the_next_command(app):
    _run_cycle(app, "turn off", Intent.SYSTEM_SHUTDOWN,
               _Executor("goodbye", on_execute=app._request_shutdown),
               _TTS(on_synthesize=lambda: _cancel_as_emergency(app)))
    assert app.powered_off == []

    _run_cycle(app, "what time is it", Intent.UNKNOWN,
               _Executor("It is three"), _TTS())

    assert app.powered_off == [], "an unrelated command powered the device off"
    assert app._shutdown_requested is False


def test_a_failed_goodbye_does_not_leave_the_shutdown_armed(app):
    def _broken_tts():
        raise RuntimeError("piper crashed")

    _run_cycle(app, "turn off", Intent.SYSTEM_SHUTDOWN,
               _Executor("goodbye", on_execute=app._request_shutdown),
               _TTS(on_synthesize=_broken_tts))

    assert app._shutdown_requested is False
