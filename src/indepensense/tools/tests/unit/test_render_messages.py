"""Unit tests for the ahead-of-time clip renderer.

Written after the tool shipped broken: it called `build_tts()` with no
arguments, which the Mac never noticed because `--dry-run` returns
before that line and the real engines only exist on the Pi. The first
run on the device died on a `TypeError` with 122 clips still to build.

So the point of this file is to exercise `main()` end to end with a mock
engine — every branch except the synthesis itself, which is the one part
that genuinely needs hardware.
"""
import wave

import pytest

from indepensense.intents import messages
from indepensense.tools import render_messages
from indepensense.voice import clips
from indepensense.voice.mock import MockTTS


@pytest.fixture
def target(tmp_path, monkeypatch):
    """Point the tool at a temp directory with a mock engine behind it."""
    monkeypatch.setattr(render_messages, "MESSAGE_AUDIO_DIR", tmp_path)
    monkeypatch.setattr(render_messages, "build_tts", lambda **kwargs: MockTTS())
    monkeypatch.setattr(render_messages, "SUPPORTED_LANGUAGES", ("en", "tl"))
    return tmp_path


def _run(*argv) -> int:
    return render_messages.main(argv=list(argv))


def _clips(directory):
    return sorted(p.name for p in directory.glob("*.wav"))


# --- the bug this file exists for --------------------------------------------

def test_the_engine_is_built_with_the_arguments_it_requires():
    """`build_tts` takes the two voice maps rather than reading config,
    so that every caller renders with the engines the device will use.
    Calling it bare raised a TypeError that no Mac test could reach."""
    import inspect
    from indepensense.config import MMS_VOICES, PIPER_VOICES
    from indepensense.voice.router import build_tts

    inspect.signature(build_tts).bind(
        piper_voices=PIPER_VOICES, mms_voices=MMS_VOICES,
    )


def test_the_tool_passes_both_voice_maps(target, monkeypatch):
    """Not just that the call is well-formed, but that it carries the
    Tagalog voice: an English-only router would render all 122 clips
    with Piper and the Tagalog half would be wrong rather than missing."""
    seen = {}

    def _spy(**kwargs):
        seen.update(kwargs)
        return MockTTS()

    monkeypatch.setattr(render_messages, "build_tts", _spy)
    _run()

    assert set(seen) == {"piper_voices", "mms_voices"}
    assert seen["mms_voices"], "no Tagalog voice passed"


# --- rendering ----------------------------------------------------------------

def test_every_static_message_is_rendered_in_every_language(target):
    assert _run() == 0

    assert len(_clips(target)) == len(messages.static_keys()) * 2


def test_the_clips_are_playable(target):
    _run()

    for clip in target.glob("*.wav"):
        with wave.open(str(clip), "rb") as handle:
            assert handle.getnframes() > 0, clip.name


def test_templated_messages_are_skipped(target):
    """A cached clip of "Battery at {percent} percent" would be replayed
    with a stale number, or with the brace spoken aloud."""
    _run()

    rendered = set(_clips(target))
    battery = messages.get("battery.level", "en", percent=47)

    assert clips.filename(battery, "en") not in rendered


def test_rerunning_renders_nothing(target):
    _run()
    stamps = {p.name: p.stat().st_mtime_ns for p in target.glob("*.wav")}

    _run()

    assert {p.name: p.stat().st_mtime_ns for p in target.glob("*.wav")} == stamps


def test_force_rerenders_everything(target):
    """For a changed voice model, where the text is identical but the
    audio should not be."""
    _run()
    before = {p.name: p.stat().st_mtime_ns for p in target.glob("*.wav")}

    _run("--force")

    after = {p.name: p.stat().st_mtime_ns for p in target.glob("*.wav")}
    assert set(after) == set(before)
    assert after != before


def test_only_the_edited_message_is_rerendered(target, monkeypatch):
    """What makes re-running cheap: the hash is per sentence, so an edit
    to one message does not cost another two minutes."""
    _run()
    before = {p.name: p.stat().st_mtime_ns for p in target.glob("*.wav")}

    monkeypatch.setitem(
        messages.MESSAGES["emergency.sent"], "en", "Your alert has gone out.",
    )
    _run()

    after = {p.name: p.stat().st_mtime_ns for p in target.glob("*.wav")}
    added = set(after) - set(before)
    assert len(added) == 1
    assert all(after[name] == before[name] for name in before if name in after)


# --- pruning ------------------------------------------------------------------

def test_a_clip_for_deleted_text_is_removed(target, monkeypatch):
    """One recording per sentence, not every wording it has ever had —
    this runs on an SD card."""
    _run()
    stale = clips.render(MockTTS(), "A sentence nobody says any more.", "en", target)

    _run()

    assert not stale.exists()


def test_the_edited_message_leaves_only_its_new_clip(target, monkeypatch):
    _run()
    stale = clips.filename(messages.get("emergency.sent", "en"), "en")

    monkeypatch.setitem(
        messages.MESSAGES["emergency.sent"], "en", "Your alert has gone out.",
    )
    _run()

    assert stale not in _clips(target)
    assert len(_clips(target)) == len(messages.static_keys()) * 2


def test_a_language_subset_never_prunes(target):
    """Every other language's clips look stale to a one-language run and
    would all be deleted."""
    _run()
    total = len(_clips(target))

    _run("--language", "en")

    assert len(_clips(target)) == total


# --- dry run ------------------------------------------------------------------

def test_a_dry_run_writes_nothing(target):
    assert _run("--dry-run") == 0

    assert _clips(target) == []


def test_a_dry_run_never_loads_an_engine(target, monkeypatch):
    """Which is what makes it usable on a Mac, where the import fails."""
    monkeypatch.setattr(
        render_messages, "build_tts",
        lambda **kwargs: pytest.fail("loaded TTS during a dry run"),
    )

    _run("--dry-run")


# --- failure ------------------------------------------------------------------

def test_one_failed_clip_does_not_stop_the_rest(target, monkeypatch):
    """A voice choking on one phoneme must not cost the other 121."""
    class _FlakyTTS(MockTTS):
        def synthesize(self, text, output_path, language=None):
            if language == "tl":
                raise RuntimeError("voice missing a phoneme")
            super().synthesize(text, output_path, language=language)

    monkeypatch.setattr(render_messages, "build_tts", lambda **kwargs: _FlakyTTS())

    assert _run() == 1
    assert len(_clips(target)) == len(messages.static_keys())


def test_a_failed_clip_leaves_no_truncated_file(target, monkeypatch):
    """`clips.render` renames into place, so a partial write never lands
    at the real filename where it would be played forever."""
    class _BrokenTTS(MockTTS):
        def synthesize(self, text, output_path, language=None):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"RIFF truncated")
            raise RuntimeError("died mid-sentence")

    monkeypatch.setattr(render_messages, "build_tts", lambda **kwargs: _BrokenTTS())

    _run()

    assert _clips(target) == []
    assert list((target / clips.SCRATCH_DIR_NAME).glob("*")) == []
