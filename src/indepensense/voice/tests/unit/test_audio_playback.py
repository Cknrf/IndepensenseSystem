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


def test_recording_counts_but_does_not_reinitialise(fake_sd, fake_sf, tmp_path,
                                                    reinit_calls):
    """Input registers in the count but skips the refresh.

    The count is the safety half: it stops a cue on another thread
    tearing PortAudio down while the microphone is live. The refresh is
    the latency half, and input does not need it — `mic_onset_test` on
    the Pi captured 2.004 s of a 2 s recording with and without it alike,
    so the ~69 ms it cost sat between the chime and the microphone going
    live for no reason."""
    from indepensense.feedback.mock import MockButton

    audio.record_until_button(MockButton(), tmp_path / "in.wav",
                              max_duration_s=0.05)

    assert reinit_calls == [], "recording paid for a refresh it does not need"
    assert audio._portaudio_streams == 0


def test_every_recording_path_skips_the_refresh():
    """All three of them, not just the one the wearable uses.

    Checked by reading the source rather than by running each function:
    `record` finishes with `np.concatenate` over its captured blocks,
    which the fake's array stand-in cannot satisfy, and bending the fake
    into a real array for one assertion would make every other test in
    this file depend on numpy being installed.

    Crude, but it guards the thing that is actually at risk — a call site
    added or edited without the keyword, which would silently put ~69 ms
    back in front of every recording with no test turning red."""
    import inspect

    for function in (audio.record, audio.record_until_enter,
                     audio.record_until_button):
        source = inspect.getsource(function)
        assert "_claim_portaudio(refresh=False)" in source, (
            f"{function.__name__} refreshes PortAudio; input does not need it"
        )
        assert "_release_portaudio()" in source, (
            f"{function.__name__} would leak the stream count"
        )


def test_playback_still_refreshes():
    """The counterpart. Output is the side that does need it, and a
    blanket `refresh=False` would silence every cue again."""
    import inspect

    source = inspect.getsource(audio._write_blocks)
    assert "_claim_portaudio()" in source
    assert "refresh=False" not in source


def test_a_cue_during_a_recording_still_cannot_tear_portaudio_down(fake_sd,
                                                                   fake_sf,
                                                                   wav):
    """The reason recordings still take part in the count at all.

    Pressing repeat mid-recording plays the stop cue while the input
    stream is live, and terminating PortAudio under it is the C-level
    double free, not a clipped cue."""
    audio._claim_portaudio(refresh=False)       # as a live recording would
    try:
        audio.play(wav)
        assert fake_sd.streams[-1].blocks, "the cue did not play"
    finally:
        audio._release_portaudio()

    assert fake_sd.unsafe_reinits == []


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
    """It does not refresh, so nothing should invalidate it either."""
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


# --- the re-init must be adjacent to the stream -----------------------------
#
# 96 ms on the Pi, and it cannot be moved. Running it when a stream
# *closed* — so the cost fell between sounds instead of in front of them —
# passed every test here and silenced the cues on the device within a
# minute of being installed. Adjacency is the property that makes it work,
# so adjacency is what gets asserted.

def test_each_sound_reinitialises_immediately_before_its_stream(fake_sd, fake_sf,
                                                                wav):
    events = []
    original = audio._reinitialise_portaudio

    def _recording():
        events.append("reinit")
        return original()

    audio._reinitialise_portaudio = _recording
    try:
        monitored = fake_sd.OutputStream

        def _stream(**kwargs):
            events.append("stream")
            return monitored(**kwargs)

        fake_sd.OutputStream = _stream
        fake_sd.InputStream = _stream
        audio.play(wav)
        audio.play(wav)
    finally:
        audio._reinitialise_portaudio = original

    assert events == ["reinit", "stream", "reinit", "stream"], (
        f"re-init and stream are not adjacent: {events}"
    )


