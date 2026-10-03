"""Live audio capture and playback for the voice layer.

Wraps `sounddevice` (PortAudio) for I/O and `soundfile` (libsndfile) for WAV
serialisation. Uses the operating system's *default* input and output devices
— on the Pi that means whichever PipeWire currently designates as default,
so which headset or speaker is in use is an OS-level concern, not a Python
concern.

Both `record` and `play` are blocking. Callers that need concurrency (e.g. a
polling loop that must keep reading sensors while audio plays) should invoke
them from a separate thread.

Thread safety
-------------
Every function here creates its own `sounddevice` stream and is the only
thing that ever closes it. None of them use the module-level `sd.play`,
`sd.rec` or `sd.stop`.

That rule exists because ignoring it crashed the wearable. `sounddevice`
keeps *one* global playback context: `sd.play()` begins by calling the
global `sd.stop()`, which stops **and closes** whatever stream that global
currently points at, and `sd.stop()` does the same when called directly.
Three of our threads reach playback — the announcer, a voice thread, and
gpiozero's button callbacks — so a PTT chime could close the announcer's
live stream, leaving the announcer to close the same PortAudio stream a
second time on its way out. That is a double free in C, and it aborted the
process: `double free or corruption (out)`.

A lock alone would not have fixed it, because `stop_playback` has to
interrupt a thread that holds the lock. Owning the stream does: playback is
serialised by `_playback_lock`, and stopping is a flag the *playing* thread
reads, not a call another thread makes into PortAudio. No thread can close a
stream it did not open, by construction rather than by discipline.
"""
import sys
import threading
from pathlib import Path

DEFAULT_SAMPLERATE_HZ = 16000   # Whisper expects 16 kHz mono; Piper output is resampled at playback time

# Frames per `write` call. This is the granularity at which playback notices
# `stop_playback`, so it sets the stop latency: 512 frames is ~23 ms at
# 22050 Hz, far below what anyone perceives as a delay when they ask the
# wearable to be quiet. Smaller would risk under-runs (audible clicks) for
# no benefit the user could hear.
_BLOCK_FRAMES = 512

# Serialises playback. Two concurrent output streams on one device do not
# crash — they talk over each other, which for this wearable is the same
# failure the announcer exists to prevent. Held for the length of an
# utterance, so callers queue rather than overlap.
_playback_lock = threading.Lock()

# Set by `stop_playback`, read by whichever thread is inside the write loop.
# Cleared at the start of each playback so a stale request cannot silence
# the next utterance.
_stop_requested = threading.Event()

# Set while `play` has speech on the speaker. Tracked here rather than asked
# of PortAudio because `sounddevice` exposes no reliable "is anything
# playing" query, and every speaker in the system already goes through
# `play` — the announcer worker, the voice pipeline, and the button
# handlers. One flag therefore covers all of them.
#
# Deliberately NOT set by `play_chime`: a chime is ~120 ms of
# acknowledgement tone, and counting it as "speaking" would make a
# stop-talking press land on nothing during the gap after a PTT press.
_playing = threading.Event()


