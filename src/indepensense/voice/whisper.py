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
        initial_prompt: str | None = None,
    ) -> Transcript:
        """Transcribe an audio file.

        `initial_prompt` is passed through to Whisper's decoder as recent
        context. Whisper treats it as if the speaker had just said this
        text, which biases the decoder toward similar vocabulary. Useful
        for steering the model toward domain-specific proper nouns that
        smaller models mishear (e.g. Filipino brands like "Jollibee" that
        `tiny` English otherwise mangles to sound-alikes like "Jalebi").

        Whisper's hard limit for initial_prompt is ~224 tokens — roughly
        500-800 characters of natural English. Longer prompts are silently
        truncated and can also degrade transcription of the actual audio,
        so keep the hint focused on the specific vocab you need.
        """
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
            initial_prompt=initial_prompt,
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
