"""Manual test: synthesize a sentence and save as WAV.

Run from repo root with:
    python -m indepensense.voice.tests.manual.tts_test

English goes through Piper and Tagalog through MMS, so which engine
this exercises depends on DEFAULT_LANGUAGE. See `docs/voice.md` for
downloading both.
The output WAV is saved under VOICE_TEST_DIR with a timestamped filename so
you can copy it back to a Mac (or play with `aplay` on the Pi) and listen.
"""
import time
from datetime import datetime

from indepensense.config import (
    DEFAULT_LANGUAGE,
    MMS_VOICES,
    PIPER_VOICES,
    VOICE_TEST_DIR,
)
from indepensense.voice.router import build_tts

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
    print(f"Loading Piper {sorted(PIPER_VOICES)} + MMS {sorted(MMS_VOICES)}")
    tts = build_tts(piper_voices=PIPER_VOICES, mms_voices=MMS_VOICES)

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
