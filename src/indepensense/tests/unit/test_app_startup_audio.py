"""Unit tests for the pre-rendered startup announcement in `app.py`.

Startup takes 2-3 minutes, and until TTS finishes loading the wearable
cannot synthesise anything — so the "I am starting up" message has to be
replayed from a file rendered on a previous boot. To a user who cannot see
a terminal, the alternative is two silent minutes that are indistinguishable
from a device which failed to power on.

The interesting behaviour is not the playback, which is one `play()` call.
It is the cache invalidation: a recording that outlives the sentence it was
made from would have the wearable saying something no longer present
anywhere in the source, and nothing would ever flag it.
"""
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.intents import messages
from indepensense.voice.mock import MockTTS


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A MockApp whose startup clips land in a temp directory."""
    monkeypatch.setattr(app_module, "STARTUP_AUDIO_DIR", tmp_path)
    instance = MockApp()
    instance.tts = MockTTS()
    return instance


# --- cache invalidation -------------------------------------------------------

def test_the_filename_changes_when_the_message_changes(app, monkeypatch):
    """The whole point of hashing the text into the name. Without it, editing
    `system.starting` leaves the wearable speaking the old sentence forever."""
    before = app._startup_audio_path("en")

    monkeypatch.setitem(
        messages.MESSAGES["system.starting"], "en", "Completely different wording.",
    )
    after = app._startup_audio_path("en")

    assert before != after


def test_each_language_gets_its_own_clip(app):
    assert app._startup_audio_path("en") != app._startup_audio_path("tl")


# --- rendering ----------------------------------------------------------------

def test_every_supported_language_is_rendered(app):
    """Not just the active one: the user can switch language by voice, and
    the next boot must greet them in their choice — at which point TTS is
    again unavailable."""
    app._render_startup_notice()

    for language in app.language.supported:
        assert app._startup_audio_path(language).exists(), language


def test_rendering_again_does_not_resynthesise(app):
    app._render_startup_notice()
    path = app._startup_audio_path("en")
    stamp = path.stat().st_mtime_ns

    app._render_startup_notice()

    assert path.stat().st_mtime_ns == stamp, "re-rendered an unchanged clip"


def test_a_changed_message_replaces_the_stale_clip(app, monkeypatch):
    """One file per language, not a growing pile of recordings of sentences
    nobody says any more — this runs on an SD card."""
    app._render_startup_notice()
    stale = app._startup_audio_path("en")

    monkeypatch.setitem(
        messages.MESSAGES["system.starting"], "en", "A newly worded greeting.",
    )
    app._render_startup_notice()

    assert app._startup_audio_path("en").exists()
    assert not stale.exists(), "old clip survived the message change"
    assert len(list(stale.parent.glob("startup_en_*.wav"))) == 1


def test_a_broken_tts_does_not_stop_the_wearable_booting(app):
    """Best-effort: the clip is a courtesy, the device coming up is not."""
    class _BrokenTTS:
        def synthesize(self, *args, **kwargs):
            raise RuntimeError("voice model missing")

    app.tts = _BrokenTTS()
    app._render_startup_notice()        # must not raise


# --- playback -----------------------------------------------------------------

def test_playing_is_skipped_when_no_clip_exists_yet(app, monkeypatch):
    """First boot after installation. Silence here is expected, not a crash —
    `_render_startup_notice` fixes it for every boot afterwards."""
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))

    app._play_startup_notice()

    assert played == []


def test_the_clip_is_played_when_present(app, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._render_startup_notice()

    app._play_startup_notice()

    assert played == [app._startup_audio_path(app.language.current)]


def test_a_playback_failure_does_not_stop_the_wearable_booting(app, monkeypatch):
    def _boom(path):
        raise OSError("no audio device")

    monkeypatch.setattr(app_module, "play", _boom)
    app._render_startup_notice()

    app._play_startup_notice()          # must not raise
