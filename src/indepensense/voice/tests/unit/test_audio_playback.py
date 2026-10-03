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


# --- PortAudio re-initialisation ---------------------------------------------
#
# Only the FIRST stream of a process plays a short sound; every stream
# after it discards roughly its first 0.8 s, so a 0.2 s cue vanishes while
# a 1 s tone is merely clipped. Measured on the device: short #1 audible,
# short #2 silent, long tone audible, short #3 silent — and the same cue
# played by five separate processes was audible five times.
#
# `Pa_Terminate` + `Pa_Initialize` restores the first-stream condition.
# The guard around it is the dangerous part: terminating PortAudio while
# any stream is live is the same C-level double free that `sd.play`
# caused.

@pytest.fixture
def reinit_calls(fake_sd, monkeypatch):
    """Records each PortAudio re-initialisation."""
    calls = []

    def _record():
        calls.append(1)
        return True             # as a successful re-init reports

    monkeypatch.setattr(audio, "_reinitialise_portaudio", _record)
    audio._portaudio_streams = 0
    yield calls
    audio._portaudio_streams = 0


def test_playback_reinitialises_portaudio(fake_sd, fake_sf, wav, reinit_calls):
    audio.play(wav)

    assert reinit_calls == [1]


def test_every_sound_reinitialises(fake_sd, fake_sf, wav, reinit_calls):
    """Not just the first — the second sound is the one that was silent."""
    audio.play(wav)
    audio.play(wav)
    audio.play(wav)

    assert len(reinit_calls) == 3


def test_recording_reinitialises_too(fake_sd, fake_sf, tmp_path, reinit_calls):
    """Input counts as well as output — the count exists to stop a cue
    tearing PortAudio down under a live microphone, so both sides have to
    register."""
    from indepensense.feedback.mock import MockButton

    audio.record_until_button(MockButton(), tmp_path / "in.wav",
                              max_duration_s=0.05)

    assert reinit_calls == [1]
    assert audio._portaudio_streams == 0


def test_the_count_returns_to_zero(fake_sd, fake_sf, wav, reinit_calls):
    """A leaked count would disable the re-init for the rest of the run,
    and the symptom would be cues going quiet again."""
    audio.play(wav)

    assert audio._portaudio_streams == 0


def test_the_count_returns_to_zero_when_a_stream_raises(fake_sd, fake_sf, wav,
                                                        reinit_calls):
    fake_sd.raise_on_write = True

    with pytest.raises(Exception):
        audio.play(wav)

    assert audio._portaudio_streams == 0


def test_no_reinit_while_another_stream_is_open(fake_sd, fake_sf, wav, reinit_calls):
    """The guard that matters. Terminating PortAudio under a live
    recording is a segfault, not a clipped cue — so a sound played while
    the microphone is open skips the re-init rather than risking it."""
    audio._portaudio_streams = 1          # as if a recording were running

    audio.play(wav)

    assert reinit_calls == [], "re-initialised with a stream still open"


def test_the_guard_does_not_block_playback(fake_sd, fake_sf, wav, reinit_calls):
    """Skipping the re-init costs the fix, not the sound."""
    audio._portaudio_streams = 1

    audio.play(wav)

    assert fake_sd.streams and fake_sd.streams[0].blocks


def test_a_failing_reinit_does_not_break_playback(fake_sd, fake_sf, wav, monkeypatch):
    """`_terminate`/`_initialize` are sounddevice private API. If a future
    version removes them the cues clip again — the device must not go
    silent altogether, so the real function swallows the failure."""
    def _explode():
        raise AttributeError("module 'sounddevice' has no attribute '_terminate'")

    monkeypatch.setattr(fake_sd, "_terminate", _explode, raising=False)
    audio._portaudio_streams = 0

    audio.play(wav)

    assert fake_sd.streams and fake_sd.streams[0].blocks, "playback was lost"
    assert audio._portaudio_streams == 0


# --- no stream is ever built on a context that is later torn down -----------
#
# The eight tests above all passed against a version that re-initialised
# PortAudio *after* constructing the stream, because a fake stream did not
# care that the library had been torn down underneath it. The device did:
#
#     PortAudioError: Error starting stream: Invalid stream pointer [-9988]
#
# `conftest` now models that — a stream records the PortAudio generation it
# was born into and refuses to start if the generation has moved on — so
# the fault is caught wherever it is reintroduced, rather than only in the
# one arrangement of calls that happened to be wrong at the time.
#
# This is deliberately NOT a test that the re-init precedes the stream.
# It no longer does: the re-init runs at *release*, so the context is
# already fresh when the next stream is built. Asserting the old order
# would pin an implementation detail that the latency fix had to change.

def test_playback_never_builds_a_stream_on_a_stale_context(fake_sd, fake_sf, wav):
    audio.play(wav)
    audio.play(wav)
    audio.play(wav)

    assert len(fake_sd.streams) == 3
    for stream in fake_sd.streams:
        assert stream.started == 1, "a stream was invalidated before it started"
        assert stream.blocks, "a stream produced no audio"


def test_recording_never_builds_a_stream_on_a_stale_context(fake_sd, fake_sf,
                                                            tmp_path):
    from indepensense.feedback.mock import MockButton

    for n in range(3):
        audio.record_until_button(MockButton(), tmp_path / f"in{n}.wav",
                                  max_duration_s=0.05)

    assert len(fake_sd.streams) == 3
    for stream in fake_sd.streams:
        assert stream.started == 1


