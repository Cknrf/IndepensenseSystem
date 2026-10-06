"""The announcer plays from the clip store instead of re-synthesising.

Before this it wrote `<microsecond timestamp>_announce.wav` per
utterance, so every sentence cost a full synthesis — 0.2-2.3 s on the Pi
— and nothing ever deleted the files. These tests pin both halves: the
second utterance of a sentence does not reach the TTS engine, and the
files stop accumulating.
"""
import time
import wave

import pytest

from indepensense import app as app_module
from indepensense.app import Announcer


class _CountingTTS:
    """A TTS engine that records every sentence it was asked to render."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text, output_path, language=None):
        self.calls.append((text, language))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(16000)
            handle.writeframes(b"\x00\x00" * 1600)


@pytest.fixture
def played(monkeypatch):
    """Captures playback instead of opening PortAudio."""
    paths = []
    monkeypatch.setattr(app_module, "play", lambda path: paths.append(path))
    return paths


@pytest.fixture
def announcer(tmp_path, played):
    tts = _CountingTTS()
    instance = Announcer(tts, tmp_path / "messages", tmp_path / "cache")
    instance.tts = tts
    instance.played = played
    instance.start()
    yield instance
    instance.stop()


def _speak(announcer, text, language="en", critical=False):
    """Queue one sentence and wait for the worker to finish playing it.

    Waits on playback rather than on the queue emptying: the item is
    popped before it is rendered, so an empty queue only means the
    worker has picked it up.
    """
    expected = len(announcer.played) + 1
    announcer.say(text, language, critical=critical)
    deadline = time.monotonic() + 3.0
    while len(announcer.played) < expected and time.monotonic() < deadline:
        time.sleep(0.005)
    assert len(announcer.played) == expected, f"{text!r} was never played"


def test_the_first_utterance_is_synthesised(announcer, played):
    _speak(announcer, "Emergency alert sent.")

    assert announcer.tts.calls == [("Emergency alert sent.", "en")]
    assert len(played) == 1


def test_the_second_utterance_is_not(announcer, played):
    """The point of the whole change: a repeated sentence costs a file
    read rather than another 2 s of Piper."""
    _speak(announcer, "Emergency alert sent.")
    _speak(announcer, "Emergency alert sent.")

    assert len(announcer.tts.calls) == 1
    assert len(played) == 2


def test_the_same_sentence_does_not_accumulate_files(announcer, tmp_path):
    """Timestamped filenames meant one WAV per utterance forever —
    roughly 9 GB a year on the SD card. Identical text now collides onto
    one file by design."""
    for _ in range(3):
        _speak(announcer, "Emergency alert sent.")

    assert len(list((tmp_path / "cache").glob("*.wav"))) == 1


def test_a_different_sentence_still_gets_its_own_clip(announcer, tmp_path):
    _speak(announcer, "Turn left in twenty metres.")
    _speak(announcer, "Turn right in ten metres.")

    assert len(announcer.tts.calls) == 2
    assert len(list((tmp_path / "cache").glob("*.wav"))) == 2


def test_the_same_text_in_two_languages_is_synthesised_twice(announcer):
    """Different voices, different audio."""
    _speak(announcer, "Jollibee", language="en")
    _speak(announcer, "Jollibee", language="tl")

    assert len(announcer.tts.calls) == 2


def test_a_static_message_is_played_from_the_permanent_directory(
    announcer, tmp_path, played,
):
    """What `render_messages` buys: the sentence is already on disk, so
    the engine is never touched at all."""
    from indepensense.voice import clips
    text = "Emergency alert sent."
    clips.render(announcer.tts, text, "en", tmp_path / "messages")
    announcer.tts.calls.clear()

    _speak(announcer, text)

    assert announcer.tts.calls == []
    assert played[0].parent == tmp_path / "messages"


def test_a_cached_clip_is_still_dropped_when_a_critical_alert_preempts_it(
    announcer, played,
):
    """A hit shrinks the preemption window but does not remove it, and a
    nav cue must never play in front of a fall alert."""
    announcer.say("Turn left in twenty metres.", "en")
    taken = announcer._take()
    announcer.say("Fall detected.", "en", critical=True)   # bumps the epoch

    assert announcer._preempted_since(taken[1])


def test_the_cache_is_swept_once_the_render_count_is_reached(
    announcer, tmp_path, monkeypatch,
):
    monkeypatch.setattr(app_module, "CLIP_CACHE_SWEEP_EVERY", 2)
    monkeypatch.setattr(app_module, "CLIP_CACHE_MAX_BYTES", 0)

    for index in range(2):
        _speak(announcer, f"Sentence number {index}.")

    assert list((tmp_path / "cache").glob("*.wav")) == []


def test_a_failing_sweep_does_not_stop_the_wearable_speaking(
    announcer, monkeypatch, played,
):
    """A full or read-only card must not take the voice with it."""
    monkeypatch.setattr(app_module, "CLIP_CACHE_SWEEP_EVERY", 1)
    monkeypatch.setattr(
        app_module.clips, "sweep",
        lambda *a, **k: (_ for _ in ()).throw(OSError("read-only file system")),
    )

    _speak(announcer, "Emergency alert sent.")

    assert len(played) == 1


# --- where a miss is written -------------------------------------------------
#
# The announcer holds finished text, so it cannot tell a fixed sentence
# from a filled-in template. It is told, as a set of filenames built from
# `messages.static_keys()`. Without this, the two-directory split only
# protects messages that `render_messages` had already built, and the
# whole point was to protect them whether or not anyone ran it.

@pytest.fixture
def routing(tmp_path, played):
    """An announcer that knows one sentence is static."""
    from indepensense.voice import clips
    tts = _CountingTTS()
    instance = Announcer(
        tts, tmp_path / "messages", tmp_path / "cache",
        frozenset({clips.filename("Emergency alert sent.", "en")}),
    )
    instance.tts = tts
    instance.played = played
    instance.start()
    yield instance
    instance.stop()


def test_a_static_message_is_written_to_the_permanent_directory(routing, tmp_path):
    _speak(routing, "Emergency alert sent.")

    assert routing.played[0].parent == tmp_path / "messages"


def test_a_templated_sentence_is_written_to_the_cache(routing, tmp_path):
    """The reason the announcer is not simply told to keep everything:
    every distance and place name the device ever speaks would land
    somewhere the sweep can never reclaim."""
    _speak(routing, "Battery at 47 percent.")

    assert routing.played[0].parent == tmp_path / "cache"


def test_a_static_message_does_not_count_toward_the_sweep(routing, monkeypatch):
    """It was not written to the cache, so it has not grown it."""
    monkeypatch.setattr(app_module, "CLIP_CACHE_SWEEP_EVERY", 1)
    swept = []
    monkeypatch.setattr(app_module.clips, "sweep",
                        lambda *a, **k: swept.append(a) or 0)

    _speak(routing, "Emergency alert sent.")

    assert swept == []


def test_an_unknown_sentence_defaults_to_the_cache(routing, tmp_path):
    """Nothing is permanent unless the catalogue says so — a typo in a
    key must not quietly fill the unswept directory."""
    _speak(routing, "Something nobody put in messages.py.")

    assert routing.played[0].parent == tmp_path / "cache"


def test_the_static_set_is_derived_from_the_message_catalogue():
    """Listed by hand, it would stop matching the moment a message was
    added. This is the check that it is not."""
    from indepensense.app import _static_clip_names
    from indepensense.intents import messages
    from indepensense.voice import clips

    names = _static_clip_names(("en", "tl"))

    assert len(names) == len(messages.static_keys()) * 2
    assert clips.filename(messages.get("emergency.sent", "tl"), "tl") in names


def test_a_templated_message_is_absent_from_the_static_set():
    from indepensense.app import _static_clip_names
    from indepensense.intents import messages
    from indepensense.voice import clips

    names = _static_clip_names(("en",))
    battery = messages.get("battery.level", "en", percent=47)

    assert clips.filename(battery, "en") not in names
