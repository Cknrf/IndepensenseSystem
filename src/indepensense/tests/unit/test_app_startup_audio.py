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
    before = app._prerendered_path("startup", "en")

    monkeypatch.setitem(
        messages.MESSAGES["system.starting"], "en", "Completely different wording.",
    )
    after = app._prerendered_path("startup", "en")

    assert before != after


def test_each_language_gets_its_own_clip(app):
    assert app._prerendered_path("startup", "en") != app._prerendered_path("startup", "tl")


# --- rendering ----------------------------------------------------------------

def test_every_supported_language_is_rendered(app):
    """Not just the active one: the user can switch language by voice, and
    the next boot must greet them in their choice — at which point TTS is
    again unavailable."""
    app._render_prerendered()

    for language in app.language.supported:
        assert app._prerendered_path("startup", language).exists(), language


def test_rendering_again_does_not_resynthesise(app):
    app._render_prerendered()
    path = app._prerendered_path("startup", "en")
    stamp = path.stat().st_mtime_ns

    app._render_prerendered()

    assert path.stat().st_mtime_ns == stamp, "re-rendered an unchanged clip"


def test_a_changed_message_replaces_the_stale_clip(app, monkeypatch):
    """One file per language, not a growing pile of recordings of sentences
    nobody says any more — this runs on an SD card."""
    app._render_prerendered()
    stale = app._prerendered_path("startup", "en")

    monkeypatch.setitem(
        messages.MESSAGES["system.starting"], "en", "A newly worded greeting.",
    )
    app._render_prerendered()

    assert app._prerendered_path("startup", "en").exists()
    assert not stale.exists(), "old clip survived the message change"
    assert len(list(stale.parent.glob("startup_en_*.wav"))) == 1


def test_a_broken_tts_does_not_stop_the_wearable_booting(app):
    """Best-effort: the clip is a courtesy, the device coming up is not."""
    class _BrokenTTS:
        def synthesize(self, *args, **kwargs):
            raise RuntimeError("voice model missing")

    app.tts = _BrokenTTS()
    app._render_prerendered()        # must not raise


# --- playback -----------------------------------------------------------------

def test_playing_is_skipped_when_no_clip_exists_yet(app, monkeypatch):
    """First boot after installation. Silence here is expected, not a crash —
    `_render_prerendered` fixes it for every boot afterwards."""
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))

    app._play_startup_notice()

    assert played == []


def test_the_clip_is_played_when_present(app, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._render_prerendered()

    app._play_startup_notice()

    assert played == [app._prerendered_path("startup", app.language.current)]


def test_a_playback_failure_does_not_stop_the_wearable_booting(app, monkeypatch):
    def _boom(path):
        raise OSError("no audio device")

    monkeypatch.setattr(app_module, "play", _boom)
    app._render_prerendered()

    app._play_startup_notice()          # must not raise


# --- the thinking clip -------------------------------------------------------
#
# Same mechanism as the startup clip, different reason. TTS exists by the
# time this plays, but the sentence sits in front of the slowest path the
# device has: synthesising it on every cloud question added ~1 s to the
# exact wait it exists to excuse.

def test_the_thinking_clip_is_rendered_for_every_language(app):
    app._render_prerendered()

    for language in app.language.supported:
        assert app._prerendered_path("thinking", language).exists(), language


def test_startup_and_thinking_clips_do_not_collide(app):
    """Both hash their own message into the filename; the name prefix is
    what keeps two different sentences from sharing a path."""
    assert (app._prerendered_path("startup", "en")
            != app._prerendered_path("thinking", "en"))


def test_speaking_thinking_plays_the_rendered_clip(app, monkeypatch):
    """The point of the change: no synthesis on the critical path."""
    played = []
    synthesised = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._render_prerendered()
    monkeypatch.setattr(app.tts, "synthesize",
                        lambda *a, **k: synthesised.append(a))

    app._speak_thinking()

    assert played == [app._prerendered_path("thinking", app.language.current)]
    assert synthesised == [], "synthesised a clip that was already rendered"


def test_speaking_thinking_falls_back_when_the_clip_is_missing(app, monkeypatch):
    """First boot after the message text changes. Better a slow sentence
    than a silent one in front of the longest wait on the device."""
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))

    app._speak_thinking()      # nothing rendered yet

    assert played, "said nothing at all"


# --- every pre-rendered clip ------------------------------------------------

def test_every_prerendered_clip_is_rendered_for_every_language(app):
    """Derived from the table rather than listed, so adding an entry to
    `_PRERENDERED` without a translation fails here rather than at the
    moment the device needs to speak it."""
    app._render_prerendered()

    for name in app_module._PRERENDERED:
        for language in app.language.supported:
            assert app._prerendered_path(name, language).exists(), (name, language)


def test_every_prerendered_clip_has_its_own_path(app):
    """Two clips sharing a filename would have one silently overwrite the
    other — and the hash only distinguishes different *text*, not
    different purposes."""
    paths = [
        app._prerendered_path(name, language)
        for name in app_module._PRERENDERED
        for language in app.language.supported
    ]
    assert len(set(paths)) == len(paths)


def test_speaking_an_unheard_notice_plays_the_rendered_clip(app, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._render_prerendered()

    app._speak_prerendered("not_heard")

    assert played == [app._prerendered_path("not_heard", app.language.current)]


def test_a_broken_speaker_does_not_break_the_pipeline(app, monkeypatch):
    """Every caller is covering a silence. A failure here must not turn
    that into an exception on the voice thread."""
    def _explode(_path):
        raise OSError("output device disappeared")

    monkeypatch.setattr(app_module, "play", _explode)
    app._render_prerendered()

    app._speak_prerendered("not_heard")      # must not raise
