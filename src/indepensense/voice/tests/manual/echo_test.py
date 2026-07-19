"""Manual end-to-end echo test: record -> STT -> TTS -> play.

Records for `RECORDING_DURATION_S` seconds through the OS default input,
transcribes with Whisper, synthesises the transcript back with Piper, and
plays the result through the OS default output. Intended for validating
that live audio I/O works end-to-end with whatever device (USB headset,
paired AirPods, etc.) PipeWire is currently routing to.

Run from repo root with:
    python -m indepensense.voice.tests.manual.echo_test
"""
import time
from datetime import datetime

from indepensense.config import (
    PIPER_VOICES,
    SYSTEM_LANGUAGE,
    VOICE_TEST_DIR,
    WHISPER_MODEL_DIR,
    WHISPER_MODELS,
)
from indepensense.voice.audio import play, record
from indepensense.voice.piper import PiperTTS
from indepensense.voice.whisper import FasterWhisperSTT

RECORDING_DURATION_S = 25.0


def main():
    timestamp = datetime.now().strftime("%B-%d-%Y_%H-%M-%S")
    input_path = VOICE_TEST_DIR / f"{timestamp}_input.wav"
    echo_path = VOICE_TEST_DIR / f"{timestamp}_echo.wav"

    print(f"Loading Whisper models {WHISPER_MODELS} and Piper voices {sorted(PIPER_VOICES)}...")
    stt = FasterWhisperSTT(models=WHISPER_MODELS, model_dir=WHISPER_MODEL_DIR)
    tts = PiperTTS(voices=PIPER_VOICES)

    input(f"Ready. Press Enter to start recording {RECORDING_DURATION_S:.0f} seconds. ")
    print("Recording... speak now.")
    t0 = time.time()
    record(RECORDING_DURATION_S, input_path)
    print(f"({(time.time() - t0):.1f}s) Saved raw audio to {input_path.name}")

    print(f"Transcribing (language={SYSTEM_LANGUAGE})...")
    t0 = time.time()
    transcript = stt.transcribe(input_path, language=SYSTEM_LANGUAGE)
    print(f"({(time.time() - t0):.1f}s) You said: {transcript.text or '(nothing detected)'}")

    if not transcript.text.strip():
        print("Empty transcript — no speech detected in the recording. Try again louder,")
        print("or check that the AirPods mic is the current PipeWire default source.")
        return

    print("Synthesising echo...")
    t0 = time.time()
    tts.synthesize(transcript.text, echo_path, language=SYSTEM_LANGUAGE)
    print(f"({(time.time() - t0):.1f}s) Saved echo to {echo_path.name}")

    print("Playing echo...")
    play(echo_path)
    print("Done.")


if __name__ == "__main__":
    main()
