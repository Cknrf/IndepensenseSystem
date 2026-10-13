"""Retention: the zero cap is a privacy control, so it has to be exact.

`config.VOICE_RECORDING_MAX_BYTES` documents 0 as "a working privacy
switch". Sweeping once every `VOICE_RECORDING_SWEEP_EVERY` commands made
that false — up to 24 recordings of the user's voice stayed on the card
until the count came round, and survived a power-off because nothing
sweeps on the way down. A privacy switch that retains 24 recordings is
worse than none, because it is believed.
"""
import wave

import pytest

import indepensense.app as app_module


def _recording(path, kb=32):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(16000)
        handle.writeframes(b"\x00\x00" * (kb * 512))
    return path


@pytest.fixture
def app(tmp_path, monkeypatch):
    instance = app_module.App.__new__(app_module.App)
    instance._recordings_since_sweep = 0
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)
    return instance


def test_a_zero_cap_keeps_nothing_after_every_command(app, tmp_path, monkeypatch):
    """Not "nothing, eventually". The setting exists so a user can say
    their voice is not retained, and that has to be true between
    commands, not on average."""
    monkeypatch.setattr(app_module, "VOICE_RECORDING_MAX_BYTES", 0)

    for i in range(3):
        _recording(tmp_path / f"r{i}.wav")
        app._after_recording()
        assert list(tmp_path.glob("*.wav")) == [], f"kept a recording after command {i}"


def test_a_normal_cap_still_batches_its_sweeps(app, tmp_path, monkeypatch):
    """The exemption is only for zero. A sweep stats every file, which is
    not worth doing per utterance when a backlog is permitted anyway."""
    monkeypatch.setattr(app_module, "VOICE_RECORDING_MAX_BYTES", 64 * 1024 * 1024)
    monkeypatch.setattr(app_module, "VOICE_RECORDING_SWEEP_EVERY", 25)

    for i in range(3):
        _recording(tmp_path / f"r{i}.wav")
        app._after_recording()

    assert len(list(tmp_path.glob("*.wav"))) == 3


def test_a_sweep_failure_never_reaches_the_user(app, tmp_path, monkeypatch):
    """A full or read-only card must not cost the answer already given."""
    monkeypatch.setattr(app_module, "VOICE_RECORDING_MAX_BYTES", 0)
    monkeypatch.setattr(app_module.clips, "sweep",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("read-only")))

    app._after_recording()   # must not raise


# --- the cache counter --------------------------------------------------------

def test_a_cloud_answer_counts_toward_the_cache_sweep(tmp_path, monkeypatch):
    """Cloud answers are unique text written straight to the cache, so
    without this they accumulated between boots, bounded only by the
    sweep in `start()`."""
    class FakeTTS:
        def synthesize(self, text, out, language=None):
            _recording(out, kb=1)

    app = app_module.App.__new__(app_module.App)
    app._static_names = frozenset()
    app.tts, app.tts_local = FakeTTS(), None
    app.announcer = app_module.Announcer.__new__(app_module.Announcer)
    app.announcer._renders_since_sweep = 0
    app.announcer._cache_dir = tmp_path / "cache"

    monkeypatch.setattr(app_module, "CLIP_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(app_module, "MESSAGE_AUDIO_DIR", tmp_path / "messages")
    monkeypatch.setattr(app_module, "_voice_chain", lambda lang: ["piper:test"])

    app._clip_for_text("Mount Apo is 2,954 metres.", "en")

    assert app.announcer._renders_since_sweep == 1


def test_counting_is_skipped_rather_than_raising_before_the_announcer_exists(
    tmp_path, monkeypatch,
):
    """The announcer is None until the voice stack attaches one. Letting
    that raise took the *shutdown* path down with it: the goodbye failed,
    the `finally` cleared `_shutdown_requested`, and the device stayed
    on. A missed count costs a slightly later sweep; nothing else."""
    class FakeTTS:
        def synthesize(self, text, out, language=None):
            _recording(out, kb=1)

    app = app_module.App.__new__(app_module.App)
    app._static_names = frozenset()
    app.tts, app.tts_local, app.announcer = FakeTTS(), None, None

    monkeypatch.setattr(app_module, "CLIP_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(app_module, "MESSAGE_AUDIO_DIR", tmp_path / "messages")
    monkeypatch.setattr(app_module, "_voice_chain", lambda lang: ["piper:test"])

    assert app._clip_for_text("Goodbye.", "en").exists()
