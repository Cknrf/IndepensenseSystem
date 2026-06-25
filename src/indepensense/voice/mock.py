"""Mock STT/TTS for off-device development.

TTS writes a tiny silent WAV header so the file path is valid; STT returns a
canned transcript. Enough to exercise voice-using code paths on a Mac without
the heavy ONNX/CTranslate2 dependencies installed.
"""
import wave
from pathlib import Path

from indepensense.voice.base import Transcript, TranscriptSegment


class MockTTS:
    def synthesize(self, text: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        # 0.1 s of silence at 16 kHz mono — enough for downstream code to
        # treat the file as a valid WAV without taking up real space.
        with wave.open(str(output_path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b"\x00\x00" * 1600)


class MockSTT:
    def transcribe(self, audio_path: Path, language: str = "en") -> Transcript:
        text = "navigate to the cafeteria"
        return Transcript(
            text=text,
            language=language,
            segments=[TranscriptSegment(text=text, start_s=0.0, end_s=1.5)],
        )
