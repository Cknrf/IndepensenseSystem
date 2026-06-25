"""Speech-to-text and text-to-speech interfaces.

Both engines are file-based for now (Phase 1/2 — see CLAUDE.md). Live audio
capture and playback come in Phase 3 once microphone and speaker hardware are
sorted.
"""
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class TranscriptSegment:
    """One word-or-phrase chunk from STT with timing relative to the audio."""
    text: str
    start_s: float
    end_s: float


@dataclass(frozen=True)
class Transcript:
    text: str                            # full transcript with segments joined
    language: str                        # detected or specified language code
    segments: list[TranscriptSegment]


class STTEngine(Protocol):
    def transcribe(self, audio_path: Path, language: str = "en") -> Transcript:
        """Transcribe a WAV file into text."""


class TTSEngine(Protocol):
    def synthesize(self, text: str, output_path: Path) -> None:
        """Render text to a WAV file at the given path."""
