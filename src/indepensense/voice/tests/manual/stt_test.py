"""Manual test: transcribe a WAV with faster-whisper.

Run from repo root with:
    python -m indepensense.voice.tests.manual.stt_test [path/to/audio.wav]

Without an argument, transcribes the most recent file in VOICE_TEST_DIR —
useful as a TTS->STT roundtrip check after running tts_test.py.

First run downloads the Whisper model into WHISPER_MODEL_DIR (~75 MB for tiny).
"""
import sys
import time
from pathlib import Path

from indepensense.config import (
    VOICE_TEST_DIR,
    WHISPER_MODEL_DIR,
    WHISPER_MODEL_SIZE,
)
from indepensense.voice.whisper import FasterWhisperSTT


def latest_wav() -> Path | None:
    wavs = sorted(VOICE_TEST_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    return wavs[-1] if wavs else None


def main():
    if len(sys.argv) > 1:
        audio_path = Path(sys.argv[1])
    else:
        audio_path = latest_wav()
        if audio_path is None:
            print(f"No WAV files in {VOICE_TEST_DIR}. Run tts_test first or pass a path.")
            return
        print(f"(No path given, using latest: {audio_path.name})")

    print(f"Loading Whisper '{WHISPER_MODEL_SIZE}' from {WHISPER_MODEL_DIR}")
    stt = FasterWhisperSTT(model_size=WHISPER_MODEL_SIZE, model_dir=WHISPER_MODEL_DIR)

    print(f"Transcribing {audio_path}...")
    t0 = time.time()
    transcript = stt.transcribe(audio_path)
    elapsed = time.time() - t0

    print(f"Done in {elapsed:.2f}s (language={transcript.language}).")
    print(f"Full text: {transcript.text}")
    print("Segments:")
    for s in transcript.segments:
        print(f"  [{s.start_s:5.2f}s - {s.end_s:5.2f}s]  {s.text}")


if __name__ == "__main__":
    main()
