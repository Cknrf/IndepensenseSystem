"""Manual benchmark: how long does the voice pipeline actually take?

The thesis claims low-latency edge processing on the Pi 5. That is a
quantitative claim and nothing in this repository currently supports it —
`data/performance/` is empty, and the only figure anybody has is "three to
seven seconds, roughly". This produces the numbers.

**No microphone required.** Recording is the one stage that needs one, and
it is excluded deliberately: it is bounded by how long the user chooses to
speak, not by the device. Everything after it — transcribe, classify,
synthesise — is replayed from WAVs already on disk. Every push-to-talk
press writes one to `config.VOICE_TEST_DIR`, so a prototype session leaves
a corpus behind.

What it measures, per clip and per repetition:

    STT    faster-whisper transcribe   (the suspected dominant cost)
    NLU    Ollama classify             (only if Ollama is reachable)
    TTS    Piper synthesise            (of the intent's actual response)

and reports median / p95 / min / max for each, **per language**, because
English runs `tiny` and Tagalog runs `small` and averaging them would
describe neither.

Real-time factor
----------------

STT is also reported as RTF — processing seconds per second of audio.
That is the figure that generalises: "2.1 s" only means something if you
also know the clip was 1.4 s long, whereas an RTF of 1.5 tells you what a
five-second command will cost without measuring one.

Methodology notes, because the thesis will need them
----------------------------------------------------

- **A warmup pass runs first and is discarded.** The first transcription
  loads the model into memory, which on a Pi 5 is tens of seconds. Leaving
  it in would describe a cold start, not the latency a user experiences.
- **Each clip is measured `--repeat` times.** Single samples on a shared
  CPU are noise; the Pi is also running Ollama, GraphHopper and Photon.
- **p95 needs samples to mean anything.** With fewer than ~20 it is close
  to the maximum. Raise `--repeat` before quoting it.

Prerequisites:
    - WAV files to replay (see `--dir`)
    - Ollama running with `NLU_MODEL` pulled, for the NLU stage
    - Piper voices and Whisper models downloaded (see docs/voice.md)

Run from repo root:
    python -m indepensense.voice.tests.manual.latency_bench
    python -m indepensense.voice.tests.manual.latency_bench --repeat 10 --csv

    # Point it at a specific corpus, one language only:
    python -m indepensense.voice.tests.manual.latency_bench \\
        --dir data/test/voice --language tl --repeat 5 --csv tagalog.csv

    # No Ollama to hand? Measure the two stages that do not need it:
    python -m indepensense.voice.tests.manual.latency_bench --no-nlu
"""
import argparse
import csv
import statistics
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from indepensense.config import (
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OLLAMA_URL,
    MMS_VOICES,
    PERF_LOG_DIR,
    PIPER_VOICES,
    SUPPORTED_LANGUAGES,
    VOICE_TEST_DIR,
    WHISPER_INITIAL_PROMPTS,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)

# Sentinel for a bare `--csv` with no filename — same convention as
# `tools/system_performance`, so the two write to the same place in the
# same way.
_TIMESTAMPED = object()

# What a push-to-talk press names its recording. Anything else in
# `VOICE_TEST_DIR` is output — greetings, responses, announcements — and
# replaying the wearable's own voice would measure nothing useful.
_DEFAULT_PATTERN = "*_command.wav"


# --------------------------------------------------------------- statistics

@dataclass(frozen=True)
class Stats:
    """Summary of one stage's timings, all in seconds."""
    n: int
    median: float
    p95: float
    minimum: float
    maximum: float
    mean: float


