"""Manual test: synthesize a sentence with Piper and save as WAV.

Run from repo root with:
    python -m indepensense.voice.tests.manual.tts_test

See `docs/voice.md` for downloading the Piper voice file.
The output WAV is saved under VOICE_TEST_DIR with a timestamped filename so
you can copy it back to a Mac (or play with `aplay` on the Pi) and listen.
"""
import time
from datetime import datetime

from indepensense.config import PIPER_VOICES, DEFAULT_LANGUAGE, VOICE_TEST_DIR
from indepensense.voice.piper import PiperTTS

SAMPLE_TEXT_EN = (
    "The quick brown fox jumps over the lazy dog. "
    "Obstacle detected three meters ahead. "
    "Turn left in twenty meters."
)

SAMPLE_TEXT_TL = (
    "Magandang umaga. May balakid sa harap. "
    "Lumiko ka sa kaliwa sa loob ng dalawampung metro."
)


def main():
    print(f"Loading Piper voices: {sorted(PIPER_VOICES)}")
    tts = PiperTTS(voices=PIPER_VOICES)

    text = SAMPLE_TEXT_EN if DEFAULT_LANGUAGE == "en" else SAMPLE_TEXT_TL
    output_path = VOICE_TEST_DIR / (
        datetime.now().strftime("%B-%d-%Y_%H-%M-%S") + f"_tts_{DEFAULT_LANGUAGE}.wav"
    )

    print(f"Synthesizing {len(text)} chars in '{DEFAULT_LANGUAGE}'...")
    t0 = time.time()
    tts.synthesize(text, output_path, language=DEFAULT_LANGUAGE)
    elapsed = time.time() - t0

    print(f"Done in {elapsed:.2f}s. WAV saved to {output_path}")


if __name__ == "__main__":
    main()
