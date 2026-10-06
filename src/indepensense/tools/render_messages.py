"""Render every static message to audio, once, ahead of time.

    python -m indepensense.tools.render_messages
    python -m indepensense.tools.render_messages --force --language tl

Run it on the Pi after editing `intents/messages.py`, and once after a
fresh install. It fills `config.MESSAGE_AUDIO_DIR` with one clip per
static message per language — 61 messages x 2 languages at the time of
writing, roughly 35 MB and a couple of minutes of Piper and MMS.

**Why a tool and not something `start()` does.** Boot is already 2-3
minutes of model loading, and the user is standing there waiting through
it. Rendering 122 clips would add another minute or two to the first
boot after any text edit, for a saving the user could have had at deploy
time instead. The two clips that genuinely must exist before the TTS
engine loads are rendered at the end of `start()` by `_render_boot_clips`
— see `app._BOOT_CLIPS`.

**Skipping this is safe.** Nothing breaks without it; the announcer
falls back to synthesising on demand into the cache directory, which is
exactly how the device behaved before any of this existed. The cost of
forgetting is latency on each sentence's first use, not silence. That is
the whole reason the fallback is there: a deploy step that can be
forgotten must not be a deploy step that can mute the wearable.

**Safe to re-run, and cheap.** Clips are named after a hash of their
text, so an unchanged message is skipped outright and only what you
edited is re-rendered. `--force` re-renders everything, for when the
voice model itself changed rather than the text.

Stale clips — ones whose text no longer appears anywhere in
`messages.py` — are deleted at the end, so an edit leaves one recording
rather than accumulating every wording a sentence has ever had.
"""
from __future__ import annotations

import argparse
import sys
import time

from indepensense.config import MESSAGE_AUDIO_DIR, SUPPORTED_LANGUAGES
from indepensense.intents import messages
from indepensense.voice import clips
from indepensense.voice.router import build_tts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--language", action="append", metavar="CODE",
        help="render only this language (repeatable). Default: all supported.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="re-render clips that already exist.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="list what would be rendered without loading a TTS engine.",
    )
    args = parser.parse_args()

    languages = args.language or list(SUPPORTED_LANGUAGES)
    keys = messages.static_keys()
    templated = len(messages.MESSAGES) - len(keys)

    print(f"{len(keys)} static messages, {templated} templated (skipped).")
    print(f"Languages: {', '.join(languages)}")
    print(f"Target:    {MESSAGE_AUDIO_DIR}")

    # Work out what is missing before loading a TTS engine — on a Mac
    # that import fails outright, which is what makes --dry-run useful
    # off the Pi.
    wanted: dict[str, tuple[str, str]] = {}
    todo: list[tuple[str, str, str]] = []
    for key in keys:
        for language in languages:
            text = messages.get(key, language)
            wanted[clips.filename(text, language)] = (key, language)
            if args.force or clips.find(text, language, MESSAGE_AUDIO_DIR) is None:
                todo.append((key, language, text))

    print(f"\n{len(todo)} to render, {len(wanted) - len(todo)} already present.")
    if args.dry_run:
        for key, language, text in todo:
            print(f"  {language}  {key:34s} {text[:52]!r}")
        return 0

    failures = 0
    if todo:
        print("Loading TTS...", flush=True)
        tts = build_tts()
        started = time.monotonic()
        for index, (key, language, text) in enumerate(todo, start=1):
            try:
                clips.render(tts, text, language, MESSAGE_AUDIO_DIR)
                print(f"  [{index:3d}/{len(todo)}] {language}  {key}", flush=True)
            except Exception as exc:
                # Carry on: one voice missing a phoneme must not stop the
                # other 121 clips from being built.
                failures += 1
                print(f"  [{index:3d}/{len(todo)}] {language}  {key} — FAILED: {exc}",
                      file=sys.stderr, flush=True)
        print(f"\nRendered in {time.monotonic() - started:.0f}s.")

    # Only ever prune when the full set was considered. With --language
    # the clips for every other language look stale and would all be
    # deleted.
    if args.language:
        print("Skipping stale-clip removal (--language renders a subset).")
    else:
        removed = 0
        for clip in MESSAGE_AUDIO_DIR.glob("*.wav"):
            if clip.name not in wanted:
                clip.unlink()
                removed += 1
        if removed:
            print(f"Removed {removed} clip(s) for text no longer in messages.py.")

    total = sum(f.stat().st_size for f in MESSAGE_AUDIO_DIR.glob("*.wav"))
    print(f"{len(list(MESSAGE_AUDIO_DIR.glob('*.wav')))} clips, {total / 1e6:.1f} MB.")
    if failures:
        print(f"{failures} failed — those will synthesise on demand instead.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