def percentile(values: list[float], fraction: float) -> float:
    """Linear-interpolated percentile, matching the common convention.

    `statistics.quantiles` needs at least two points and cuts into equal
    buckets, which is awkward for an arbitrary fraction. This is the
    textbook inclusive method: rank the values, find the position
    `fraction * (n - 1)`, and interpolate between the two neighbours.

    A single sample is its own percentile rather than an error — a
    benchmark run that produced one measurement should still print.
    """
    if not values:
        raise ValueError("percentile of no values")
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def summarise(values: list[float]) -> Stats | None:
    """Reduce raw timings to the figures worth quoting. None if empty."""
    if not values:
        return None
    return Stats(
        n=len(values),
        median=statistics.median(values),
        p95=percentile(values, 0.95),
        minimum=min(values),
        maximum=max(values),
        mean=statistics.fmean(values),
    )


def format_stats(label: str, stats: Stats | None, unit: str = "s") -> str:
    """One aligned line of a results table."""
    if stats is None:
        return f"  {label:<22} (not measured)"
    return (
        f"  {label:<22} n={stats.n:<4} "
        f"median {stats.median:6.2f}{unit}   "
        f"p95 {stats.p95:6.2f}{unit}   "
        f"min {stats.minimum:6.2f}{unit}   "
        f"max {stats.maximum:6.2f}{unit}"
    )


# ------------------------------------------------------------------- corpus

def audio_duration_s(path: Path) -> float:
    """Length of a WAV in seconds, or 0.0 if it cannot be read.

    Needed for the real-time factor, which is the figure that generalises
    beyond the particular clips in the corpus.
    """
    import soundfile as sf  # lazy: not needed to import this module

    try:
        info = sf.info(str(path))
        return float(info.duration)
    except Exception:
        return 0.0


def find_clips(directory: Path, pattern: str, limit: int | None) -> list[Path]:
    """Recordings to replay, oldest first so runs are reproducible."""
    clips = sorted(directory.glob(pattern))
    return clips[:limit] if limit else clips


# ---------------------------------------------------------------- one sample

@dataclass
class Sample:
    """One clip put through the pipeline once."""
    language: str
    clip: str
    audio_s: float
    repetition: int
    stt_s: float | None = None
    nlu_s: float | None = None
    tts_s: float | None = None
    transcript: str = ""
    intent: str = ""

    @property
    def total_s(self) -> float:
        return sum(v for v in (self.stt_s, self.nlu_s, self.tts_s) if v)


def run_once(
    clip: Path,
    language: str,
    repetition: int,
    stt,
    parser,
    tts,
    output_dir: Path,
) -> Sample:
    """Transcribe, classify and synthesise one clip, timing each stage.

    `parser` or `tts` may be None, which skips that stage and leaves its
    timing unset rather than recording a zero — a stage that did not run
    is not a stage that took no time.
    """
    sample = Sample(
        language=language,
        clip=clip.name,
        audio_s=audio_duration_s(clip),
        repetition=repetition,
    )

    started = time.perf_counter()
    transcript = stt.transcribe(
        clip,
        language=language,
        initial_prompt=WHISPER_INITIAL_PROMPTS.get(language) or None,
    )
    sample.stt_s = time.perf_counter() - started
    sample.transcript = transcript.text.strip()

    if parser is not None and sample.transcript:
        started = time.perf_counter()
        result = parser.parse(sample.transcript)
        sample.nlu_s = time.perf_counter() - started
        sample.intent = result.intent.value

    if tts is not None:
        # Synthesise something of realistic length. The transcript stands
        # in for a response: both are one short sentence, and using the
        # real response would need the executor, GPS and the routing
        # services, which is a different test.
        spoken = sample.transcript or "Navigating to your destination."
        target = output_dir / f"bench_{language}_{repetition}.wav"
        started = time.perf_counter()
        tts.synthesize(spoken, target, language=language)
        sample.tts_s = time.perf_counter() - started

    return sample


# ------------------------------------------------------------------ reporting

def _stage_line(sample: Sample) -> str:
    """Per-measurement progress: only the stages that actually ran.

    A skipped stage is omitted rather than printed as 0.00 s, which would
    read as "instant" instead of "not measured".
    """
    parts = []
    for label, value in (
        ("stt", sample.stt_s), ("nlu", sample.nlu_s), ("tts", sample.tts_s),
    ):
        if value is not None:
            parts.append(f"{label} {value:5.2f}s")
    return "  ".join(parts) if parts else "(nothing measured)"