# --- PortAudio has to be re-initialised immediately before every stream ------
#
# A short sound only plays if `Pa_Initialize` ran *just* before the stream
# that carries it. Let a few seconds pass between the two and the stream
# silently discards roughly its first 0.8 s — which erases a 0.2 s cue
# completely while merely clipping a 1 s tone, and that is why speech
# always worked and the acknowledgement cues never did.
#
# The evidence, all measured on the device rather than reasoned about:
#
#     one process, 3 s apart     short #1 audible, #2 SILENT, #3 SILENT
#     five separate processes    audible 5/5
#     `aplay`, 3 s apart         audible every time
#     0.3 s after a long tone    audible
#     re-init, then open at once audible every time
#     re-init, then open 3 s on  SILENT
#
# The first four were originally read as "only the first stream of a
# process works", and a fix built on that — re-initialising when a stream
# *closed*, so the cost fell between sounds instead of in front of them —
# tested green in units and failed immediately on the device. That last
# pair is what the ordinal theory cannot explain and the elapsed-time one
# can: in every working case `Pa_Initialize` and the stream are adjacent.
# Import-then-play is adjacent, which is why a fresh process looks like a
# "first stream" effect.
#
# What decays in between is still unidentified — PortAudio's cached ALSA
# configuration, the PipeWire node, or the headset's own amplifier. So
# this is an empirically determined remedy, not a root-cause fix, and a
# PipeWire or kernel update could make it redundant or insufficient.
# `deploy/pipewire/51-no-suspend.conf` was an earlier attempt at the same
# symptom from the suspension angle and did not resolve it.
#
# The cost is real and unavoidable: **96 ms on the Pi** (2 ms on a Mac),
# because a re-init re-enumerates every ALSA device. It cannot be moved
# off the critical path, because being on the critical path is precisely
# what makes it work.
#
# Guarded by a stream count, and that guard is the important part.
# Terminating PortAudio while any stream is live — including the
# microphone's `InputStream` during a recording — is the same C-level
# double free that `sd.play` caused, and the overlap is real: pressing
# repeat mid-recording plays the stop cue while `record_until_button`
# still holds its input stream. So the count covers input and output
# alike, and when anything is open the re-init is skipped: a clipped cue
# is a poor outcome, a segfault is not one at all.
_portaudio_lock = threading.Lock()
_portaudio_streams = 0


# Bound on the unwind loop below. PortAudio's init count should never be
# above 1 here, so anything past a couple of passes means the counter is
# not behaving as documented and looping harder will not help.
_MAX_TERMINATE_PASSES = 4


def _reinitialise_portaudio() -> bool:
    """Restore the first-stream-of-a-process condition. Never raises.

    Reports whether PortAudio is up afterwards, so a caller can tell a
    refreshed context from a dead one.

    Caller must hold `_portaudio_lock` and must have verified that no
    stream is open. Uses `sounddevice`'s private `_terminate`/`_initialize`
    because PortAudio exposes no public way to do this and nothing else
    makes a second short sound audible.

    The target is a single invariant: **`sd._initialized == 1` on exit**.

    `Pa_Initialize`/`Pa_Terminate` are *reference counted* — PortAudio
    only really shuts down when the count reaches zero — and sounddevice
    mirrors that count in `sd._initialized`. Aiming at the invariant
    rather than issuing a fixed pair of calls is what makes this safe in
    the three states that actually occur, all found by experiment:

      * **Count 1**, the normal case: one teardown, one initialise.

      * **Count 0**, after a failed `Pa_Initialize` — a USB
        re-enumeration can cause one. Tearing down again raises
        `paNotInitialized`, so the obvious `try: terminate(); initialize()`
        skips the initialise and leaves the library down *for good*: every
        later stream dies with `Error querying device -1` and the wearable
        is mute until it is restarted. Here the teardown is simply skipped
        and the initialise brings it back.

      * **Count above 1**: a single teardown would shut nothing down and
        the re-init would silently stop working, the only symptom being
        the cues going quiet again. The loop unwinds it.

    A teardown that fails while the count is still positive leaves the
    initialise alone deliberately — raising it would push the count up
    instead, and the drift is unbounded across calls.
    """
    import sounddevice as sd

    # `_initialized` is private too. Without it the count cannot be
    # managed at all, so fall back to one best-effort pair.
    if not isinstance(getattr(sd, "_initialized", None), int):
        try:
            sd._terminate()
        except Exception:
            pass                        # already down; the initialise matters
        try:
            sd._initialize()
        except Exception as exc:
            print(f"[audio] PortAudio is down and could not be restarted: {exc}",
                  file=sys.stderr, flush=True)
            return False
        return True

    for _ in range(_MAX_TERMINATE_PASSES):
        if sd._initialized <= 0:
            break
        try:
            sd._terminate()
        except Exception as exc:
            print(f"[audio] PortAudio teardown failed: {exc}",
                  file=sys.stderr, flush=True)
            break

    if sd._initialized <= 0:
        try:
            sd._initialize()
        except Exception as exc:
            # The library IS down and every stream will now fail. Say so
            # plainly; the next sound retries from the top.
            print(f"[audio] PortAudio is down and could not be restarted: {exc}",
                  file=sys.stderr, flush=True)
            return False

    return sd._initialized == 1


