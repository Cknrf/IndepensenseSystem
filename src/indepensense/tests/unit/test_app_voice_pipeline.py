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
from indepensense.feedback.mock import MockButton
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
    # `_on_ptt_press` sets this before spawning the voice thread. The
    # pipeline is called directly here, so the fixture stands in for it.
    app._voice_active.set()
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


# --- the button is reclaimed before the long wait ----------------------------
#
# `record_until_button` replaces the PTT handler with its own "stop
# recording" closure, and that closure is dead the moment it returns.
# Restoring only in the pipeline's `finally` left the button pointing at
# it for the whole 3-7 s of transcription and classification — the one
# press in the system that produced no sound, no log and no effect at
# all, during the exact wait that makes a user press something.

def test_the_button_is_reclaimed_as_soon_as_recording_ends(monkeypatch, tmp_path):
    """Asserted at the moment STT runs, not at the end — the end is when
    the `finally` would have fixed it anyway."""
    app = MockApp()
    app.ptt_button = MockButton()
    app.ptt_button.on("pressed", lambda: None)      # the recorder's closure
    # `_on_ptt_press` sets this before spawning the thread; calling the
    # pipeline directly has to stand in for that, or a press lands in a
    # state the real device never reaches.
    app._voice_active.set()
    handler_during_stt = []

    class _WatchingSTT(_StubSTT):
        def transcribe(self, audio_path, language="en", initial_prompt=None):
            handler_during_stt.append(app.ptt_button._handlers.get("pressed"))
            return super().transcribe(audio_path, language, initial_prompt)

    app.stt = _WatchingSTT("navigate to the cafeteria")
    monkeypatch.setattr(app_module, "record_until_button", lambda *a, **k: 3.0)
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(app, "_play_press_feedback", lambda rising_chime: None)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)

    app._voice_pipeline()

    assert handler_during_stt == [app._on_ptt_press]


def test_a_press_while_thinking_reaches_the_busy_cue(monkeypatch, tmp_path):
    """The user-visible point of the reclaim: the press now lands on a
    live handler and is answered, instead of vanishing."""
    app = MockApp()
    app.ptt_button = MockButton()
    app.ptt_button.on("pressed", lambda: None)
    app._voice_active.set()
    cues: list[str] = []
    monkeypatch.setattr(app_module, "play_busy_cue", lambda: cues.append("busy"))

    class _PressingSTT(_StubSTT):
        def transcribe(self, audio_path, language="en", initial_prompt=None):
            app.ptt_button.press()       # impatient user, mid-transcription
            return super().transcribe(audio_path, language, initial_prompt)

    app.stt = _PressingSTT("navigate to the cafeteria")
    monkeypatch.setattr(app_module, "record_until_button", lambda *a, **k: 3.0)
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(app, "_play_press_feedback", lambda rising_chime: None)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)

    app._voice_pipeline()

    assert cues == ["busy"]


def test_a_press_while_thinking_does_not_start_a_second_recording(
    monkeypatch, tmp_path,
):
    """Reclaiming the button must not also make it usable — one voice
    thread at a time, or two recordings fight for the microphone."""
    app = MockApp()
    app.ptt_button = MockButton()
    app._voice_active.set()
    recordings = []

    class _PressingSTT(_StubSTT):
        def transcribe(self, audio_path, language="en", initial_prompt=None):
            app.ptt_button.press()
            return super().transcribe(audio_path, language, initial_prompt)

    app.stt = _PressingSTT("navigate to the cafeteria")

    def _record(*_a, **_k):
        recordings.append(1)
        return 3.0

    monkeypatch.setattr(app_module, "record_until_button", _record)
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(app_module, "play_busy_cue", lambda: None)
    monkeypatch.setattr(app, "_play_press_feedback", lambda rising_chime: None)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)

    app._voice_pipeline()

    assert recordings == [1]


def test_the_button_is_reclaimed_even_when_the_pipeline_fails_early(
    monkeypatch, tmp_path,
):
    """The `finally` backstop still earns its place: a path that never
    reaches the recorder has not reclaimed anything."""
    app = MockApp()
    app.ptt_button = MockButton()
    app.ptt_button.on("pressed", lambda: None)
    app._voice_active.set()

    def _explode(*_a, **_k):
        raise OSError("microphone gone")

    monkeypatch.setattr(app_module, "record_until_button", _explode)
    monkeypatch.setattr(app, "_speak_error", lambda message: None)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)

    app._voice_pipeline()

    assert app.ptt_button._handlers["pressed"] == app._on_ptt_press
