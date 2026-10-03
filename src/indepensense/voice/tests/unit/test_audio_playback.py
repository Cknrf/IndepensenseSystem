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


# --- interrupt cues ----------------------------------------------------------
#
# A press that stops the wearable talking used to produce nothing, which is
# also what a device that has just died produces. These cues are the
# difference. They are generated here rather than read from WAVs so the
# device ships no audio assets it has to find on disk at the one moment it
# needs to say "I stopped".

def test_the_stop_cue_owns_and_closes_its_stream(fake_sd):
    pytest.importorskip("numpy")

    audio.play_stop_cue()

    assert len(fake_sd.streams) == 1
    assert fake_sd.streams[0].closed == 1
    assert fake_sd.max_live == 1


def test_a_cue_never_overlaps_speech(fake_sd, wav):
    """Same collision as the chime: a cue runs on gpiozero's callback
    thread while the announcer is mid-sentence. The stop cue is played
    *immediately after* `stop_playback`, so this ordering is the common
    case rather than a corner one."""
    pytest.importorskip("numpy")

    speech = threading.Thread(target=audio.play, args=(wav,), name="announcer")
    cue = threading.Thread(target=audio.play_stop_cue, name="button-callback")
    speech.start()
    cue.start()
    speech.join(timeout=5.0)
    cue.join(timeout=5.0)

    assert fake_sd.max_live == 1
    for stream in fake_sd.streams:
        assert stream.closed == 1


def test_a_cue_does_not_count_as_speech(fake_sd):
    """`is_playing` gates the stop press. A cue that set it would make the
    *next* press land on nothing — the user presses stop twice in a row
    when the first one seemed not to work."""
    pytest.importorskip("numpy")

    audio.play_stop_cue()

    assert audio.is_playing() is False


def test_a_cue_clears_a_stale_stop_request(fake_sd):
    """The stop cue is played right after `stop_playback` set the flag.
    Without clearing it the cue would abort itself on its first block and
    the press would still be silent."""
    pytest.importorskip("numpy")

    audio.stop_playback()
    audio.play_stop_cue()

    assert fake_sd.streams[0].blocks, "the cue aborted on a stale stop flag"


def test_the_stop_and_busy_cues_sound_different(fake_sd):
    """They mean opposite things — "I stopped" against "I cannot" — and
    the wearer has no screen to tell them apart."""
    pytest.importorskip("numpy")

    audio.play_stop_cue()
    stop_frames = sum(fake_sd.streams[0].blocks)
    fake_sd.streams.clear()

    audio.play_busy_cue()
    busy_frames = sum(fake_sd.streams[0].blocks)

    assert stop_frames != busy_frames


def test_a_cue_with_no_steps_plays_nothing(fake_sd):
    """Guards the empty-sequence path: a zero-length array would reach
    PortAudio as a stream with nothing to write."""
    pytest.importorskip("numpy")

    audio.play_cue([])

    assert fake_sd.streams == []


# --- keeping the output device awake -----------------------------------------
#
# The wearable's USB headset mutes its own amplifier when the wire goes
# quiet and takes ~0.7-1.0 s to come back, which is longer than every cue
# this module makes. Measured: a 1.00 s tone was audible at 3-second gaps,
# a 0.64 s one was not, and holding the stream open 2 s after the last
# write changed nothing. PipeWire config did not fix it either — the node
# settles to `idle` and stops feeding the device whatever it is told.

def test_the_first_sound_starts_the_keepalive(fake_sd, fake_sf, wav, monkeypatch):
    """Lazy, not wired into `App.start`: the manual tests, probes and
    calibration tools all play audio without starting the app, and every
    one of them would otherwise reproduce the fault."""
    started = []
    monkeypatch.setattr(audio, "start_keepalive", lambda: started.append(1))

    audio.play(wav)

    assert started == [1]


def test_a_cue_starts_it_too(fake_sd, monkeypatch):
    pytest.importorskip("numpy")
    started = []
    monkeypatch.setattr(audio, "start_keepalive", lambda: started.append(1))

    audio.play_stop_cue()

    assert started == [1]


def test_starting_twice_runs_one_thread(fake_sd, real_keepalive):
    """Called before every single sound, so it has to be cheap and
    idempotent rather than spawning a thread per utterance."""
    audio.start_keepalive()
    first = audio._keepalive_thread
    audio.start_keepalive()

    try:
        assert audio._keepalive_thread is first
    finally:
        audio.stop_keepalive()


def test_it_holds_a_stream_open(fake_sd, real_keepalive):
    """The whole mechanism: a stream that stays open, so the amplifier
    never sees the wire go quiet."""
    audio.start_keepalive()
    try:
        assert _wait_until(lambda: len(fake_sd.streams) == 1)
        assert _wait_until(lambda: len(fake_sd.streams[0].blocks) > 2)
        assert fake_sd.streams[0].closed == 0, "released the device early"
    finally:
        audio.stop_keepalive()


def test_stopping_closes_the_stream(fake_sd, real_keepalive):
    audio.start_keepalive()
    assert _wait_until(lambda: len(fake_sd.streams) == 1)

    audio.stop_keepalive()

    assert fake_sd.streams[0].closed == 1


def test_stopping_when_not_running_is_a_no_op(fake_sd):
    audio.stop_keepalive()          # must not raise


def test_a_device_that_cannot_be_held_does_not_break_playback(fake_sd, fake_sf, wav, real_keepalive):
    """Every sound opens its own stream regardless of this one, so a
    keepalive that cannot start costs the workaround and nothing else."""
    fake_sd.raise_on_write = True
    audio.start_keepalive()
    assert _wait_until(lambda: not audio._keepalive_thread.is_alive(), 2.0)

    fake_sd.raise_on_write = False
    audio.play(wav)                 # must still work

    assert any(s.blocks for s in fake_sd.streams)


def _wait_until(condition, timeout_s: float = 2.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False