def _claim_portaudio(refresh: bool = True) -> None:
    """Register a stream about to open, re-initialising PortAudio first.

    `refresh=False` registers the stream without re-initialising. Used by
    the three recording functions: **input is not affected by the
    discard**, measured on the Pi with `mic_onset_test` — three trials
    per condition, 2 s each, and a stream opened with no re-init captured
    2.004 s of a 2.000 s recording, identical to one opened with. Only
    short *output* needs the adjacency.

    Recording still takes part in the count, which is the half that
    matters for safety: it stops a cue on another thread tearing PortAudio
    down while the microphone is live. It simply no longer pays ~69 ms to
    refresh a context it does not need, and that 69 ms sat between the
    PTT chime ending and the microphone going live — dead time the user
    may already be speaking into.

    Called immediately before the stream is constructed, never after:
    `Pa_Terminate` invalidates every existing stream pointer, so a stream
    built first and claimed second dies on `start()` with
    `Invalid stream pointer`.

    Unconditional when nothing else is open, including for the very first
    sound of the process. Importing sounddevice does initialise PortAudio,
    but startup then spends 30-60 s loading Whisper, Piper and the NLU
    model before anything speaks — by which point that initialisation is
    exactly as stale as any other.
    """
    global _portaudio_streams
    with _portaudio_lock:
        if refresh and _portaudio_streams == 0:
            _reinitialise_portaudio()
        _portaudio_streams += 1


def _release_portaudio() -> None:
    """Register a stream that has closed.

    Deliberately does no work. Re-initialising here instead — so the 96 ms
    falls between sounds rather than in front of them — was tried, passed
    every unit test, and silenced the cues on the device: by the time the
    next sound arrives the context has gone stale again.
    """
    global _portaudio_streams
    with _portaudio_lock:
        _portaudio_streams = max(0, _portaudio_streams - 1)



def is_playing() -> bool:
    """True while speech is on the speaker.

    Lets a button handler tell "stop talking" from "repeat" without
    knowing which subsystem started the audio.
    """
    return _playing.is_set()


def record(
    duration_s: float,
    output_path: Path,
    samplerate: int = DEFAULT_SAMPLERATE_HZ,
    channels: int = 1,
) -> None:
    """Record for `duration_s` seconds and save as a WAV file.

    Records into a numpy int16 array from the default input device, then
    writes as 16-bit PCM WAV. This matches what faster-whisper prefers for
    input.

    Reads an owned `InputStream` rather than calling `sd.rec`, which routes
    through the same module-level context `sd.play` does — recording would
    then close a stream the speaker was still using. The two sibling
    recorders below already worked this way; this one was the last caller of
    sounddevice's global state.
    """
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    output_path.parent.mkdir(parents=True, exist_ok=True)
    remaining = int(duration_s * samplerate)
    blocks: list = []

    # Counted so a cue played on another thread cannot re-initialise
    # PortAudio out from under a live recording. No refresh: input does
    # not suffer the discard that short output does, measured rather than
    # assumed — see `_claim_portaudio`.
    _claim_portaudio(refresh=False)
    try:
        stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            blocksize=_BLOCK_FRAMES,
        )
        with stream:
            while remaining > 0:
                data, _overflowed = stream.read(min(_BLOCK_FRAMES, remaining))
                blocks.append(data.copy())
                remaining -= len(data)
    finally:
        _release_portaudio()

    audio = np.concatenate(blocks, axis=0)
    sf.write(str(output_path), audio, samplerate, subtype="PCM_16")


