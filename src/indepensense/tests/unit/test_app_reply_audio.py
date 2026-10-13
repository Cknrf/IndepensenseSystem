"""Unit tests for how the voice pipeline's spoken reply is produced.

The reply used to go straight to `self.tts.synthesize(...)`. That is the
one speaking path in the system that bypassed `voice/clips.py`, and it
cost two things that are only visible from outside the call:

  - **No local fallback.** `self.tts` routes Tagalog to `RemoteTTS` when
    `REMOTE_TTS_ENABLED` is set, and a `TTSEngine` has no fallback inside
    it by design — the fallback lives in `clips.render_first`, where the
    filename is chosen, because a locally-rendered clip must be filed
    under the local voice. So every Tagalog reply died with the endpoint
    and reached the user as "something went wrong".
  - **No cache.** Each reply was a fresh synthesis, while the *same*
    sentence replayed through the repeat button hit the clip store,
    because that path goes through the announcer.

Both are asserted through `_voice_pipeline` rather than on
`_clip_for_text` alone, because the defect was never in the helper — it
was in which helper the pipeline called.
"""
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.intents.base import Intent, IntentResult
from indepensense.voice.base import Transcript, TranscriptSegment


class _STT:
    def __init__(self, text="take me home"):
        self.text = text

    def transcribe(self, path, language="en", initial_prompt=None):
        return Transcript(
            text=self.text, language=language,
            segments=[TranscriptSegment(text=self.text, start_s=0, end_s=1)],
        )


class _Parser:
    def parse(self, text):
        return IntentResult(intent=Intent.SYSTEM_TIME)


class _Executor:
    def __init__(self, response):
        self.response = response

    def execute(self, result):
        return self.response


class _Engine:
    """A `TTSEngine` that records its calls and writes a real file.

    Writing matters: the clip store renames the rendered file into place,
    so an engine that produces nothing is not a legal engine — it only
    ever passed because the old path never read the result back.
    """

    def __init__(self, name, fails=False):
        self.name = name
        self.fails = fails
        self.calls = []

    def synthesize(self, text, path, language=None):
        self.calls.append(text)
        if self.fails:
            raise RuntimeError(f"{self.name} unreachable")
        path.write_bytes(b"RIFF....WAVE")


@pytest.fixture
def app(monkeypatch, tmp_path):
    instance = MockApp()
    instance.cloud = None
    instance.stt = _STT()
    instance.parser = _Parser()
    instance._voice_active.set()
    instance.played = []

    monkeypatch.setattr(app_module, "record_until_button", lambda *a, **k: 3.0)
    monkeypatch.setattr(app_module, "play", instance.played.append)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)
    monkeypatch.setattr(instance, "_play_press_feedback",
                        lambda rising_chime: None)
    return instance


def _run(app, response):
    app.executor = _Executor(response)
    app._voice_cancel.clear()
    app._voice_pipeline()


# --- the local fallback ------------------------------------------------------
#
# Tagalog only: `config.REMOTE_TTS_VOICES` serves `tl` and not `en`, so
# `en` has a one-voice chain and no fallback to exercise. That asymmetry
# is the point — the bug was invisible in English.

def test_a_reply_falls_back_to_the_local_engine(app):
    """The whole fix. With the endpoint down this used to raise out of
    the pipeline and reach the user as a generic error, in the one
    language the device cannot speak without the network."""
    app.language.set("tl")
    app.tts = _Engine("remote", fails=True)
    app.tts_local = _Engine("local")

    _run(app, "Alas tres na po.")

    assert app.tts.calls == ["Alas tres na po."], "remote should be tried first"
    assert app.tts_local.calls == ["Alas tres na po."]
    assert len(app.played) == 1


def test_a_reply_with_no_engine_left_does_not_reach_the_user_as_silence(app):
    """Both engines gone is a real failure and must surface as one —
    `_clip_for_text` deliberately raises where `_play_clip` swallows, so
    the pipeline's own error handling answers."""
    app.language.set("tl")
    app.tts = _Engine("remote", fails=True)
    app.tts_local = _Engine("local", fails=True)
    cues = []
    app._play_clip = lambda key, **fields: cues.append(key)

    _run(app, "Alas tres na po.")

    assert app.played == []
    assert cues == ["voice.pipeline_error"]


def test_the_remote_engine_alone_is_enough_when_it_works(app):
    app.language.set("tl")
    app.tts = _Engine("remote")
    app.tts_local = _Engine("local")

    _run(app, "Alas tres na po.")

    assert app.tts_local.calls == [], "local should not be touched on success"
    assert len(app.played) == 1


# --- the clip store ----------------------------------------------------------

def test_the_same_reply_is_only_synthesised_once(app):
    """Replies repeat far more than they look like they do — every
    confirmation, every error, "there is nothing to repeat yet"."""
    app.tts = _Engine("piper")

    _run(app, "It is three o'clock.")
    _run(app, "It is three o'clock.")

    assert app.tts.calls == ["It is three o'clock."]
    assert len(app.played) == 2


def test_a_different_reply_is_synthesised_again(app):
    """Guards the obvious wrong fix for the test above — a cache keyed on
    something coarser than the sentence."""
    app.tts = _Engine("piper")

    _run(app, "It is three o'clock.")
    _run(app, "It is four o'clock.")

    assert len(app.tts.calls) == 2


def test_a_static_reply_is_filed_where_the_sweep_cannot_reach_it(app):
    """A reply that is a fixed catalogue message belongs in the permanent
    directory, the same as one spoken through the announcer. Filing it in
    the cache would make the never-evicted guarantee depend on which code
    path happened to say it first."""
    app.language.set("en")
    app.tts = _Engine("piper")
    static_text = app_module.messages.get("nav.none_active", "en")

    _run(app, static_text)

    assert list(app_module.MESSAGE_AUDIO_DIR.glob("*.wav"))
    assert not list(app_module.CLIP_CACHE_DIR.glob("*.wav"))


def test_a_templated_reply_is_filed_in_the_swept_cache(app):
    """The counterpart. Every place name and distance the device ever
    speaks would otherwise accumulate somewhere nothing reclaims."""
    app.language.set("en")
    app.tts = _Engine("piper")

    _run(app, "Navigating to the cafeteria. Total distance 90 meters.")

    assert list(app_module.CLIP_CACHE_DIR.glob("*.wav"))
    assert not list(app_module.MESSAGE_AUDIO_DIR.glob("*.wav"))


# --- what is no longer written ----------------------------------------------

def test_the_reply_is_no_longer_written_beside_the_recording(app, tmp_path):
    """`VOICE_TEST_DIR` had two WAVs per utterance and nothing pruning
    either. The reply now lives in the clip store under a hash, so it is
    deduplicated and — when templated — swept.

    Non-vacuous despite the stubbed recorder: the old path synthesised
    straight to `{timestamp}_response.wav`, and `_Engine` writes, so this
    directory did hold one. The recording itself is untouched here — that
    is a separate question about a file this test's recorder never
    creates."""
    app.tts = _Engine("piper")

    _run(app, "It is three o'clock.")

    assert list(tmp_path.glob("*_response.wav")) == []
