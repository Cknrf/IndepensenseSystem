"""Manual benchmark: which remote TTS model is faster, MOSS-TTS-v1.5 or OmniVoice?

Both run behind the API on the gpuer server (`config.TTS_API_BASE_URL`,
documented in docs/tts-api.md). This sends the same sentences to each and
reports request time and real-time factor, **per language**, because the
two languages give different results and averaging them would describe
neither — the same reason `latency_bench` splits them.

**No hardware required.** It runs from any machine with network access,
the Mac included; nothing is synthesised locally.

Corpus
------

The wearable's own static responses from `intents/messages.py` — the
sentences it actually speaks, not a pangram. Templated messages (with a
`{placeholder}`) are left out because they need values to fill. A fixed
seed picks the sample, so two runs measure the same sentences.

Real-time factor
----------------

Request time divided by the length of the audio returned. Below 1x the
clip is ready before it would finish playing, so it can be streamed
without a gap. That is the figure that matters for a navigation cue, and it
normalises away the fact that the two models speak at different speeds.

Methodology notes, because the thesis will need them
----------------------------------------------------

- **Request time is the full HTTPS round trip**, including the network.
  A `GET /health` baseline is printed first so it can be subtracted; it is
  the same for both models.
- **The models alternate on every sentence, and the order flips each
  repeat.** The GPU is shared with other tenants; interleaving makes any
  drift in their load hit both models equally instead of whichever ran
  second.
- **A warmup request per model runs first and is discarded.**
- **Stats use `latency_bench.summarise`**, so the median and p95 here are
  computed the same way as the on-device numbers.
- **Look at the max, not just the median.** MOSS is autoregressive and can
  miss its end-of-speech token: in the first run one request returned
  101 s of audio after 42 s. The median hides that; the max shows it.

Run from repo root:
    python -m indepensense.voice.tests.manual.tts_api_bench
    python -m indepensense.voice.tests.manual.tts_api_bench --repeat 5 --csv

    # One model, one language:
    python -m indepensense.voice.tests.manual.tts_api_bench \\
        --model omnivoice --language tl
"""
import argparse
import csv
import io
import random
import time
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import requests

from indepensense.config import PERF_LOG_DIR, TTS_API_BASE_URL
from indepensense.intents.messages import LANGUAGES, MESSAGES
from indepensense.voice.tests.manual.latency_bench import format_stats, summarise

MODELS = ("omnivoice", "moss")

# MOSS takes a language name; OmniVoice ignores the field.
_LANGUAGE_NAMES = {"en": "English", "tl": "Tagalog"}

# A runaway MOSS generation took 42 s; this leaves room for a worse one
# without letting a stuck request hang the run.
_REQUEST_TIMEOUT_S = 300

_TIMESTAMPED = object()


@dataclass
class Sample:
    model: str
    language: str
    repeat: int
    text: str
    request_s: float
    audio_s: float

    @property
    def rtf(self) -> float:
        return self.request_s / self.audio_s


def pick_corpus(language: str, count: int, seed: int) -> list[str]:
    """`count` static messages in `language`, the same ones for a given seed."""
    static = sorted(m[language] for m in MESSAGES.values() if "{" not in m[language])
    return random.Random(seed).sample(static, min(count, len(static)))


def synthesise(session: requests.Session, url: str, model: str,
               language: str, text: str) -> tuple[float, float]:
    """One request. Returns (request seconds, seconds of audio returned)."""
    started = time.perf_counter()
    response = session.post(
        f"{url}/tts",
        json={"text": text, "model": model, "language": _LANGUAGE_NAMES[language]},
        timeout=_REQUEST_TIMEOUT_S,
    )
    elapsed = time.perf_counter() - started
    response.raise_for_status()
    with wave.open(io.BytesIO(response.content)) as wav:
        return elapsed, wav.getnframes() / wav.getframerate()


def network_baseline(session: requests.Session, url: str, count: int = 10) -> list[float]:
    times = []
    for _ in range(count):
        started = time.perf_counter()
        session.get(f"{url}/health", timeout=30).raise_for_status()
        times.append(time.perf_counter() - started)
    return times


