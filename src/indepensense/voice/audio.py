"""Live audio capture and playback for the voice layer.

Wraps `sounddevice` (PortAudio) for I/O and `soundfile` (libsndfile) for WAV
serialisation. Uses the operating system's *default* input and output devices
— on the Pi that means whichever PipeWire currently designates as default,
so switching between built-in audio, a USB headset, or paired Bluetooth
headphones (AirPods) is an OS-level concern, not a Python concern.

Both `record` and `play` are blocking. Callers that need concurrency (e.g. a
polling loop that must keep reading sensors while audio plays) should invoke
them from a separate thread.
"""
from pathlib import Path

DEFAULT_SAMPLERATE_HZ = 16000   # Whisper expects 16 kHz mono; Piper output is resampled at playback time


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
    """
    import sounddevice as sd
    import soundfile as sf

    output_path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(duration_s * samplerate)
    audio = sd.rec(
        frames,
        samplerate=samplerate,
        channels=channels,
        dtype="int16",
        blocking=True,
    )
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

    stream = sd.InputStream(
        samplerate=samplerate,
        channels=channels,
        dtype="int16",
        callback=_callback,
    )
    with stream:
        # input() blocks until Enter; the callback keeps filling `frames`.
        input("  (recording — press Enter to stop) ")

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


def play(audio_path: Path) -> None:
    """Play a WAV file through the default output device.

    Reads the file's actual sample rate (Piper voices are typically 22050 Hz)
    and hands both the array and rate to sounddevice so it doesn't need to
    resample.
    """
    import sounddevice as sd
    import soundfile as sf

    audio, samplerate = sf.read(str(audio_path))
    sd.play(audio, samplerate=samplerate, blocking=True)
