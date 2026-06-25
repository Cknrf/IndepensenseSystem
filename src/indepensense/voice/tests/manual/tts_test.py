"""Manual test: synthesize a sentence with Piper and save as WAV.

Run from repo root with:
    python -m indepensense.voice.tests.manual.tts_test

See `docs/voice.md` for downloading the Piper voice file.
The output WAV is saved under VOICE_TEST_DIR with a timestamped filename so
you can copy it back to a Mac (or play with `aplay` on the Pi) and listen.
"""
import time
from datetime import datetime

from indepensense.config import PIPER_VOICE_PATH, VOICE_TEST_DIR
from indepensense.voice.piper import PiperTTS

SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "Obstacle detected three meters ahead. "
    "Turn left in twenty meters."
)


def main():
    output_path = VOICE_TEST_DIR / (datetime.now().strftime("%B-%d-%Y_%H-%M-%S") + "_tts.wav")
    print(f"Loading Piper voice from {PIPER_VOICE_PATH}")
    tts = PiperTTS(voice_path=PIPER_VOICE_PATH)

    print(f"Synthesizing {len(SAMPLE_TEXT)} chars...")
    t0 = time.time()
    tts.synthesize(SAMPLE_TEXT, output_path)
    elapsed = time.time() - t0

    print(f"Done in {elapsed:.2f}s. WAV saved to {output_path}")


if __name__ == "__main__":
    main()
