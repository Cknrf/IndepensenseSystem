"""faster-whisper speech-to-text driver.

Holds one Whisper model per language code and picks which one to use per
transcription call. This lets us mix model sizes across languages — for
example, `tiny` for English (fast, accurate on English-only training data)
and `base` for Tagalog (Tagalog is underrepresented in Whisper's training
set, so a larger model is needed for acceptable accuracy).

`int8` quantization is used because the Pi 5 has no GPU. It roughly halves
memory and doubles CPU throughput vs `float16`, with negligible accuracy
cost at these model sizes.
"""
from pathlib import Path

from indepensense.voice.base import Transcript, TranscriptSegment


class FasterWhisperSTT:
    def __init__(
        self,
        models: dict[str, str],
        model_dir: Path | None = None,
        compute_type: str = "int8",
    ):
        """Load one model per language code.

        `models` maps language codes (e.g. "en", "tl") to Whisper model
        sizes ("tiny", "base", "small", "medium", "large-v3"). Loading a
        model takes several seconds, so we do it once at construction and
        select per call.

        The first language in the dict is the default when `transcribe` is
        called without an explicit `language` argument.
        """
        from faster_whisper import WhisperModel  # lazy: pulls ctranslate2

        if not models:
            raise ValueError("FasterWhisperSTT requires at least one model")

        kwargs: dict = {"compute_type": compute_type, "device": "cpu"}
        if model_dir is not None:
            model_dir.mkdir(parents=True, exist_ok=True)
            kwargs["download_root"] = str(model_dir)

        self._models: dict[str, object] = {}
        self._sizes: dict[str, str] = dict(models)
        for language, size in models.items():
            self._models[language] = WhisperModel(size, **kwargs)

        self._default_language = next(iter(models))

    def model_size_for(self, language: str) -> str | None:
        """Return the loaded model size for a language, or None if not loaded."""
        return self._sizes.get(language)

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
    ) -> Transcript:
        lang = language or self._default_language
        if lang not in self._models:
            raise ValueError(
                f"No Whisper model loaded for language '{lang}'. "
                f"Available: {sorted(self._models)}"
            )
        model = self._models[lang]

        segments_iter, info = model.transcribe(
            str(audio_path),
            language=lang,
            beam_size=1,          # greedy decoding — fastest on CPU
            vad_filter=True,      # skip non-speech regions
        )
        segments = [
            TranscriptSegment(text=s.text.strip(), start_s=s.start, end_s=s.end)
            for s in segments_iter
        ]
        full_text = " ".join(s.text for s in segments).strip()
        return Transcript(
            text=full_text,
            language=info.language,
            segments=segments,
        )
