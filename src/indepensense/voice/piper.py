"""Piper text-to-speech driver.

Piper distributes neural TTS models as ONNX files plus a JSON config sibling.
The voice download is documented in `docs/voice.md`; this driver assumes the
ONNX file is already on disk.
"""
import wave
from pathlib import Path


class PiperTTS:
    def __init__(self, voice_path: Path):
        from piper.voice import PiperVoice  # lazy: heavy import

        config_path = voice_path.with_suffix(voice_path.suffix + ".json")
        if not voice_path.exists():
            raise FileNotFoundError(
                f"Piper voice not found at {voice_path}. "
                f"See docs/voice.md for the download command."
            )
        if not config_path.exists():
            raise FileNotFoundError(
                f"Piper voice config not found at {config_path}. "
                f"The .onnx and .onnx.json files must sit side by side."
            )
        self._voice = PiperVoice.load(str(voice_path), config_path=str(config_path))

    def synthesize(self, text: str, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            self._voice.synthesize_wav(text, wav_file)