def report(samples: list[Sample], languages: list[str]) -> None:
    """Print the per-language tables that the thesis will quote."""
    print()
    print("=" * 72)
    print("  RESULTS")
    print("=" * 72)

    for language in languages:
        rows = [s for s in samples if s.language == language]
        if not rows:
            continue

        model = WHISPER_MODELS.get(language, "?")
        print(f"\n  --- {language}  (Whisper '{model}') "
              f"{len(rows)} measurement(s) ---")

        for label, values in (
            ("STT (transcribe)", [s.stt_s for s in rows if s.stt_s is not None]),
            ("NLU (classify)", [s.nlu_s for s in rows if s.nlu_s is not None]),
            ("TTS (synthesise)", [s.tts_s for s in rows if s.tts_s is not None]),
            ("TOTAL", [s.total_s for s in rows if s.total_s]),
        ):
            print(format_stats(label, summarise(values)))

        # Real-time factor: the number that generalises past this corpus.
        rtf = [
            s.stt_s / s.audio_s
            for s in rows
            if s.stt_s is not None and s.audio_s > 0
        ]
        rtf_stats = summarise(rtf)
        if rtf_stats is not None:
            print(format_stats("STT real-time factor", rtf_stats, unit="x"))
            print(f"  {'':22} → a 5 s command costs about "
                  f"{rtf_stats.median * 5:.1f} s to transcribe")

    total = summarise([s.total_s for s in samples if s.total_s])
    if total is not None:
        print(f"\n  Across all languages: median {total.median:.2f} s, "
              f"p95 {total.p95:.2f} s")
        print("  (excludes recording, which is bounded by how long the user "
              "speaks, not the device)")

    if total is not None and total.n < 20:
        print(f"\n  NOTE: {total.n} samples. p95 is close to the maximum below "
              f"~20 — raise --repeat before quoting it.")