def record_until_enter(
    output_path: Path,
    samplerate: int = DEFAULT_SAMPLERATE_HZ,
    channels: int = 1,
    max_duration_s: float = 60.0,
) -> float:
    """Record until the user presses Enter (or `max_duration_s` elapses).

    Push-to-talk style: the user calls this after pressing Enter to start,
    then presses Enter again to stop. Returns the duration recorded in
    seconds. Uses a `sounddevice.InputStream` with a callback so we can
    accumulate frames while `input()` blocks waiting for the next Enter.

    Fails safe on empty capture (writes a short silent WAV) so downstream
    code doesn't have to special-case zero-frame files.
    """
    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames: list[np.ndarray] = []

    def _callback(indata, _frame_count, _time_info, _status):
        frames.append(indata.copy())

    # Counted but not refreshed — input is unaffected by the discard
    # that silences short output. See `_claim_portaudio`.
    _claim_portaudio(refresh=False)
    try:
        stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            callback=_callback,
        )
        with stream:
            # input() blocks until Enter; the callback keeps filling `frames`.
            input("  (recording — press Enter to stop) ")
    finally:
        _release_portaudio()

    if not frames:
        # Write ~0.1 s of silence so downstream code has a valid WAV to open.
        sf.write(
            str(output_path),
            np.zeros(int(0.1 * samplerate), dtype="int16"),
            samplerate,
            subtype="PCM_16",
        )
        return 0.0

    audio = np.concatenate(frames, axis=0)
    duration_s = len(audio) / samplerate
    if duration_s > max_duration_s:
        audio = audio[: int(max_duration_s * samplerate)]
        duration_s = max_duration_s
    sf.write(str(output_path), audio, samplerate, subtype="PCM_16")
    return duration_s


def record_until_button(
    button,
    output_path: Path,
    samplerate: int = DEFAULT_SAMPLERATE_HZ,
    channels: int = 1,
    max_duration_s: float = 60.0,
    cancel_event=None,
) -> float:
    """Record until the user presses the given `button` (or `max_duration_s`
    elapses, or `cancel_event` is set by another thread).

    Same behaviour as `record_until_enter` but the stop signal comes from
    a physical button press instead of Enter on stdin.

    `cancel_event` — optional `threading.Event`. When set from any thread,
    the recording aborts immediately. Used by the wearable's emergency
    button to preempt a PTT recording: the emergency callback sets the
    event, this function returns, and the caller checks `cancel_event`
    afterwards to decide whether to skip the rest of the pipeline.

    The `button` argument is any object satisfying the `feedback.Button`
    protocol — real `GPIOButton` on the Pi or `MockButton` for tests.
    """
    import threading
    import time

    import numpy as np
    import sounddevice as sd
    import soundfile as sf

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames: list[np.ndarray] = []
    stop_event = threading.Event()

    def _audio_callback(indata, _frame_count, _time_info, _status):
        frames.append(indata.copy())

    def _on_press():
        stop_event.set()

    button.on("pressed", _on_press)

    # Counted but not refreshed — input is unaffected by the discard
    # that silences short output. See `_claim_portaudio`.
    _claim_portaudio(refresh=False)
    try:
        stream = sd.InputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            callback=_audio_callback,
        )
        with stream:
            # Poll both stop_event (button press) and cancel_event (external
            # abort like the emergency button) on a short interval. 50 ms is
            # imperceptible latency for the user but fine-grained enough that
            # an emergency preemption feels instant.
            deadline = time.monotonic() + max_duration_s
            while time.monotonic() < deadline:
                if stop_event.wait(timeout=0.05):
                    break
                if cancel_event is not None and cancel_event.is_set():
                    break
    finally:
        _release_portaudio()

    if not frames:
        sf.write(
            str(output_path),
            np.zeros(int(0.1 * samplerate), dtype="int16"),
            samplerate,
            subtype="PCM_16",
        )
        return 0.0

    audio = np.concatenate(frames, axis=0)
    duration_s = len(audio) / samplerate
    if duration_s > max_duration_s:
        audio = audio[: int(max_duration_s * samplerate)]
        duration_s = max_duration_s
    sf.write(str(output_path), audio, samplerate, subtype="PCM_16")
    return duration_s


def wait_for_button_press(button, prompt: str | None = None) -> None:
    """Block until the given `button` fires a `pressed` event.

    Uses the same protocol-shaped `Button` as `record_until_button`. Prints
    `prompt` before waiting if provided.
    """
    import threading

    if prompt:
        print(prompt, flush=True)

    got_press = threading.Event()
    button.on("pressed", got_press.set)
    got_press.wait()


