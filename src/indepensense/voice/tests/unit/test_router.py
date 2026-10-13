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


# --- build_tts: which engines actually get constructed -----------------------
#
# `MmsTTS.__init__` loads a VITS checkpoint eagerly, so *constructing* an
# engine is the expensive act, not calling it. The remote entries used to
# be applied last and simply overwrite the local ones — right precedence,
# reached by building the loser first. With `REMOTE_TTS_ENABLED` that read
# the Tagalog model off the SD card and made it unreachable in the same
# breath, while `App._try_open_local_tts` built a second router and loaded
# it again for the fallback.
#
# These patch the constructors rather than the filesystem: the assertion
# is about what was built, and a real load would need the checkpoints.

class _Ctor:
    """Stands in for an engine class, recording how it was constructed."""

    def __init__(self):
        self.languages: list[str] = []

    def __call__(self, *args, language=None, voices=None, **kwargs):
        self.languages.append(language or next(iter(voices or {"?": None})))
        return RecordingEngine()


@pytest.fixture
def ctors(monkeypatch):
    from indepensense.voice import router

    piper, mms, remote = _Ctor(), _Ctor(), _Ctor()
    monkeypatch.setattr(router, "PiperTTS", piper)
    monkeypatch.setattr(router, "MmsTTS", mms)
    monkeypatch.setattr(router, "RemoteTTS", remote)
    return piper, mms, remote


def _build(ctors_unused=None, remote=None):
    from indepensense.voice.router import RemoteSpec, build_tts

    return build_tts(
        piper_voices={"en": Path("/models/en.onnx")},
        mms_voices={"tl": Path("/models/mms-tl")},
        remote=RemoteSpec(url="https://tts.test", voices=remote or {}),
    )


def test_a_remotely_served_language_loads_no_local_model(ctors):
    """The fix. Loading a VITS checkpoint to overwrite it immediately is
    one full model load and its memory for an engine nothing can call."""
    piper, mms, remote = ctors

    _build(remote={"tl": "07"})

    assert mms.languages == [], "MMS should not be built for a remote language"
    assert remote.languages == ["tl"]
    assert piper.languages == ["en"], "English is unaffected"


def test_the_local_model_is_still_built_when_nothing_is_remote(ctors):
    """`_try_open_local_tts` builds exactly this router for the fallback,
    so the skip must be conditional on the remote spec, not permanent."""
    piper, mms, remote = ctors

    _build(remote={})

    assert mms.languages == ["tl"]
    assert remote.languages == []


def test_the_remote_engine_wins_the_language_either_way(ctors):
    """Precedence is unchanged — only how it is reached. A regression here
    would have the router speak Tagalog locally while `voice_id` named the
    remote voice, filing every clip under a voice that never spoke."""
    _, _, remote = ctors

    tts = _build(remote={"tl": "07"})

    assert tts.engine_for("tl") is not None
    assert sorted(tts._engines) == ["en", "tl"]


def test_the_default_language_is_unchanged_by_the_skip(ctors):
    """`MultiEngineTTS` takes the first inserted language as its default,
    and the skip moves insertion order around. English must stay first."""
    tts = _build(remote={"tl": "07"})

    assert next(iter(tts._engines)) == "en"
