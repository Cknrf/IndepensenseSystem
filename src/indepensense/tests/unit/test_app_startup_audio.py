"""Unit tests for the clips `app.py` plays rather than synthesises.

Two reasons, and the distinction is what these tests guard.

`system.starting` and `language.greeting` are rendered at the end of
every boot by `_render_boot_clips`, because they are spoken *before* TTS
is loaded — `_play_startup_notice` has no engine to fall back to, so a
missing clip there means silence, and to a user who cannot see a
terminal two silent minutes are indistinguishable from a device that
failed to power on.

Everything else goes through `_play_clip`, which looks the sentence up
and synthesises on the spot if it is missing. Those tests are about the
fallback working, not about the clip existing.

The underlying store — naming, lookup order, eviction — is tested in
`voice/tests/unit/test_clips.py`. What is tested here is the wiring.
"""
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.intents import messages
from indepensense.voice import clips
from indepensense.voice.mock import MockTTS


@pytest.fixture
def app(tmp_path, monkeypatch):
    """A MockApp whose clips land in temp directories."""
    monkeypatch.setattr(app_module, "MESSAGE_AUDIO_DIR", tmp_path / "messages")
    monkeypatch.setattr(app_module, "CLIP_CACHE_DIR", tmp_path / "cache")
    instance = MockApp()
    instance.tts = MockTTS()
    return instance


def _clip(app, key, language=None):
    """Where the clip for `key` would live, if it exists."""
    language = language or app.language.current
    return clips.find(
        messages.get(key, language), language,
        app_module.MESSAGE_AUDIO_DIR, app_module.CLIP_CACHE_DIR,
    )


# --- the boot clips ----------------------------------------------------------

def test_every_supported_language_is_rendered(app):
    """Not just the active one: the user can switch language by voice, and
    the next boot must greet them in their choice — at which point TTS is
    again unavailable."""
    app._render_boot_clips()

    for key in app_module._BOOT_CLIPS:
        for language in app.language.supported:
            assert _clip(app, key, language) is not None, (key, language)


def test_the_greeting_is_a_boot_clip(app):
    """It was not, and was re-synthesised on every single boot — the miss
    that prompted all of this."""
    assert "language.greeting" in app_module._BOOT_CLIPS


def test_rendering_again_does_not_resynthesise(app):
    app._render_boot_clips()
    path = _clip(app, "system.starting", "en")
    stamp = path.stat().st_mtime_ns

    app._render_boot_clips()

    assert path.stat().st_mtime_ns == stamp, "re-rendered an unchanged clip"


def test_a_changed_message_leaves_the_stale_clip_unused(app, monkeypatch):
    """The point of hashing the text into the name. The old file is still
    on disk until `render_messages` prunes it, but nothing will ever ask
    for it again — which is what stops the wearable speaking a sentence
    that is no longer anywhere in the source."""
    app._render_boot_clips()
    stale = _clip(app, "system.starting", "en")

    monkeypatch.setitem(
        messages.MESSAGES["system.starting"], "en", "A newly worded greeting.",
    )

    assert _clip(app, "system.starting", "en") is None
    app._render_boot_clips()
    fresh = _clip(app, "system.starting", "en")
    assert fresh is not None and fresh != stale


def test_a_broken_tts_does_not_stop_the_wearable_booting(app):
    """Best-effort: the clip is a courtesy, the device coming up is not."""
    class _BrokenTTS:
        def synthesize(self, *args, **kwargs):
            raise RuntimeError("voice model missing")

    app.tts = _BrokenTTS()
    app._render_boot_clips()        # must not raise


# --- the startup notice ------------------------------------------------------

def test_playing_is_skipped_when_no_clip_exists_yet(app, monkeypatch):
    """First boot after installation. Silence here is expected, not a crash —
    `_render_boot_clips` fixes it for every boot afterwards."""
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))

    app._play_startup_notice()

    assert played == []


def test_the_notice_never_falls_back_to_synthesis(app, monkeypatch):
    """The one caller that cannot: it runs before the TTS engine is
    loaded, so reaching for it would raise on the first line of
    `start()` rather than produce a sentence."""
    synthesised = []
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(app.tts, "synthesize", lambda *a, **k: synthesised.append(a))

    app._play_startup_notice()

    assert synthesised == []


