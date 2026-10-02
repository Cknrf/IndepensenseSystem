"""Unit tests for the silent exits from `_voice_pipeline`.

The pipeline has several paths that end a voice cycle with a bare
`return`. Each one leaves the user having pressed a button, heard a
chime, and then received nothing — which is indistinguishable from the
device having died mid-command. A field log shows one: a 2.2 s recording
transcribed to `''`, after which the wearable simply went quiet.

Drives the real `_voice_pipeline` with the module-level recorder and the
STT stubbed, rather than calling the helpers directly. The branch being
tested is *which exit the pipeline takes*, and asserting that from
outside is the only way the test fails if the branches are reordered.
"""
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.voice.base import Transcript, TranscriptSegment


class _StubSTT:
    """Returns a scripted transcript, accepting the kwargs the app passes."""

    def __init__(self, text: str):
        self.text = text
        self.calls = 0

    def transcribe(self, audio_path, language="en", initial_prompt=None):
        self.calls += 1
        return Transcript(
            text=self.text,
            language=language,
            segments=[TranscriptSegment(text=self.text, start_s=0.0, end_s=1.0)],
        )


@pytest.fixture
def pipeline(monkeypatch, tmp_path):
    """A MockApp whose pipeline can be run without audio hardware.

    Returns `(app, state)` where `state["spoken"]` lists the pre-rendered
    clips played and `state["duration"]` is what the recorder reports.
    """
    app = MockApp()
    app.stt = _StubSTT("navigate to the cafeteria")
    state = {"duration": 3.0, "spoken": [], "played": []}

    monkeypatch.setattr(app_module, "record_until_button",
                        lambda *a, **k: state["duration"])
    monkeypatch.setattr(app_module, "play", lambda path: state["played"].append(path))
    monkeypatch.setattr(app, "_play_press_feedback", lambda rising_chime: None)
    monkeypatch.setattr(app, "_speak_prerendered", lambda name: state["spoken"].append(name))
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)
    return app, state


# --- nothing was captured ----------------------------------------------------

def test_a_recording_too_short_to_hold_speech_says_so(pipeline):
    """A double-press, or a bounce. The user has had their press chime and
    would otherwise get nothing back at all."""
    app, state = pipeline
    state["duration"] = 0.1

    app._voice_pipeline()

    assert state["spoken"] == ["not_heard"]


def test_an_empty_transcript_says_so(pipeline):
    """The field case: 2.2 s of audio, `''` out of Whisper, then silence."""
    app, state = pipeline
    app.stt = _StubSTT("")

    app._voice_pipeline()

    assert state["spoken"] == ["not_heard"]


def test_a_whitespace_only_transcript_counts_as_empty(pipeline):
    app, state = pipeline
    app.stt = _StubSTT("   \n  ")

    app._voice_pipeline()

    assert state["spoken"] == ["not_heard"]


def test_nothing_heard_does_not_reach_the_parser(pipeline):
    """Classifying an empty string would spend seconds of LLM time to
    arrive at `unknown`, and `unknown` forwards to the cloud."""
    app, state = pipeline
    app.stt = _StubSTT("")
    parsed = []
    app.parser = type("P", (), {"parse": lambda self, t: parsed.append(t)})()

    app._voice_pipeline()

    assert parsed == []


# --- cancelled is not the same as unheard ------------------------------------

def test_a_cancelled_cycle_stays_quiet(pipeline):
    """The stop cue has already answered the press. Following it with "I
    didn't hear anything" would contradict a user who knows perfectly well
    why it stopped — they stopped it."""
    app, state = pipeline
    app.stt = _StubSTT("")
    app._voice_cancel.set()

    app._voice_pipeline()

    assert state["spoken"] == []


def test_a_cancelled_recording_stays_quiet(pipeline):
    """Same, one stage earlier — cancelled before the transcript exists."""
    app, state = pipeline
    app._voice_cancel.set()

    app._voice_pipeline()

    assert state["spoken"] == []


# --- the normal path is unaffected -------------------------------------------

def test_a_real_transcript_is_not_reported_as_unheard(pipeline):
    app, state = pipeline

    app._voice_pipeline()

    assert "not_heard" not in state["spoken"]


def test_the_voice_active_latch_is_always_released(pipeline):
    """Every exit runs the `finally`. A latch left set would make the next
    PTT press answer with the busy cue forever."""
    app, state = pipeline
    app._voice_active.set()
    state["duration"] = 0.1

    app._voice_pipeline()

    assert not app._voice_active.is_set()
