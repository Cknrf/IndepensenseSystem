"""faster-whisper speech-to-text driver.

`int8` quantization is used because the Pi 5 has no GPU and `int8` halves
memory and roughly doubles throughput vs `float16` on CPU, at negligible
accuracy cost for the `tiny` model.
"""
from pathlib import Path

from indepensense.voice.base import Transcript, TranscriptSegment


class FasterWhisperSTT:
    def __init__(
        self,
        model_size: str = "tiny",
        model_dir: Path | None = None,
        compute_type: str = "int8",
    ):
        from faster_whisper import WhisperModel  # lazy: pulls ctranslate2

        kwargs: dict = {"compute_type": compute_type, "device": "cpu"}
        if model_dir is not None:
            model_dir.mkdir(parents=True, exist_ok=True)
            kwargs["download_root"] = str(model_dir)
        self._model = WhisperModel(model_size, **kwargs)

    def transcribe(self, audio_path: Path, language: str = "en") -> Transcript:
        segments_iter, info = self._model.transcribe(
            str(audio_path),
            language=language,
            beam_size=1,                  # greedy decoding — fastest on CPU
            vad_filter=True,              # skip non-speech regions
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