def test_the_clip_is_played_when_present(app, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._render_boot_clips()

    app._play_startup_notice()

    assert played == [_clip(app, "system.starting")]


def test_the_notice_is_played_from_the_permanent_directory(app, monkeypatch):
    """Not the cache, which gets swept. A clip evicted between boots
    would mean a silent startup."""
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._render_boot_clips()

    app._play_startup_notice()

    assert played[0].parent == app_module.MESSAGE_AUDIO_DIR


def test_a_playback_failure_does_not_stop_the_wearable_booting(app, monkeypatch):
    def _boom(path):
        raise OSError("no audio device")

    monkeypatch.setattr(app_module, "play", _boom)
    app._render_boot_clips()

    app._play_startup_notice()          # must not raise


# --- _play_clip --------------------------------------------------------------
#
# The in-pipeline cues. TTS exists by the time these play, so a missing
# clip costs latency rather than silence — but the latency is the whole
# problem: `cloud.thinking` sits in front of the slowest path the device
# has, and synthesising it added ~1 s to the exact wait it exists to
# excuse.

def test_speaking_thinking_plays_the_rendered_clip(app, monkeypatch):
    """The point of the change: no synthesis on the critical path."""
    played = []
    synthesised = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    clips.render(app.tts, messages.get("cloud.thinking", app.language.current),
                 app.language.current, app_module.MESSAGE_AUDIO_DIR)
    monkeypatch.setattr(app.tts, "synthesize", lambda *a, **k: synthesised.append(a))

    app._speak_thinking()

    assert played == [_clip(app, "cloud.thinking")]
    assert synthesised == [], "synthesised a clip that was already rendered"


def test_speaking_thinking_falls_back_when_the_clip_is_missing(app, monkeypatch):
    """First boot after the message text changes, or before
    `render_messages` has been run. Better a slow sentence than a silent
    one in front of the longest wait on the device."""
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))

    app._speak_thinking()      # nothing rendered yet

    assert played, "said nothing at all"


def test_the_fallback_caches_what_it_synthesised(app, monkeypatch):
    """So the cost is paid once rather than on every cue."""
    monkeypatch.setattr(app_module, "play", lambda path: None)

    app._speak_thinking()

    assert _clip(app, "cloud.thinking") is not None


def test_a_static_message_synthesised_live_is_kept_permanently(app, monkeypatch):
    """Otherwise the never-evicted guarantee depends on someone having
    run `render_messages`. Forget it, and the rarely-spoken static
    messages — the emergency-delivery failures — live only in the cache,
    where the sweep takes the oldest first."""
    monkeypatch.setattr(app_module, "play", lambda path: None)

    app._speak_thinking()

    assert _clip(app, "cloud.thinking").parent == app_module.MESSAGE_AUDIO_DIR


def test_the_permanent_copy_is_not_pruned_by_the_renderer(app, monkeypatch):
    """`render_messages` deletes anything in that directory whose text is
    not in `messages.py`. A static message's is, so a clip the app wrote
    itself survives the next run rather than being treated as debris."""
    from indepensense.intents import messages as messages_module
    monkeypatch.setattr(app_module, "play", lambda path: None)
    app._speak_thinking()
    written = _clip(app, "cloud.thinking").name

    wanted = {
        clips.filename(messages_module.get(key, language), language)
        for key in messages_module.static_keys()
        for language in app.language.supported
    }

    assert written in wanted


def test_speaking_an_unheard_notice_plays_its_clip(app, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    app._play_clip("voice.nothing_heard")

    assert played == [_clip(app, "voice.nothing_heard")]


def test_the_greeting_goes_through_the_same_path(app, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))

    app._speak_greeting()

    assert played == [_clip(app, "language.greeting")]


def test_a_broken_speaker_does_not_break_the_pipeline(app, monkeypatch):
    """Every caller is covering a silence. A failure here must not turn
    that into an exception on the voice thread."""
    def _explode(_path):
        raise OSError("output device disappeared")

    monkeypatch.setattr(app_module, "play", _explode)

    app._play_clip("voice.nothing_heard")      # must not raise


def test_a_broken_tts_does_not_break_the_pipeline_either(app, monkeypatch):
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(
        app.tts, "synthesize",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("voice gone")),
    )

    app._play_clip("voice.nothing_heard")      # must not raise