def write_csv(samples: list[Sample], path: Path) -> None:
    """One row per measurement, for the thesis appendix and for plotting."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "language", "clip", "audio_s", "repetition",
            "stt_s", "nlu_s", "tts_s", "total_s",
            "transcript", "intent",
        ])
        for s in samples:
            writer.writerow([
                s.language, s.clip, f"{s.audio_s:.3f}", s.repetition,
                f"{s.stt_s:.4f}" if s.stt_s is not None else "",
                f"{s.nlu_s:.4f}" if s.nlu_s is not None else "",
                f"{s.tts_s:.4f}" if s.tts_s is not None else "",
                f"{s.total_s:.4f}",
                s.transcript, s.intent,
            ])
    print(f"\n  Wrote {len(samples)} rows to {path}")


# ----------------------------------------------------------------------- cli

def _resolve_csv_path(value) -> Path | None:
    """Same convention as `tools/system_performance`.

    Relative names resolve against `PERF_LOG_DIR`, so where you happened to
    run from cannot decide where the evaluation data lands.
    """
    if value is None:
        return None
    if value is _TIMESTAMPED:
        stamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
        return PERF_LOG_DIR / f"{stamp}_latency.csv"
    path = Path(value)
    return path if path.is_absolute() else PERF_LOG_DIR / path


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Measure voice-pipeline latency by replaying recorded WAVs.",
    )
    parser.add_argument("--dir", type=Path, default=VOICE_TEST_DIR,
                        help=f"where to find recordings (default: {VOICE_TEST_DIR})")
    parser.add_argument("--pattern", default=_DEFAULT_PATTERN,
                        help=f"glob for the clips (default: {_DEFAULT_PATTERN})")
    parser.add_argument("--language", choices=[*SUPPORTED_LANGUAGES, "both"],
                        default="both",
                        help="which language's models to measure (default: both)")
    parser.add_argument("--repeat", type=int, default=3,
                        help="measurements per clip (default: 3)")
    parser.add_argument("--limit", type=int, default=None,
                        help="use at most this many clips")
    parser.add_argument("--warmup", type=int, default=1,
                        help="discarded passes before measuring, to exclude "
                             "model load (default: 1)")
    parser.add_argument("--no-nlu", action="store_true",
                        help="skip the Ollama stage")
    parser.add_argument("--no-tts", action="store_true",
                        help="skip the Piper stage")
    parser.add_argument("--csv", nargs="?", const=_TIMESTAMPED, default=None,
                        metavar="NAME",
                        help=f"write per-measurement rows to a CSV under "
                             f"{PERF_LOG_DIR}. Bare --csv uses a timestamped "
                             f"name; an absolute path is honoured as given")
    return parser.parse_args()


def main():
    args = _parse_args()
    languages = (
        list(SUPPORTED_LANGUAGES) if args.language == "both" else [args.language]
    )

    clips = find_clips(args.dir, args.pattern, args.limit)
    if not clips:
        print(f"No clips matching {args.pattern!r} in {args.dir}.")
        print()
        print("Every push-to-talk press writes one, so a prototype session")
        print("leaves a corpus behind — check the Pi rather than a dev machine.")
        print("Failing that, record a handful once:")
        print("    python -m indepensense.voice.tests.manual.stt_test")
        raise SystemExit(1)

    print(f"Benchmarking {len(clips)} clip(s) x {args.repeat} "
          f"repetition(s) x {len(languages)} language(s)")
    print(f"  corpus: {args.dir}")

    print("\n  Loading Whisper models...")
    from indepensense.voice.whisper import FasterWhisperSTT
    stt = FasterWhisperSTT(models=WHISPER_MODELS, model_dir=WHISPER_MODEL_DIR)

    tts = None
    if not args.no_tts:
        print("  Loading TTS voices (Piper + MMS)...")
        from indepensense.voice.router import build_tts
        tts = build_tts(piper_voices=PIPER_VOICES, mms_voices=MMS_VOICES)

    parser = None
    if not args.no_nlu:
        print("  Connecting to Ollama (with warmup)...")
        from indepensense.intents.parser import OllamaIntentParser
        try:
            parser = OllamaIntentParser(
                model=NLU_MODEL, ollama_url=OLLAMA_URL,
                prompt_path=NLU_PROMPT_PATH, timeout_s=NLU_TIMEOUT_S,
                warmup=True, warmup_timeout_s=NLU_WARMUP_TIMEOUT_S,
            )
        except Exception as exc:
            print(f"  Ollama unavailable ({exc}). Continuing without the "
                  f"NLU stage — the other two still measure.")

    args.dir.mkdir(parents=True, exist_ok=True)

    # Warmup. The first transcription loads the model, which on a Pi 5 is
    # tens of seconds; measuring it would describe a cold start rather than
    # the latency a user experiences.
    for language in languages:
        for i in range(args.warmup):
            print(f"  Warmup {language} {i + 1}/{args.warmup}...", flush=True)
            run_once(clips[0], language, -1, stt, parser, tts, args.dir)

    samples: list[Sample] = []
    total_runs = len(languages) * len(clips) * args.repeat
    run = 0
    for language in languages:
        for clip in clips:
            for repetition in range(args.repeat):
                run += 1
                sample = run_once(
                    clip, language, repetition, stt, parser, tts, args.dir,
                )
                samples.append(sample)
                print(f"  [{run:3d}/{total_runs}] [{language}] "
                      f"{clip.name[:34]:<34} {_stage_line(sample)}",
                      flush=True)

    report(samples, languages)

    csv_path = _resolve_csv_path(args.csv)
    if csv_path is not None:
        write_csv(samples, csv_path)
    else:
        print(f"\n  Re-run with --csv to record this under {PERF_LOG_DIR} "
              f"— objective 6 needs the data on disk, not in scrollback.")


if __name__ == "__main__":
    main()
