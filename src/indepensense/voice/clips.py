"""Content-addressed storage for rendered speech.

Synthesis is the slowest step in answering: 0.2-2.3 s on the Pi,
depending on sentence length, and it ran again every single time the
wearable spoke — including for the 61 messages whose text never changes.
The device paid two seconds to re-render "Emergency alert sent." on
every press.

A clip is named after the sentence it contains, not after when it was
made:

    sha256("en\\x00Emergency alert sent.")[:16] + ".wav"

Three things fall out of that, and they are the whole reason for this
module:

  * **Reuse is automatic.** The same sentence in the same language maps
    to the same filename, so the second utterance is a file read.
  * **Editing `messages.py` invalidates the clip.** New text, new hash,
    new filename — the old recording is simply never asked for again.
    The alternative, a clip keyed by message name, leaves the wearable
    confidently speaking a sentence that is no longer anywhere in the
    source.
  * **Disk stops growing without bound.** The announcer used to write
    `<microsecond timestamp>_announce.wav` per utterance and nothing ever
    deleted them — roughly 9 GB a year of write-once-read-once files on
    the SD card. Identical text now collides onto one file by design.

**Two directories, because they have different lifetimes.** `find()`
searches them in order and the first is never swept:

    data/audio/messages/   static messages. Built by `render_messages`.
                           Permanent.
    data/audio/cache/      everything with a number or a place name in
                           it. Swept once it outgrows its cap.

Splitting them is not tidiness. Age-based eviction over a single
directory would delete the *least* spoken clips first, and the least
spoken clips are `emergency.delivery.all_failed` and its neighbours —
so the one time the device has to say "I could not reach anyone", it
would pay full synthesis to say it. Anything built from a template can
be re-rendered at leisure; the fixed messages are the ones that must
already be on disk.

Callers do not say which kind they have, and must not have to: the
announcer receives finished text and has no idea whether a template
produced it. A static sentence hashes to a name that is in the
permanent directory and is found there; a templated one cannot be, so
it lands in the cache. The split happens on its own.

Nothing here is Pi-only — `soundfile` and the TTS engines are the ones
that need hardware, and this module touches neither. It is importable
and testable on a Mac.
"""
from __future__ import annotations

import hashlib
import os
import threading
from pathlib import Path


# Half-written clips live here, one level down, so that a `*.wav` glob
# over the clip directory can never pick one up.
SCRATCH_DIR_NAME = ".partial"


def digest(text: str, language: str) -> str:
    """Stable identity for one sentence spoken in one language.

    The language is part of the hash, not just the directory, because
    the English and Tagalog voices render different audio and a message
    that happens to be identical in both — a place name, a brand — must
    still produce two clips.

    The NUL separator keeps the two fields from running together: with a
    plain concatenation, language "en" + text "glish..." and language
    "english" + text "..." would collide. Unlikely with two languages,
    free to prevent.

    16 hex characters is 64 bits. At a few thousand clips the odds of a
    collision are around 1 in 10^13, and a collision would mean one
    sentence spoken in another's voice — worth the eight extra
    characters over the 8 the old startup clips used.
    """
    return hashlib.sha256(f"{language}\x00{text}".encode()).hexdigest()[:16]


def filename(text: str, language: str) -> str:
    return f"{digest(text, language)}.wav"


def find(text: str, language: str, *directories: Path) -> Path | None:
    """First directory containing a clip of this exact sentence.

    Order matters and is the caller's choice: pass the permanent
    directory before the cache, so a static message that also happens to
    have been cached is served from the copy that will not be swept out
    from under it.
    """
    name = filename(text, language)
    for directory in directories:
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def render(tts, text: str, language: str, directory: Path) -> Path:
    """Synthesise into `directory` and return the finished clip.

    Writes to a temporary file and renames into place. `os.replace` is
    atomic on POSIX, which buys two things that matter on a device that
    can lose power at any moment:

      * A crash, or a pull of the battery, mid-synthesis leaves the
        temporary behind rather than a truncated `.wav`. A truncated WAV
        at the right filename is permanent damage — it exists, so `find`
        returns it, and the wearable clips that sentence short forever.
      * Two threads asked to speak the same sentence at the same moment
        — the announcer and the voice pipeline can both do this — write
        separate temporaries and rename them onto the same final name.
        One wins, both play a complete file. Interleaved writes to one
        path would corrupt it for both.

    **The temporary keeps a `.wav` extension**, and that is not
    cosmetic. `MmsTTS` writes through `soundfile`, which picks its
    container from the filename; handed a `.part` it raised "No format
    specified and unable to get format from file extension" and every
    Tagalog clip on the device failed to render while English — written
    by Piper through `wave.open`, which does not care — succeeded. The
    `TTSEngine` protocol says "render text to a WAV file at the given
    path", so a path that does not look like one is this function's bug,
    not the engine's.

    It therefore lives in a `.partial/` subdirectory rather than beside
    the finished clips, so that a `*.wav` glob — the sweep, the
    renderer's prune — never mistakes a half-written file for a usable
    one. Same filesystem, so the rename is still atomic.
    """
    directory.mkdir(parents=True, exist_ok=True)
    final = directory / filename(text, language)
    scratch_dir = directory / SCRATCH_DIR_NAME
    scratch_dir.mkdir(parents=True, exist_ok=True)
    # pid and thread id so concurrent writers never share a temporary.
    scratch = scratch_dir / f"{final.stem}.{os.getpid()}.{threading.get_ident()}.wav"
    try:
        tts.synthesize(text, scratch, language=language)
        os.replace(scratch, final)
    except BaseException:
        scratch.unlink(missing_ok=True)
        raise
    return final


def sweep(directory: Path, max_bytes: int) -> int:
    """Delete the oldest clips until `directory` fits. Returns bytes freed.

    Oldest-first by modification time, which for a write-once file is
    when it was rendered. A true LRU would need access times, and
    `relatime` mounts — the default on Raspberry Pi OS — only update
    those once a day, so "least recently used" would be a guess
    sharpened to the nearest 24 hours. Rendered-oldest is at least a
    fact.

    Only ever point this at the cache directory. Everything in it is
    reproducible from a template at the cost of one synthesis; nothing
    in `data/audio/messages/` is, within the boot that needs it.

    Abandoned temporaries are removed unconditionally — one that
    outlived its process is debris from a crash, and no running writer
    owns a name containing a pid that is gone.
    """
    if not directory.exists():
        return 0

    freed = 0
    for scratch in (directory / SCRATCH_DIR_NAME).glob("*.wav"):
        try:
            freed += scratch.stat().st_size
            scratch.unlink()
        except OSError:
            pass

    clips: list[tuple[float, int, Path]] = []
    for clip in directory.glob("*.wav"):
        try:
            stat = clip.stat()
        except OSError:
            continue           # vanished under us; nothing to account for
        clips.append((stat.st_mtime, stat.st_size, clip))

    total = sum(size for _, size, _ in clips)
    for _, size, clip in sorted(clips):
        if total <= max_bytes:
            break
        try:
            clip.unlink()
        except OSError:
            continue
        total -= size
        freed += size
    return freed