def _write_blocks(audio, samplerate: int) -> None:
    """Push an audio array to the speaker, one block at a time.

    The whole of this module's output path. The stream is created, written
    and closed inside this one function, which is what makes the ownership
    rule in the module docstring true: nothing else holds a reference to it.

    `audio` is 2-D, `(frames, channels)` — `always_2d=True` on the read side
    and an explicit reshape for the chime, so the channel count is something
    we read off the data rather than assume.

    Checks `_stop_requested` between blocks and `abort()`s rather than
    `stop()`s on the way out: `stop()` drains the buffer, which would keep
    talking for a few dozen milliseconds after the user asked for silence.

    Writes the caller's audio and nothing else. A previous version opened
    with 0.2 s of silence, on the theory that the stream's first blocks
    were lost to a start-up underrun. They are not: `audio_probe` showed
    the stream negotiating the right rate and consuming 1.0 s of audio in
    0.96 s on every attempt, first or fiftieth. What actually swallowed
    short sounds was PipeWire resuming a suspended device — fixed in
    `deploy/pipewire/`, not here. The padding only moved the sound later
    into a window that was already being discarded, which made it worse.
    """
    import sounddevice as sd

    channels = audio.shape[1]
    # Claimed BEFORE the stream is constructed. `Pa_Terminate` invalidates
    # every existing stream pointer, so a stream built first and claimed
    # second fails to start with `Invalid stream pointer`.
    _claim_portaudio()
    try:
        stream = sd.OutputStream(
            samplerate=samplerate,
            channels=channels,
            dtype="float32",
            blocksize=_BLOCK_FRAMES,
        )
        # `with` starts the stream and closes it exactly once, on every
        # exit path including an exception. That single close is the
        # invariant the old `sd.play` global broke.
        with stream:
            for start in range(0, len(audio), _BLOCK_FRAMES):
                if _stop_requested.is_set():
                    stream.abort()
                    return
                stream.write(audio[start:start + _BLOCK_FRAMES])
    finally:
        _release_portaudio()


def play(audio_path: Path) -> None:
    """Play a WAV file through the default output device.

    Reads the file's actual sample rate (Piper voices are 22050 Hz, MMS
    16000 Hz) and plays at it, so nothing has to resample.

    Blocking, and serialised against every other caller: if the announcer is
    mid-sentence, a second `play` waits rather than cutting it off.
    """
    import soundfile as sf

    # Read outside the lock — file I/O doesn't need serialising, and holding
    # the lock across it would make every queued utterance wait on a disk read.
    audio, samplerate = sf.read(str(audio_path), dtype="float32", always_2d=True)

    with _playback_lock:
        _stop_requested.clear()
        _playing.set()
        try:
            _write_blocks(audio, samplerate)
        finally:
            # Cleared even when `stop_playback` cut us short, so a truncated
            # announcement doesn't leave the wearable believing it is still
            # talking — every later stop press would then be swallowed.
            _playing.clear()


def stop_playback() -> None:
    """Cut short whatever is currently playing, from any thread.

    Sets a flag; the thread inside `_write_blocks` sees it at the next block
    boundary (~23 ms) and aborts its own stream. That indirection is the
    whole point — see the module docstring. Calling into PortAudio from here
    is what produced the double free, because the playing thread would then
    close a stream this one had already closed.

    Only affects playback already in progress. Anything queued behind the
    lock starts fresh, and dropping *pending* speech is the announcer's job
    (`Announcer.clear`), not this function's.

    Safe to call when nothing is playing: the flag is cleared by the next
    playback before it writes anything. Cannot raise — it touches no audio
    library at all, which is also why it works unchanged on a dev machine
    with no audio stack installed.
    """
    _stop_requested.set()


