"""MultiEngineTTS dispatch.

No engine here is real — the point of the router is that it holds the
`TTSEngine` protocol and nothing else, so a recording stub is a complete
substitute. The real drivers are verified on the Pi by
`voice.tests.manual.tts_test`.
"""
from pathlib import Path

import pytest

from indepensense.voice.router import MultiEngineTTS


class RecordingEngine:
    """A TTSEngine that records what it was asked for instead of speaking."""

    def __init__(self):
        self.calls: list[tuple[str, Path, str | None]] = []

    def synthesize(self, text, output_path, language=None):
        self.calls.append((text, output_path, language))


def test_routes_each_language_to_its_own_engine():
    english, tagalog = RecordingEngine(), RecordingEngine()
    tts = MultiEngineTTS({"en": english, "tl": tagalog})

    tts.synthesize("turn left", Path("a.wav"), language="en")
    tts.synthesize("kumaliwa ka", Path("b.wav"), language="tl")

    assert [c[0] for c in english.calls] == ["turn left"]
    assert [c[0] for c in tagalog.calls] == ["kumaliwa ka"]


def test_passes_the_language_on_to_the_engine():
    """Not dropped: the engine registered for a language may itself hold
    several voices, as PiperTTS does."""
    english = RecordingEngine()
    MultiEngineTTS({"en": english}).synthesize("hi", Path("a.wav"), language="en")

    assert english.calls[0][2] == "en"


def test_first_language_is_the_default():
    english, tagalog = RecordingEngine(), RecordingEngine()
    MultiEngineTTS({"en": english, "tl": tagalog}).synthesize("hi", Path("a.wav"))

    assert len(english.calls) == 1
    assert tagalog.calls == []


def test_unknown_language_raises_rather_than_speaking_the_wrong_one():
    """Falling back to another engine would mean a Tagalog user silently
    hearing English, which is worse than a caught exception."""
    tts = MultiEngineTTS({"en": RecordingEngine()})

    with pytest.raises(ValueError, match="No TTS engine loaded"):
        tts.synthesize("hi", Path("a.wav"), language="tl")


def test_rejects_an_empty_engine_map():
    with pytest.raises(ValueError, match="at least one engine"):
        MultiEngineTTS({})


def test_engine_for_exposes_the_mapping():
    english = RecordingEngine()
    tts = MultiEngineTTS({"en": english})

    assert tts.engine_for("en") is english
    assert tts.engine_for("tl") is None