def report(samples: list[Sample], models: list[str], languages: list[str]) -> None:
    for language in languages:
        rows = [s for s in samples if s.language == language]
        if not rows:
            continue
        print(f"\n=== {_LANGUAGE_NAMES[language]} ===")
        for model in models:
            mine = [s for s in rows if s.model == model]
            print(f"-- {model}")
            print(format_stats("request time", summarise([s.request_s for s in mine])))
            print(format_stats("audio length", summarise([s.audio_s for s in mine])))
            print(format_stats("real-time factor", summarise([s.rtf for s in mine]), unit="x"))

        if len(models) == 2:
            first, second = models
            by_key = {(s.model, s.repeat, s.text): s.request_s for s in rows}
            pairs = [(by_key[(first, s.repeat, s.text)], s.request_s)
                     for s in rows if s.model == second]
            wins = sum(a < b for a, b in pairs)
            print(f"   {first} faster in {wins}/{len(pairs)} paired requests")


def write_csv(samples: list[Sample], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["model", "language", "repeat", "chars",
                         "request_s", "audio_s", "rtf", "text"])
        for s in samples:
            writer.writerow([s.model, s.language, s.repeat, len(s.text),
                             f"{s.request_s:.4f}", f"{s.audio_s:.4f}",
                             f"{s.rtf:.4f}", s.text])
    print(f"\nWrote {len(samples)} rows to {path}")


# ----------------------------------------------------------------------- cli

def _resolve_csv_path(value) -> Path | None:
    """Same convention as `latency_bench`: relative names land in PERF_LOG_DIR."""
    if value is None:
        return None
    if value is _TIMESTAMPED:
        stamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
        return PERF_LOG_DIR / f"{stamp}_tts_api.csv"
    path = Path(value)
    return path if path.is_absolute() else PERF_LOG_DIR / path


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Compare MOSS-TTS-v1.5 and OmniVoice on the remote TTS API.",
    )
    parser.add_argument("--url", default=TTS_API_BASE_URL,
                        help=f"API base URL (default: {TTS_API_BASE_URL})")
    parser.add_argument("--model", choices=[*MODELS, "both"], default="both")
    parser.add_argument("--language", choices=[*LANGUAGES, "both"], default="both")
    parser.add_argument("--sentences", type=int, default=15,
                        help="sentences per language (default: 15)")
    parser.add_argument("--repeat", type=int, default=3,
                        help="measurements per sentence per model (default: 3)")
    parser.add_argument("--seed", type=int, default=0,
                        help="corpus sampling seed (default: 0)")
    parser.add_argument("--csv", nargs="?", const=_TIMESTAMPED, default=None,
                        metavar="NAME",
                        help=f"write per-request rows to a CSV under {PERF_LOG_DIR}. "
                             f"Bare --csv uses a timestamped name; an absolute "
                             f"path is honoured as given")
    return parser.parse_args()


def main():
    args = _parse_args()
    models = list(MODELS) if args.model == "both" else [args.model]
    languages = list(LANGUAGES) if args.language == "both" else [args.language]
    corpus = {lang: pick_corpus(lang, args.sentences, args.seed) for lang in languages}
    session = requests.Session()

    print(f"Benchmarking {', '.join(models)} at {args.url}: "
          f"{args.sentences} sentence(s) per language x {args.repeat} repeat(s)")
    print(format_stats("network round trip (/health)",
                       summarise(network_baseline(session, args.url))))

    for model in models:
        synthesise(session, args.url, model, "en", "Warmup sentence.")

    samples = []
    for repeat in range(args.repeat):
        order = models if repeat % 2 == 0 else models[::-1]
        for language in languages:
            for text in corpus[language]:
                for model in order:
                    request_s, audio_s = synthesise(session, args.url, model, language, text)
                    sample = Sample(model, language, repeat, text, request_s, audio_s)
                    samples.append(sample)
                    print(f"  {model:9} {language} r{repeat} {request_s:6.2f}s "
                          f"audio {audio_s:6.2f}s  rtf {sample.rtf:4.2f}x  {text[:50]}")

    report(samples, models, languages)

    csv_path = _resolve_csv_path(args.csv)
    if csv_path is not None:
        write_csv(samples, csv_path)


if __name__ == "__main__":
    main()