def _tone(
    frequency_hz: float,
    duration_s: float,
    samplerate: int,
    amplitude: float = 0.3,
):
    """One fixed-pitch tone with the edges faded, as a float32 array.

    The fade is not decoration. A sine cut off mid-cycle steps the speaker
    cone discontinuously, which is heard as a click — and a cue made of
    clicks is indistinguishable from a loose connection on a device the
    user cannot look at.
    """
    import numpy as np

    n_samples = int(samplerate * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)
    wave = amplitude * np.sin(2.0 * np.pi * frequency_hz * t)

    fade = int(0.008 * samplerate)
    if fade > 0 and n_samples > 2 * fade:
        wave[:fade] *= np.linspace(0.0, 1.0, fade)
        wave[-fade:] *= np.linspace(1.0, 0.0, fade)
    return wave.astype(np.float32)


def play_cue(
    steps: list[tuple[float, float]],
    gap_s: float = 0.03,
    amplitude: float = 0.3,
) -> None:
    """Play a sequence of `(frequency_hz, duration_s)` tones as one cue.

    Distinct from `play_chime`, which sweeps continuously between two
    pitches. A cue built from *separate* tones is heard as a pattern
    rather than a slide, and pattern is what the ear uses to tell short
    sounds apart — the wearer has to identify these without seeing
    anything, and two similar sweeps would blur together.

    Takes the same playback lock as everything else here and generates
    its own audio, so it is safe from any thread.
    """
    import numpy as np

    samplerate = 22050
    silence = np.zeros(int(gap_s * samplerate), dtype="float32")

    parts: list = []
    for frequency_hz, duration_s in steps:
        if parts:
            parts.append(silence)
        parts.append(_tone(frequency_hz, duration_s, samplerate, amplitude))
    if not parts:
        return

    audio = np.concatenate(parts).reshape(-1, 1)
    with _playback_lock:
        _stop_requested.clear()
        # Like `play_chime`, deliberately does not set `_playing`: a cue is
        # an acknowledgement, not speech, and counting it as speech would
        # make the very next stop press land on nothing.
        _write_blocks(audio, samplerate)


# Two falling tones — the shape of something being put down. Says "I
# stopped" after a press that interrupted speech. Deliberately NOT the
# falling `play_chime` sweep, which already means "recording ended": the
# two happen seconds apart in the same session and the wearer has no
# screen to disambiguate them.
_STOP_CUE = [(660.0, 0.07), (440.0, 0.10)]

# One long low buzz. Says the press was heard and refused, which is the
# thing a silently-ignored button cannot say — and a button that appears
# to do nothing reads as broken hardware.
#
# This was two flat 60 ms beeps at 350 Hz, chosen for the telephone
# busy-signal convention, and it was reported as indistinguishable from
# the stop cue. The reason was not pitch: flat-350 against falling-660-to-
# 440 is a large difference written down, but both were two short beeps
# 30 ms apart, and at 60 ms a tone barely has a pitch to hear at all.
# Rhythm and count are what the ear uses at this duration, and on those
# the two cues were identical. Chosen by ear from five candidates in
# `busy_cue_audition`, all of which varied rhythm rather than frequency.
#
# Being a single tone, it shares a shape with the waiting blip rather
# than with the other cues, so those two are what must now be kept apart.
# They are, on three axes at once: 200 Hz against 520 is nearly an octave
# and a half, 280 ms against 120 is over twice as long, and the blip
# recurs every 1.2 s while this is heard once. `test_cue_design` pins the
# first two; the third is a property of the caller, not the sound.
_BUSY_CUE = [(200.0, 0.28)]


def play_stop_cue() -> None:
    """Acknowledge a press that interrupted speech or a voice command."""
    play_cue(_STOP_CUE)


def play_busy_cue() -> None:
    """Tell the user a press was heard but cannot be acted on right now."""
    play_cue(_BUSY_CUE)


