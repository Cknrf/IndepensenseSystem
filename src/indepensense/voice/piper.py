"""Piper text-to-speech driver.

The driver holds one or more ONNX voices keyed by language code and picks
which voice to use for each synthesis call. This keeps the door open for
switching between English and Filipino output without reloading models —
loading a voice takes several seconds, so we do it once at construction and
select per call thereafter.

Piper does not currently publish a Filipino/Tagalog voice. In this project
the `tl` slot is filled with an Indonesian voice (`id_ID-news_tts-medium`).
Indonesian and Filipino are both Austronesian, share the same 5-vowel
system, and produce intelligible Tagalog output even though the accent is
not native. This is documented as a workaround in `docs/voice.md`; a
switch to Meta MMS-TTS is future work.
"""
import wave
from pathlib import Path


class PiperTTS:
    def __init__(self, voices: dict[str, Path]):
        """Load one voice per language code.

        `voices` maps language codes (e.g. "en", "tl") to the path of the
        ONNX weights file. Piper requires a `.onnx.json` config file with
        the same base name in the same directory.

        The first language in the dict becomes the default when `synthesize`
        is called without an explicit `language` argument.
        """
        from piper.voice import PiperVoice  # lazy: heavy import

        if not voices:
            raise ValueError("PiperTTS requires at least one voice")

        self._voices: dict[str, object] = {}
        for language, voice_path in voices.items():
            config_path = voice_path.with_suffix(voice_path.suffix + ".json")
            if not voice_path.exists():
                raise FileNotFoundError(
                    f"Piper voice for '{language}' not found at {voice_path}. "
                    f"See docs/voice.md for the download command."
                )
            if not config_path.exists():
                raise FileNotFoundError(
                    f"Piper voice config not found at {config_path}. "
                    f"The .onnx and .onnx.json files must sit side by side."
                )
            self._voices[language] = PiperVoice.load(
                str(voice_path), config_path=str(config_path)
            )

        self._default_language = next(iter(voices))

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str | None = None,
    ) -> None:
        lang = language or self._default_language
        if lang not in self._voices:
            raise ValueError(
                f"No voice loaded for language '{lang}'. "
                f"Available: {sorted(self._voices)}"
            )
        voice = self._voices[lang]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(output_path), "wb") as wav_file:
            voice.synthesize_wav(text, wav_file)
