"""Fetch every Hub-hosted model the wearable loads, once, into `models/`.

    python -m indepensense.tools.fetch_models            # whatever is missing
    python -m indepensense.tools.fetch_models --force    # everything again
    python -m indepensense.tools.fetch_models --dry-run  # list, no network

Run it on the Pi once after a fresh install, and again after changing
`WHISPER_MODELS`, `NLU_EMBEDDING_MODEL` or `MMS_VOICE_REPOS` in
`config.py`. It lays each model out as a plain directory the driver
loads by path:

    models/whisper/<size>/                 faster-whisper (CTranslate2)
    models/embeddings/multilingual-e5-small/   sentence-transformers
    models/voices/mms-tts-tgl/             MMS-TTS (transformers)

Piper's English voice is not on the Hub and is not fetched here —
`python -m piper.download_voices` handles it (see docs/voice.md).

**Why the runtime no longer downloads for itself.** It used to: both
faster-whisper and sentence-transformers were handed a repo id and
resolved it at startup, which asks the Hub for the current revision
before touching the local copy. Measured on the Pi, that cost ~8 s per
boot for the embedding model alone — sentence-transformers probes ten
files that do not exist in the repo, one round trip each — and on a boot
with no network it is a wait for the timeout instead. A wearable that
starts in the field cannot depend on huggingface.co answering. A
directory path is loaded as is: startup is the same with the modem up,
down or absent, and the weights in use are the ones that were tested
rather than whatever the Hub serves today. The MMS voice already
followed this rule; this makes it the rule for everything.

**A missing model is now a startup failure, not a slow boot.** That is
deliberate. The drivers raise `FileNotFoundError` naming this tool, so
the one deliberate run with network after installation replaces an
implicit download that could fire at any boot, in the field, over the
SIM link. The first-boot checklist in the README lists this step.

Safe to re-run: a directory that already holds files is skipped unless
`--force`. A download interrupted half-way leaves a partial directory
that looks present — `--force` is the fix.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from indepensense.config import (
    MMS_VOICE_REPOS,
    MMS_VOICES,
    NLU_EMBEDDING_MODEL,
    NLU_EMBEDDING_MODEL_DIR,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)

# Left out of every Hub snapshot. The repos ship alternative formats
# alongside the safetensors weights the drivers load — ONNX and OpenVINO
# exports, the legacy `pytorch_model.bin` — which would double the bytes
# on the SD card and, for the voice, double what `transformers` has to
# consider when it picks a weights file.
_HUB_IGNORE = ("onnx/*", "openvino/*", "*.bin", "*.h5", "*.msgpack", "*.ot")


@dataclass(frozen=True)
class Target:
    label: str
    destination: Path
    fetch: Callable[[], None]

    @property
    def present(self) -> bool:
        return self.destination.is_dir() and any(self.destination.iterdir())


def _whisper(size: str, destination: Path) -> Callable[[], None]:
    def fetch() -> None:
        from faster_whisper import download_model  # lazy: Pi-only

        # faster-whisper knows the repo for each size and which files a
        # CTranslate2 model needs; `output_dir` makes it a plain directory
        # rather than a Hub cache tree.
        download_model(size, output_dir=str(destination))
    return fetch


def _snapshot(repo: str, destination: Path) -> Callable[[], None]:
    def fetch() -> None:
        from huggingface_hub import snapshot_download  # lazy: Pi-only

        snapshot_download(repo, local_dir=str(destination), ignore_patterns=list(_HUB_IGNORE))
    return fetch


def targets() -> list[Target]:
    """Everything the configuration says the wearable loads from the Hub."""
    found: list[Target] = []
    for size in dict.fromkeys(WHISPER_MODELS.values()):   # de-duplicated, ordered
        destination = WHISPER_MODEL_DIR / size
        found.append(Target(f"Whisper {size}", destination, _whisper(size, destination)))
    found.append(Target(
        f"embedding model {NLU_EMBEDDING_MODEL}",
        NLU_EMBEDDING_MODEL_DIR,
        _snapshot(NLU_EMBEDDING_MODEL, NLU_EMBEDDING_MODEL_DIR),
    ))
    for language, repo in MMS_VOICE_REPOS.items():
        destination = MMS_VOICES[language]
        found.append(Target(f"MMS voice {repo}", destination, _snapshot(repo, destination)))
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true",
                        help="fetch again even if the directory already holds files.")
    parser.add_argument("--dry-run", action="store_true",
                        help="list what would be fetched, without touching the network.")
    args = parser.parse_args(argv)

    wanted = targets()
    todo = [t for t in wanted if args.force or not t.present]
    for target in wanted:
        state = "fetch" if target in todo else "present"
        print(f"  {state:8s} {target.label:45s} -> {target.destination}")
    print(f"\n{len(todo)} to fetch, {len(wanted) - len(todo)} already present.")
    if args.dry_run or not todo:
        return 0

    failures = 0
    started = time.monotonic()
    for target in todo:
        print(f"\nFetching {target.label}...", flush=True)
        target.destination.mkdir(parents=True, exist_ok=True)
        try:
            target.fetch()
        except Exception as exc:
            # Carry on: one repo unreachable must not stop the others.
            failures += 1
            print(f"  FAILED: {exc}", file=sys.stderr, flush=True)
    print(f"\nDone in {time.monotonic() - started:.0f}s, {failures} failure(s).")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
