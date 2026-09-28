"""Unit tests for stream ownership in `voice/audio.py`.

These exist because of a crash on the assembled prototype. The wearable
aborted with `double free or corruption (out)` — a C-level fault inside
PortAudio with no Python traceback — when a PTT chime was played on
gpiozero's button-callback thread while the announcer was mid-sentence.

The mechanism: `sounddevice` keeps one global playback context, and
`sd.play()` starts by calling the global `sd.stop()`, which closes whatever
stream that global points at. The announcer's thread then closed the same
PortAudio stream again on its way out of its own `sd.play`. Two closes, one
stream.

So the properties worth asserting are not "does audio come out" — that needs
a speaker and a human ear. They are structural, and they are exactly what
the fake stream in `conftest.py` is instrumented for:

  1. every stream is closed exactly once,
  2. by the thread that opened it,
  3. and only one is ever live at a time.

Anything that holds those three cannot reproduce the crash, whatever order
the threads happen to run in.
"""
import threading
import time

import pytest

from indepensense.voice import audio


def _play_from_threads(fake_sd, count: int, wav, hold_s: float = 0.005) -> None:
    """Fire `count` concurrent `play` calls and wait for all of them.

    Each write holds the stream open briefly. Without that the fake returns
    instantly and the threads can serialise by luck, so the overlap
    assertion would pass against an unlocked implementation too — green, and
    proving nothing. Verified by removing `_playback_lock` and watching
    `test_only_one_stream_is_live_at_a_time` fail.
    """
    if fake_sd.after_write is None:
        fake_sd.after_write = lambda: time.sleep(hold_s)

    workers = [
        threading.Thread(target=audio.play, args=(wav,), name=f"player-{i}")
        for i in range(count)
    ]
    for worker in workers:
        worker.start()
        time.sleep(0)               # let each thread reach the lock
    for worker in workers:
        worker.join(timeout=5.0)
        assert not worker.is_alive(), "a playback thread deadlocked"


# --- the three structural properties -----------------------------------------

def test_every_stream_is_closed_exactly_once(fake_sd, wav):
    """The crash was a second close of an already-closed stream. One close
    per stream is the invariant that makes it unreachable."""
    _play_from_threads(fake_sd, 8, wav)

    assert len(fake_sd.streams) == 8
    for stream in fake_sd.streams:
        assert stream.closed == 1, f"stream closed {stream.closed} times"


def test_a_stream_is_only_ever_closed_by_the_thread_that_opened_it(fake_sd, wav):
    """`sd.play` used to close *other* threads' streams. Ownership is what
    replaced the lock-and-hope approach, so it gets asserted directly."""
    _play_from_threads(fake_sd, 8, wav)

    for stream in fake_sd.streams:
        assert len(stream.closed_by) == 1
        assert stream.closed_by[0].startswith("player-")


def test_only_one_stream_is_live_at_a_time(fake_sd, wav):
    """Two concurrent output streams do not crash PortAudio — they talk over
    each other, which for a device whose only channel to its user is speech
    is its own kind of failure."""
    _play_from_threads(fake_sd, 8, wav)

    assert fake_sd.max_live == 1
    assert fake_sd.live == 0, "a stream was left open"


def test_a_chime_never_overlaps_speech(fake_sd, wav):
    """The exact collision that crashed the device: the chime runs on the
    button-callback thread, the announcement on the announcer thread."""
    pytest.importorskip("numpy")     # play_chime synthesises its tone

    speech = threading.Thread(target=audio.play, args=(wav,), name="announcer")
    chime = threading.Thread(target=audio.play_chime, name="button-callback")
    speech.start()
    chime.start()
    speech.join(timeout=5.0)
    chime.join(timeout=5.0)

    assert fake_sd.max_live == 1
    for stream in fake_sd.streams:
        assert stream.closed == 1


# --- the module-level API must stay unused -----------------------------------

def test_playback_never_touches_sounddevices_global_api(fake_sd, wav):
    """`sd.play` / `sd.stop` / `sd.rec` all route through the one global
    context. Using any of them reintroduces the bug, so the fake records
    the attempt rather than letting it work."""
    audio.play(wav)
    audio.stop_playback()

    assert fake_sd.global_calls == []


def test_stop_playback_works_with_no_audio_stack_at_all(monkeypatch):
    """It sets a flag and nothing else — so it cannot fail on a dev machine,
    and more importantly cannot reach into a stream it does not own."""
    import sys

    monkeypatch.setitem(sys.modules, "sounddevice", None)
    audio.stop_playback()           # must not raise
    assert audio._stop_requested.is_set()
    audio._stop_requested.clear()


# --- stopping -----------------------------------------------------------------

def test_stop_playback_cuts_the_current_utterance_short(fake_sd, fake_sf, wav):
    """`vision.read` on a menu is thirty seconds of speech. The stop press
    has to land mid-utterance, not at the end of it."""
    fake_sf.frames = audio._BLOCK_FRAMES * 10
    # Request the stop from inside the first write, so the assertion is on
    # the loop's behaviour rather than on a sleep winning a race.
    fake_sd.after_write = audio.stop_playback

    audio.play(wav)

    stream = fake_sd.streams[0]
    assert stream.blocks == [audio._BLOCK_FRAMES], "kept writing after the stop"
    assert stream.aborted == 1, "drained the buffer instead of aborting"
    assert stream.closed == 1


def test_a_stale_stop_does_not_silence_the_next_utterance(fake_sd, fake_sf, wav):
    """Stopping is about the sentence in progress. If the flag survived into
    the next `play`, one stop press would mute the wearable permanently."""
    fake_sf.frames = audio._BLOCK_FRAMES * 3
    audio.stop_playback()           # nothing playing — a no-op request

    audio.play(wav)

    assert len(fake_sd.streams[0].blocks) == 3
    assert fake_sd.streams[0].aborted == 0


def test_stopping_does_not_strand_a_queued_utterance(fake_sd, fake_sf, wav):
    """A stop lands on the speaker, not on the lock. Whoever was waiting
    behind it still gets to speak."""
    fake_sf.frames = audio._BLOCK_FRAMES * 4
    calls = []

    def _stop_once():
        if not calls:
            calls.append(True)
            audio.stop_playback()

    fake_sd.after_write = _stop_once
    _play_from_threads(fake_sd, 2, wav)

    aborted = [s for s in fake_sd.streams if s.aborted]
    finished = [s for s in fake_sd.streams if not s.aborted]
    assert len(aborted) == 1, "the stop should cut exactly one utterance"
    assert len(finished) == 1 and len(finished[0].blocks) == 4


# --- the playing flag ---------------------------------------------------------

def test_the_flag_is_cleared_when_a_stream_raises(fake_sd, wav):
    """If `_playing` leaked, every later stop press would be swallowed and
    the repeat button would look broken."""
    fake_sd.raise_on_write = True

    with pytest.raises(RuntimeError):
        audio.play(wav)

    assert audio.is_playing() is False
    assert fake_sd.streams[0].closed == 1, "an exception must still close the stream"