def test_speech_and_cues_interleaved_stay_valid(fake_sd, fake_sf, wav, tmp_path):
    """The real sequence: chime, record, speak, cue. Every one of them has
    to survive the others' re-initialisations."""
    pytest.importorskip("numpy")
    from indepensense.feedback.mock import MockButton

    audio.play_chime()
    audio.record_until_button(MockButton(), tmp_path / "in.wav",
                              max_duration_s=0.05)
    audio.play(wav)
    audio.play_stop_cue()

    assert len(fake_sd.streams) == 4
    for stream in fake_sd.streams:
        assert stream.started == 1


# --- the re-init is paid after the sound, not before it ---------------------
#
# Measured on the Pi: 96 ms, because it re-enumerates every ALSA device
# (2 ms on a Mac via CoreAudio). Paid before the stream, that lands on the
# front of a 200 ms cue, and — worse — between the PTT chime and the
# microphone going live, where it swallows the first tenth of a second of
# whatever the user says. Paid after, it falls in the gap between sounds.

def test_a_sound_does_not_reinitialise_before_playing(fake_sd, fake_sf, wav):
    """The latency property. If this fails, every sound costs 96 ms more."""
    calls = []
    original = audio._reinitialise_portaudio

    def _counting():
        calls.append(len(fake_sd.streams))
        return original()

    audio._reinitialise_portaudio = _counting
    try:
        audio.play(wav)
        audio.play(wav)
    finally:
        audio._reinitialise_portaudio = original

    # Each re-init happened once the stream it follows already existed —
    # i.e. after the sound, never in front of one.
    assert calls == [1, 2], f"re-initialised before a sound: {calls}"


def test_the_first_sound_of_the_process_pays_nothing(fake_sd, fake_sf, wav,
                                                     reinit_calls):
    """Importing sounddevice already initialised PortAudio, so the first
    stream is a first stream and needs no help to be one."""
    audio._portaudio_fresh = True

    audio.play(wav)

    assert reinit_calls == [1], "the first sound should re-init once, on the way out"
    assert fake_sd.streams[0].blocks


def test_a_stale_context_is_still_refreshed_before_the_stream(fake_sd, fake_sf,
                                                              wav, reinit_calls):
    """The backstop. If a release was skipped or its re-init failed, the
    next claim must do the work rather than open a stale stream."""
    audio._portaudio_fresh = False

    audio.play(wav)

    # Twice: once on the way in because the context was stale, once on the
    # way out to leave it fresh for the next sound.
    assert len(reinit_calls) == 2


# --- recovery: PortAudio must never be left down -----------------------------
#
# `Pa_Initialize`/`Pa_Terminate` are reference counted, and the first
# version of this fix ignored that in two ways that both end in silence:
#
#   * `try: _terminate(); _initialize()` skips the initialise whenever the
#     terminate raises. Terminating an already-down PortAudio raises
#     exactly that, so one transient `Pa_Initialize` failure left the
#     library terminated FOREVER — every later stream died with
#     `Error querying device -1` and the wearable was mute until restart.
#     Reproduced on the dev machine, not theorised.
#
#   * a count above 1 means a single `_terminate()` tears nothing down, so
#     the re-init silently stops working and the cues go quiet again with
#     no error anywhere.

def test_recovers_when_portaudio_was_left_terminated(fake_sd, fake_sf, wav):
    """The permanent-silence bug. One failed initialise must not be fatal.

    A library that is down implies the last re-init failed, which is
    exactly the state `_portaudio_fresh = False` records — so the next
    claim refreshes before building anything."""
    fake_sd._initialized = 0               # as a failed `Pa_Initialize` leaves it
    audio._portaudio_fresh = False

    audio.play(wav)

    assert fake_sd._initialized == 1, "PortAudio was left down"
    assert fake_sd.streams and fake_sd.streams[0].blocks, "the device stayed mute"


def test_a_failed_initialise_is_retried_by_the_next_sound(fake_sd, fake_sf, wav):
    """Failure is survivable only if the next sound tries again.

    Three sounds, because the failure now surfaces one sound later than
    it used to: the re-init runs on the way *out*, so the sound that
    triggers the failure has already been played by the time it happens.
    """
    fake_sd.fail_initialize = True
    audio.play(wav)                        # plays fine; leaves PortAudio down
    assert fake_sd.streams[0].blocks
    assert fake_sd._initialized == 0
    assert audio._portaudio_fresh is False, "a failed re-init must not read as fresh"

    with pytest.raises(Exception):         # nothing can open while it is down
        audio.play(wav)

    fake_sd.fail_initialize = False
    audio.play(wav)

    assert fake_sd._initialized == 1
    assert fake_sd.streams[-1].blocks, "the device did not recover"


def test_the_reference_count_is_driven_to_zero(fake_sd, fake_sf, wav):
    """A count above 1 means nothing is actually torn down, so the cues
    would go quiet again with no error to show for it."""
    fake_sd._initialized = 3

    audio.play(wav)

    assert fake_sd.reinits == 3, "did not unwind the count, so nothing reset"
    assert fake_sd._initialized == 1


def test_the_count_stays_balanced_across_many_sounds(fake_sd, fake_sf, wav):
    """Drift either way is a silent failure: up and the re-init stops
    working, down and the device dies."""
    for _ in range(10):
        audio.play(wav)

    assert fake_sd._initialized == 1