# A single soft blip, repeated by the caller while the device is working.
# Quieter and shorter than the cues above on purpose: those are answers to
# a press and are heard once, this one recurs for several seconds and is
# background. At 0.3 amplitude it reads as the device beeping AT you.
#
# It was originally 45 ms at 0.12 and was completely inaudible on the
# headset, which read as a bug and was not one — it was specified too
# small to hear. The ear integrates loudness over roughly 200 ms, so a
# tone shorter than that is perceived quieter in proportion to its
# length, on top of whatever its amplitude says. Against the 200 ms stop
# cue that put it about 6 dB down on duration and another 8 dB down on
# amplitude: ~14 dB, which is not "quieter" but gone. Worse, `_tone`
# fades 8 ms at each end, so 16 of those 45 ms were ramp.
#
# 120 ms at 0.26 lands ~3.5 dB under the stop cue: still audibly the
# quieter of the two, which is the design intent, but comfortably present
# on the headset. 0.18 was tried first and was clearly audible in the cue
# test yet still too faint in use, so this is a second step up rather than
# a guess. Keep both numbers in mind when tuning — halving the duration
# costs as much as halving the amplitude.
#
# Going much past this makes it rival the cues that answer a press, and a
# background sound that is as loud as an answer stops reading as
# background: the wearer starts attending to it every 1.2 s.
_WAITING_TICK = [(520.0, 0.12)]
_WAITING_AMPLITUDE = 0.26


def play_waiting_tick() -> None:
    """One blip of the "still working on it" pattern.

    Deliberately a single short blip the caller repeats, not a continuous
    tone it would have to interrupt. `play` holds `_playback_lock` for a
    whole utterance, so a sustained waiting sound would make the answer —
    and any obstacle warning — queue behind it. One blip holds the lock
    for 120 ms out of every 1.2 s and leaves it free the rest of the
    time.""" 
    play_cue(_WAITING_TICK, amplitude=_WAITING_AMPLITUDE)


# The two chimes are deliberately different lengths.
#
# The rising one is a "go" — it has to get out of the way so the user can
# start talking, and every millisecond of it is a millisecond they are
# waiting to speak. The falling one is a "got it", played after the
# recording has already ended, so nothing is waiting on it; at 120 ms it
# was heard as a clipped blip rather than a resolution, and a sound that
# reads as truncated reads as a fault on a device the user cannot see.
_RISING_CHIME_S = 0.12
_FALLING_CHIME_S = 0.24


def play_chime(rising: bool = True, duration_s: float | None = None) -> None:
    """Play a short synthesized chime as an audio button-press acknowledgment.

    Generated on-the-fly with numpy — no WAV files needed. A rising tone
    (500 → 900 Hz sweep) marks recording start; a falling tone (900 → 500 Hz)
    marks recording end. Modeled after voice-assistant conventions (Siri,
    Google, Alexa all use rising-then-falling to bracket their listening
    windows).

    Short fade-in / fade-out avoids clicks at the boundaries. Amplitude
    is deliberately kept at 30% peak so the chime is noticeable but not
    startling.

    Blocking. `duration_s` defaults per direction — 120 ms rising, 240 ms
    falling; see the constants above for why they differ. Cheap to
    generate (<10 ms of CPU). Takes the same playback lock as `play`: the
    chime runs on gpiozero's button callback thread, and it overlapping
    the announcer is precisely what crashed the wearable before the stream
    became ours.
    """
    import numpy as np

    if duration_s is None:
        duration_s = _RISING_CHIME_S if rising else _FALLING_CHIME_S

    samplerate = 22050
    n_samples = int(samplerate * duration_s)
    t = np.linspace(0, duration_s, n_samples, endpoint=False)

    if rising:
        freqs = np.linspace(500.0, 900.0, n_samples)
    else:
        freqs = np.linspace(900.0, 500.0, n_samples)

    # Instantaneous phase = cumulative integral of angular frequency.
    phase = 2.0 * np.pi * np.cumsum(freqs) / samplerate
    wave = 0.3 * np.sin(phase)

    # 10 ms fade in/out to eliminate the click artifact at the edges.
    fade_samples = int(0.01 * samplerate)
    if fade_samples > 0 and n_samples > 2 * fade_samples:
        wave[:fade_samples] *= np.linspace(0.0, 1.0, fade_samples)
        wave[-fade_samples:] *= np.linspace(1.0, 0.0, fade_samples)

    # Mono, but shaped (frames, 1) — `_write_blocks` reads the channel count
    # off the array rather than assuming one.
    audio = wave.astype(np.float32).reshape(-1, 1)

    with _playback_lock:
        _stop_requested.clear()
        # Deliberately does not set `_playing` — see the comment on that flag.
        _write_blocks(audio, samplerate)