def test_the_first_sound_reinitialises_too(fake_sd, fake_sf, wav, reinit_calls):
    """Import-time initialisation is stale by the time anything speaks —
    startup spends 30-60 s loading models first."""
    audio.play(wav)

    assert reinit_calls == [1]


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

    Every sound re-initialises on the way in, so the next one recovers."""
    fake_sd._initialized = 0               # as a failed `Pa_Initialize` leaves it

    audio.play(wav)

    assert fake_sd._initialized == 1, "PortAudio was left down"
    assert fake_sd.streams and fake_sd.streams[0].blocks, "the device stayed mute"


def test_a_failed_initialise_is_retried_by_the_next_sound(fake_sd, fake_sf, wav):
    """Failure is survivable only if the next sound tries again."""
    fake_sd.fail_initialize = True
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


# --- cue proportions ---------------------------------------------------------
#
# The waiting blip was reported as "no sound at all" and was not a code
# fault: at 45 ms and 0.12 amplitude it was specified below audibility.
# Loudness is not amplitude alone — the ear integrates energy over roughly
# 200 ms, so a tone shorter than that is heard quieter in proportion to
# its length as well. Energy goes as amplitude squared times duration,
# which is 20·log10(A) + 10·log10(T) in decibels.
#
# These tests pin the *proportions* rather than the raw numbers, so the
# cues stay tellable apart and audible if anyone retunes them. They are
# the only automatic guard there is: whether a cue can actually be heard
# is a question for `cue_test` and a pair of ears.

def _cue_seconds(steps, gap_s: float = 0.03) -> float:
    return sum(d for _, d in steps) + gap_s * (len(steps) - 1)


def _level_db(steps, amplitude: float) -> float:
    """Rough perceived level, relative to a 1.0-amplitude 1-second tone."""
    import math

    # Capped at the ear's integration window: past ~200 ms a longer tone
    # is not heard as louder, only as longer.
    seconds = min(_cue_seconds(steps), 0.2)
    return 20.0 * math.log10(amplitude) + 10.0 * math.log10(seconds)


def test_the_waiting_blip_is_quieter_than_the_cues_but_still_audible():
    """It recurs every 1.2 s while the device thinks, so it must read as
    background — but the version that was 14 dB down was simply gone."""
    stop = _level_db(audio._STOP_CUE, 0.3)
    blip = _level_db(audio._WAITING_TICK, audio._WAITING_AMPLITUDE)

    assert blip < stop - 2.0, "a background blip must not rival an answer cue"
    assert blip > stop - 9.0, (
        f"the blip is {stop - blip:.1f} dB below the stop cue; past about "
        "9 it stops being heard at all"
    )


def test_no_cue_is_shorter_than_the_ear_can_register():
    """Below ~60 ms a tone is heard as a click of indeterminate pitch, and
    these cues are told apart by pitch."""
    for name, steps in (("stop", audio._STOP_CUE),
                        ("busy", audio._BUSY_CUE),
                        ("waiting", audio._WAITING_TICK)):
        for _frequency, seconds in steps:
            assert seconds >= 0.06, f"{name}: a {seconds * 1000:.0f} ms tone is a click"


def test_the_falling_chime_is_longer_than_the_rising_one(fake_sd, fake_sf):
    """The rising chime is a "go" and delays the user speaking; the falling
    one is a "got it" with nothing waiting on it, and at 120 ms it was
    heard as truncated."""
    pytest.importorskip("numpy")

    audio.play_chime(rising=True)
    rising = sum(fake_sd.streams[-1].blocks)

    audio.play_chime(rising=False)
    falling = sum(fake_sd.streams[-1].blocks)

    assert falling > rising * 1.5, (
        f"falling {falling} frames vs rising {rising} — not distinguishable"
    )


def test_an_explicit_chime_duration_still_wins(fake_sd, fake_sf):
    """The per-direction defaults must not take the override away — the
    manual cue test and the latency bench both set it."""
    pytest.importorskip("numpy")

    audio.play_chime(rising=False, duration_s=0.05)

    assert sum(fake_sd.streams[-1].blocks) == int(22050 * 0.05)


def test_the_two_single_tone_cues_are_kept_apart():
    """The busy cue and the waiting blip are the only one-tone cues, so
    they have nothing but pitch and length to separate them.

    This pairing is new. The busy cue was two 60 ms beeps and collided
    with the stop cue instead — identical rhythm, and at 60 ms the pitch
    contour that was supposed to distinguish them was not audible. Moving
    it to a single buzz fixed that collision and created this one.
    """
    import math

    if len(audio._BUSY_CUE) != 1 or len(audio._WAITING_TICK) != 1:
        pytest.skip("not both single tones — told apart by count instead")

    (busy_hz, busy_s), = audio._BUSY_CUE
    (blip_hz, blip_s), = audio._WAITING_TICK

    octaves = abs(math.log2(busy_hz / blip_hz))
    assert octaves >= 1.0, (
        f"{busy_hz:.0f} Hz and {blip_hz:.0f} Hz are {octaves:.2f} octaves "
        "apart — too close for two cues with the same shape"
    )

    longer, shorter = max(busy_s, blip_s), min(busy_s, blip_s)
    assert longer / shorter >= 1.8, (
        f"{busy_s * 1000:.0f} ms and {blip_s * 1000:.0f} ms are too alike in "
        "length to help tell them apart"
    )


def test_no_two_cues_share_a_tone_count_and_a_pitch():
    """Rhythm is what the ear reads first on sounds this short, so two
    cues with the same number of tones must differ clearly in pitch —
    that is exactly what the old busy cue got wrong against the stop cue.
    """
    import math

    cues = {
        "stop": audio._STOP_CUE,
        "busy": audio._BUSY_CUE,
        "waiting": audio._WAITING_TICK,
    }
    names = sorted(cues)
    for i, first in enumerate(names):
        for second in names[i + 1:]:
            a, b = cues[first], cues[second]
            if len(a) != len(b):
                continue                 # told apart by count alone
            gap = min(abs(math.log2(fa / fb))
                      for (fa, _), (fb, _) in zip(a, b))
            assert gap >= 1.0, (
                f"{first} and {second} have {len(a)} tone(s) each and are "
                f"only {gap:.2f} octaves apart"
            )
