"""Unit tests for the content-addressed clip store.

The three properties worth pinning are the three the design rests on:
the same sentence reuses its clip, an *edited* sentence does not, and a
sweep can never reach the static messages.
"""
import os
import wave

import pytest

from indepensense.voice import clips
from indepensense.voice.mock import MockTTS


@pytest.fixture
def dirs(tmp_path):
    """The permanent and ephemeral halves, as `app` wires them."""
    return tmp_path / "messages", tmp_path / "cache"


def _wav(path, seconds=1.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


# --- naming ------------------------------------------------------------------

def test_the_same_sentence_names_the_same_clip():
    assert clips.filename("Alert sent.", "en") == clips.filename("Alert sent.", "en")


def test_editing_the_text_names_a_different_clip():
    """The whole reason the hash is of the text and not of the message
    key: a reworded sentence must not keep playing its old recording."""
    assert clips.filename("Alert sent.", "en") != clips.filename("Alert sent!", "en")


def test_each_language_gets_its_own_clip():
    """Two voices, two recordings — even where the text coincides, which
    it does for place names and brands."""
    assert clips.filename("Jollibee", "en") != clips.filename("Jollibee", "tl")


def test_the_language_cannot_bleed_into_the_text():
    """A plain concatenation would make these two collide."""
    assert clips.digest("glish hello", "en") != clips.digest("hello", "english")


# --- lookup ------------------------------------------------------------------

def test_a_missing_clip_is_not_found(dirs):
    assert clips.find("never said", "en", *dirs) is None


def test_a_rendered_clip_is_found_again(dirs):
    _, cache = dirs
    clips.render(MockTTS(), "Alert sent.", "en", cache)

    assert clips.find("Alert sent.", "en", *dirs) is not None


def test_the_permanent_copy_wins_over_the_cached_one(dirs):
    """Order is the caller's guarantee that a static message is served
    from the directory the sweep cannot touch."""
    messages_dir, cache = dirs
    clips.render(MockTTS(), "Alert sent.", "en", cache)
    clips.render(MockTTS(), "Alert sent.", "en", messages_dir)

    assert clips.find("Alert sent.", "en", *dirs).parent == messages_dir


def test_an_edited_message_misses_its_old_clip(dirs):
    """Re-running the renderer is what repairs this; until then the
    sentence synthesises live rather than playing the stale wording."""
    messages_dir, cache = dirs
    clips.render(MockTTS(), "Battery low.", "en", messages_dir)

    assert clips.find("Battery is low.", "en", *dirs) is None


# --- rendering ---------------------------------------------------------------

def test_rendering_creates_the_directory(dirs):
    _, cache = dirs
    assert not cache.exists()

    clips.render(MockTTS(), "Alert sent.", "en", cache)

    assert cache.exists()


def test_rendering_leaves_a_playable_wav(dirs):
    _, cache = dirs
    path = clips.render(MockTTS(), "Alert sent.", "en", cache)

    with wave.open(str(path), "rb") as handle:
        assert handle.getnframes() > 0


def test_rendering_leaves_no_temporary_behind(dirs):
    _, cache = dirs
    clips.render(MockTTS(), "Alert sent.", "en", cache)

    assert list(cache.glob("*.part")) == []


def test_a_failed_render_leaves_nothing_at_all(dirs):
    """A truncated WAV at the final name would be permanent damage: it
    exists, so `find` returns it, and the wearable clips that sentence
    short forever. The temporary file plus rename is what prevents it."""
    _, cache = dirs

    class _Broken:
        def synthesize(self, text, output_path, language=None):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"RIFF truncated")
            raise RuntimeError("voice died mid-sentence")

    with pytest.raises(RuntimeError):
        clips.render(_Broken(), "Alert sent.", "en", cache)

    assert clips.find("Alert sent.", "en", cache) is None
    assert list(cache.glob("*.part")) == []


def test_rendering_twice_is_idempotent(dirs):
    """Two threads can be asked for the same sentence at once — the
    announcer and the voice pipeline both speak."""
    _, cache = dirs
    first = clips.render(MockTTS(), "Alert sent.", "en", cache)
    second = clips.render(MockTTS(), "Alert sent.", "en", cache)

    assert first == second
    assert len(list(cache.glob("*.wav"))) == 1


# --- sweeping ----------------------------------------------------------------

def test_a_cache_under_its_cap_is_left_alone(dirs):
    _, cache = dirs
    _wav(cache / "aaaa.wav")

    assert clips.sweep(cache, max_bytes=10_000_000) == 0
    assert len(list(cache.glob("*.wav"))) == 1


def test_sweeping_a_missing_directory_is_not_an_error(dirs):
    _, cache = dirs
    assert clips.sweep(cache, max_bytes=1) == 0


def test_the_oldest_clips_go_first(dirs):
    _, cache = dirs
    old = _wav(cache / "old.wav")
    new = _wav(cache / "new.wav")
    os.utime(old, (1_000_000, 1_000_000))
    os.utime(new, (2_000_000, 2_000_000))

    clips.sweep(cache, max_bytes=new.stat().st_size)

    assert not old.exists()
    assert new.exists()


def test_sweeping_stops_once_it_fits(dirs):
    """Not a purge — it evicts the minimum and leaves the rest cached."""
    _, cache = dirs
    sizes = []
    for index in range(4):
        path = _wav(cache / f"clip{index}.wav")
        os.utime(path, (1_000_000 + index, 1_000_000 + index))
        sizes.append(path.stat().st_size)

    clips.sweep(cache, max_bytes=sum(sizes[:2]))

    assert len(list(cache.glob("*.wav"))) == 2


def test_abandoned_temporaries_are_cleaned_up(dirs):
    """Debris from a power loss mid-synthesis. No live writer owns a name
    containing a pid that no longer exists."""
    _, cache = dirs
    scratch = cache / "abcd.999.888.part"
    scratch.parent.mkdir(parents=True)
    scratch.write_bytes(b"half a sentence")

    clips.sweep(cache, max_bytes=10_000_000)

    assert not scratch.exists()


def test_the_sweep_never_reaches_the_static_messages(dirs):
    """The reason there are two directories at all. Age-based eviction
    over one would delete the least-spoken clips first, and those are
    `emergency.delivery.all_failed` and its neighbours — needed at the
    one moment there is no time to synthesise them."""
    messages_dir, cache = dirs
    rare = clips.render(MockTTS(), "I could not reach anyone.", "en", messages_dir)
    os.utime(rare, (1_000, 1_000))         # untouched for years
    _wav(cache / "recent.wav")

    clips.sweep(cache, max_bytes=0)

    assert rare.exists()
    assert list(cache.glob("*.wav")) == []
