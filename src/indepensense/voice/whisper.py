"""faster-whisper speech-to-text driver.

Holds one Whisper model per language code and picks which one to use per
transcription call. This lets us mix model sizes across languages — for
example, `tiny` for English (fast, accurate on English-only training data)
and `small` for Tagalog (Tagalog is underrepresented in Whisper's training
set, so a larger model is needed for acceptable accuracy).

`int8` quantization is used because the Pi 5 has no GPU. It roughly halves
memory and doubles CPU throughput vs `float16`, with negligible accuracy
cost at these model sizes.

Models are loaded from directories under `config.WHISPER_MODEL_DIR`, laid
out by `tools/fetch_models.py`, never resolved from the Hugging Face Hub
by name. Given a name, faster-whisper asks the Hub for the current
revision before using its local copy — a round trip per model on every
boot, and a wait for the timeout on a boot with no network. A directory
path is loaded as is.
"""
from pathlib import Path

from indepensense.voice.base import Transcript, TranscriptSegment


class FasterWhisperSTT:
    def __init__(
        self,
        models: dict[str, str],
        model_dir: Path,
        compute_type: str = "int8",
    ):
        """Load one model per language code from `model_dir/<size>/`.

        `models` maps language codes (e.g. "en", "tl") to Whisper model
        sizes ("tiny", "base", "small", "medium", "large-v3"); each size
        is a CTranslate2 model directory under `model_dir`. Loading a
        model takes seconds, so we do it once at construction and
        select per call.

        A missing directory is a `FileNotFoundError` naming the fetch
        step, not a download: the wearable must start in the field with
        no network, so the only acceptable time to need the Hub is the
        one deliberate run of `fetch_models` after installation.

        The first language in the dict is the default when `transcribe` is
        called without an explicit `language` argument.
        """
        from faster_whisper import WhisperModel  # lazy: pulls ctranslate2

        if not models:
            raise ValueError("FasterWhisperSTT requires at least one model")

        self._models: dict[str, object] = {}
        self._sizes: dict[str, str] = dict(models)
        for language, size in models.items():
            path = model_dir / size
            if not path.is_dir():
                raise FileNotFoundError(
                    f"Whisper '{size}' for '{language}' not found at {path}. "
                    f"Fetch it once with: python -m indepensense.tools.fetch_models"
                )
            self._models[language] = WhisperModel(
                str(path), device="cpu", compute_type=compute_type,
            )

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
