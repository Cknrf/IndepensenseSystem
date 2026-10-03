"""Manual test: does the microphone lose its opening the way the speaker did?

Short *output* sounds on this device are silently discarded unless
`Pa_Initialize` ran immediately beforehand — see the comment block in
`voice/audio.py`. The remedy costs about 96 ms per stream on the Pi, and
`_claim_portaudio` applies it to recording as well as playback.

Whether recording *needs* it has never been established, and it matters
in a way the user can hear. A push-to-talk press runs:

    chime  ->  [96 ms re-init]  ->  microphone live

so if the re-init is unnecessary on the input side, the first tenth of a
second of every command is being thrown away for nothing. "Oras" losing
its first syllable is "ras", which Whisper will not recover.

What this measures
------------------

An input stream records for a fixed duration and the captured frames are
counted. Audio arrives at a known rate, so captured seconds should equal
the recording duration; whatever is missing was discarded at the start of
the stream.

Stream *open* time is reported separately rather than folded in. It is a
real cost — dead time after the chime, while the user may already be
speaking — but it is not discarded audio, and on a Mac it is dominated by
the microphone-permission dialog the first time it runs.

Two conditions, interleaved, each after a 3 s idle gap so the stale state
has time to develop:

    WITH re-init      what the code does today
    WITHOUT re-init   what dropping it from the recording path would do

No microphone signal is required — silence counts as frames just as
speech does. **Nothing needs to be spoken and nothing is judged by ear.**

Reading the result
------------------

    both missing columns within ~30 ms
        Input is unaffected. The re-init can be dropped from the
        recording path, which removes 96 ms from the gap between the
        chime and the microphone going live.

    WITHOUT is short by several hundred ms
        Input is affected exactly like output. The current code is
        correct and the 96 ms is the price of not clipping commands.

    both short
        Something else is wrong; do not change the recording path on the
        strength of it. Say so rather than acting on it.

Run on the Pi — the fault has never been reproduced on a Mac, where a
re-init costs 2 ms rather than 96 and all of this is moot:

    python -m indepensense.voice.tests.manual.mic_onset_test
"""
import time

TRIALS = 3
RECORD_S = 2.0
IDLE_S = 3.0
SAMPLERATE = 16000

# Anything under this is ordinary stream start-up, not the fault being
# looked for. The output-side discard was ~800 ms; a result in between is
# worth reporting rather than rounding to either conclusion.
_NEGLIGIBLE_MS = 30.0


def measure_once(reinitialise: bool) -> tuple[float, float]:
    """Record for `RECORD_S` and report (open_seconds, captured_seconds).

    Two separate costs, deliberately not summed:

      * **open** — how long constructing and starting the stream takes.
        This is dead time after the chime during which the user may
        already be speaking and nothing is listening.
      * **captured** — how much audio actually arrived during a known
        `RECORD_S` of recording. Anything short of it was discarded by
        the stream after it started.

    An earlier version measured one wall-clock span covering both and
    could not tell them apart, which on a Mac reported 37 s "missing"
    because the microphone-permission dialog is part of opening a stream.
    """
    import sounddevice as sd

    if reinitialise:
        sd._terminate()
        sd._initialize()

    frames: list[int] = []

    def _callback(indata, _count, _time, _status):
        frames.append(len(indata))

    started = time.perf_counter()
    stream = sd.InputStream(samplerate=SAMPLERATE, channels=1,
                            dtype="int16", callback=_callback)
    with stream:
        open_s = time.perf_counter() - started
        time.sleep(RECORD_S)

    return open_s, sum(frames) / SAMPLERATE


def reinit_cost_ms() -> float:
    """What the workaround costs per stream on this machine."""
    import sounddevice as sd

    samples = []
    for _ in range(5):
        started = time.perf_counter()
        sd._terminate()
        sd._initialize()
        samples.append((time.perf_counter() - started) * 1000.0)
    samples.sort()
    return samples[len(samples) // 2]


def main() -> None:
    print(__doc__.split("Run on the Pi")[0].rstrip())
    print("=" * 70)

    print(f"\nPortAudio re-initialisation costs {reinit_cost_ms():.0f} ms "
          "per stream here.")
    print(f"\n{TRIALS} trials per condition, {RECORD_S:.0f} s each, "
          f"{IDLE_S:.0f} s idle between.")
    print("Nothing to do but wait — no need to speak.\n")
    print(f"  {'condition':22s} {'open':>9s} {'captured':>9s} {'missing':>9s}")
    print("  " + "-" * 52)

    missing = {True: [], False: []}
    opening = {True: [], False: []}
    for _trial in range(TRIALS):
        for reinitialise in (True, False):
            time.sleep(IDLE_S)
            open_s, captured = measure_once(reinitialise)
            lost_ms = (RECORD_S - captured) * 1000.0
            missing[reinitialise].append(lost_ms)
            opening[reinitialise].append(open_s * 1000.0)
            label = "WITH re-init" if reinitialise else "WITHOUT re-init"
            print(f"  {label:22s} {open_s * 1000:7.0f}ms {captured:8.3f}s "
                  f"{lost_ms:8.0f}ms", flush=True)

    print()
    for reinitialise, values in opening.items():
        values.sort()
        label = "WITH re-init" if reinitialise else "WITHOUT re-init"
        print(f"  median stream-open, {label:17s} {values[len(values) // 2]:6.0f} ms"
              "   <- dead time after the chime")

    print()
    medians = {}
    for reinitialise, values in missing.items():
        values.sort()
        medians[reinitialise] = values[len(values) // 2]
        label = "WITH re-init" if reinitialise else "WITHOUT re-init"
        print(f"  median missing, {label:17s} {medians[reinitialise]:6.0f} ms")

    print()
    with_ok = medians[True] < _NEGLIGIBLE_MS
    without_ok = medians[False] < _NEGLIGIBLE_MS

    if with_ok and without_ok:
        print("  Input is NOT affected. The re-init can come out of the")
        print("  recording path, which removes it from the gap between the")
        print("  chime and the microphone going live.")
    elif with_ok and not without_ok:
        print("  Input IS affected, exactly like output. The recording path")
        print("  needs the re-init and the cost is the price of not clipping")
        print("  the first syllable of every command. Change nothing.")
    else:
        print("  Both conditions lost audio, so this does not distinguish")
        print("  them — something else is going on. Report the numbers; do")
        print("  not change the recording path on the strength of this run.")


if __name__ == "__main__":
    main()
