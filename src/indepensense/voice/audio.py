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


# --- PortAudio has to be re-initialised between streams ----------------------
#
# Only the FIRST stream of a process plays a short sound. Every stream
# after it silently discards roughly its first 0.8 s, so a 0.2 s cue
# vanishes entirely while a 1 s tone is merely clipped — which is why
# speech always worked and the acknowledgement cues never did.
#
# Measured on the device, all within one process:
#
#     short #1   audible        long tone   audible
#     short #2   SILENT         short #3    SILENT
#
# and the same cue played by a fresh `python -c` each time — five
# processes — was audible five times out of five. `aplay` likewise. The
# device was never at fault, and neither was PipeWire: `blocksize`,
# `latency`, an explicit `stop()` before close, and `sd.play()` itself
# all failed identically.
#
# `Pa_Terminate()` + `Pa_Initialize()` restores whatever state the first
# stream of a process enjoys, and short sounds play every time.
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


def _reinitialise_portaudio() -> None:
    """Restore the first-stream-of-a-process condition. Never raises.

    Caller must hold `_portaudio_lock` and must have verified that no
    stream is open. Uses `sounddevice`'s private `_terminate`/`_initialize`
    because PortAudio exposes no public way to do this and nothing else
    makes a second short sound audible.

    `Pa_Initialize`/`Pa_Terminate` are *reference counted* — PortAudio
    only really shuts down when the count reaches zero — and sounddevice
    mirrors the count in `sd._initialized`. Two consequences shape this
    function, and both were found by experiment rather than reading:

      * The count must be driven to zero or nothing is torn down and the
        re-init silently does nothing. Importing sounddevice leaves it at
        1, so normally that is a single `_terminate()`; the loop is there
        because an unbalanced count would otherwise disable the fix for
        the rest of the run with no symptom but the cues going quiet.

      * `_initialize()` must be attempted *unconditionally*. Calling
        `_terminate()` on an already-terminated PortAudio raises
        `paNotInitialized`, so the obvious `try: terminate(); initialize()`
        skips the initialise and leaves the library terminated for good —
        every later stream then dies with `Error querying device -1` and
        the wearable is silent until it is restarted. A transient
        `Pa_Initialize` failure, which a USB re-enumeration can cause, was
        enough to reach that state permanently.
    """
    import sounddevice as sd

    # `_initialized` is private too. Absent it, fall back to one pass:
    # the count is 1 in every case we can actually observe.
    passes = getattr(sd, "_initialized", 1)
    if not isinstance(passes, int) or passes < 0:
        passes = 1

    for _ in range(min(passes, _MAX_TERMINATE_PASSES)):
        try:
            sd._terminate()
        except Exception as exc:
            # Already down, which is fine — the initialise below is what
            # actually matters.
            print(f"[audio] PortAudio teardown skipped: {exc}",
                  file=sys.stderr, flush=True)
            break

    try:
        sd._initialize()
    except Exception as exc:
        # Now the library IS terminated and every stream will fail. Say so
        # plainly: this is the one path where the device goes silent, and
        # the next sound retries from the top.
        print(f"[audio] PortAudio is down and could not be restarted: {exc}",
              file=sys.stderr, flush=True)


def _claim_portaudio() -> None:
    """Register a stream about to open, re-initialising if it is the only one."""
    global _portaudio_streams
    with _portaudio_lock:
        if _portaudio_streams == 0:
            _reinitialise_portaudio()
        _portaudio_streams += 1


def _release_portaudio() -> None:
    """Register a stream that has closed."""
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
    # PortAudio out from under a live recording — and claimed before the
    # stream exists, since a re-init invalidates existing pointers.
    _claim_portaudio()
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

    _claim_portaudio()
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

    _claim_portaudio()
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

# Two flat low beeps, the convention for "not now" since the telephone
# busy signal. Says the press was heard and refused, which is the thing a
# silently-ignored button cannot say — and a button that appears to do
# nothing reads as broken hardware.
_BUSY_CUE = [(350.0, 0.06), (350.0, 0.06)]


def play_stop_cue() -> None:
    """Acknowledge a press that interrupted speech or a voice command."""
    play_cue(_STOP_CUE)


def play_busy_cue() -> None:
    """Tell the user a press was heard but cannot be acted on right now."""
    play_cue(_BUSY_CUE)


# A single soft blip, repeated by the caller while the device is working.
# Quieter and shorter than the cues above on purpose: those are answers to
# a press and are heard once, this one recurs for several seconds and is
# background. At 0.3 amplitude it reads as the device beeping AT you; at
# 0.12 it reads as the device being busy.
_WAITING_TICK = [(520.0, 0.045)]
_WAITING_AMPLITUDE = 0.12


def play_waiting_tick() -> None:
    """One blip of the "still working on it" pattern.

    Deliberately a single short blip the caller repeats, not a continuous
    tone it would have to interrupt. `play` holds `_playback_lock` for a
    whole utterance, so a sustained waiting sound would make the answer —
    and any obstacle warning — queue behind it. One blip holds the lock
    for 45 ms and leaves it free the rest of the time.""" 
    play_cue(_WAITING_TICK, amplitude=_WAITING_AMPLITUDE)


def play_chime(rising: bool = True, duration_s: float = 0.12) -> None:
    """Play a short synthesized chime as an audio button-press acknowledgment.

    Generated on-the-fly with numpy — no WAV files needed. A rising tone
    (500 → 900 Hz sweep) marks recording start; a falling tone (900 → 500 Hz)
    marks recording end. Modeled after voice-assistant conventions (Siri,
    Google, Alexa all use rising-then-falling to bracket their listening
    windows).

    Short fade-in / fade-out avoids clicks at the boundaries. Amplitude
    is deliberately kept at 30% peak so the chime is noticeable but not
    startling.

    Blocking, ~120 ms by default. Cheap to generate (<10 ms of CPU). Takes
    the same playback lock as `play`: the chime runs on gpiozero's button
    callback thread, and it overlapping the announcer is precisely what
    crashed the wearable before the stream became ours.
    """
    import numpy as np

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
