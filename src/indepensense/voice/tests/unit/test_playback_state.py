"""Unit tests for playback state tracking in `voice/audio.py`.

`is_playing()` is what lets the repeat button tell "stop talking" from
"repeat" without knowing which subsystem started the audio. If the flag
ever leaked — stayed set after playback ended — every later stop press
would be swallowed and the button would look broken.

`sounddevice` and `soundfile` are stubbed into `sys.modules`, so this
exercises the real `play` on a machine with no audio stack at all. The
lazy imports inside `play` are what make that possible.
"""
import sys
import threading
import types

import pytest

from indepensense.voice import audio


class _FakeSoundDevice(types.ModuleType):
    """Records playback, and can be told to block or to fail."""

    def __init__(self):
        super().__init__("sounddevice")
        self.played = []
        self.stops = 0
        self.block_until = None        # threading.Event, if set
        self.raise_on_play = False

    def play(self, data, samplerate=None, blocking=False):
        if self.raise_on_play:
            raise RuntimeError("no output device")
        self.played.append(samplerate)
        if self.block_until is not None:
            self.block_until.wait(timeout=5.0)

    def stop(self):
        self.stops += 1
        if self.block_until is not None:
            self.block_until.set()


class _FakeSoundFile(types.ModuleType):
    def __init__(self):
        super().__init__("soundfile")

    def read(self, path):
        return ([0, 0, 0], 22050)

    def write(self, *args, **kwargs):
        pass


@pytest.fixture
def fake_audio(monkeypatch, tmp_path):
    sd = _FakeSoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setitem(sys.modules, "soundfile", _FakeSoundFile())
    # Any pre-existing flag state must not leak between tests.
    audio._playing.clear()
    yield sd
    audio._playing.clear()


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "speech.wav"
    path.write_bytes(b"")           # the fake reader never looks at it
    return path


def test_nothing_is_playing_to_begin_with(fake_audio):
    assert audio.is_playing() is False


def test_the_flag_is_set_while_playing_and_cleared_after(fake_audio, wav):
    seen = []
    fake_audio.block_until = threading.Event()

    worker = threading.Thread(target=audio.play, args=(wav,), daemon=True)
    worker.start()

    deadline = threading.Event()
    for _ in range(200):                       # up to ~2 s
        if audio.is_playing():
            seen.append(True)
            break
        deadline.wait(0.01)

    assert seen == [True], "flag was never set during playback"

    fake_audio.block_until.set()
    worker.join(timeout=2.0)
    assert audio.is_playing() is False, "flag leaked after playback ended"


def test_the_flag_is_cleared_when_playback_is_aborted(fake_audio, wav):
    """`stop_playback` cuts `play` short. If the flag survived that, the
    wearable would believe it was still talking forever."""
    fake_audio.block_until = threading.Event()

    worker = threading.Thread(target=audio.play, args=(wav,), daemon=True)
    worker.start()
    for _ in range(200):
        if audio.is_playing():
            break
        threading.Event().wait(0.01)

    audio.stop_playback()
    worker.join(timeout=2.0)

    assert fake_audio.stops == 1
    assert audio.is_playing() is False


def test_the_flag_is_cleared_when_playback_raises(fake_audio, wav):
    fake_audio.raise_on_play = True

    with pytest.raises(RuntimeError):
        audio.play(wav)

    assert audio.is_playing() is False


def test_a_chime_does_not_count_as_speaking(fake_audio):
    """A chime is ~120 ms of acknowledgement tone. Counting it would make a
    stop press land on nothing in the gap after a PTT press."""
    pytest.importorskip("numpy")
    audio.play_chime(rising=True)

    assert audio.is_playing() is False


def test_stop_playback_is_safe_when_nothing_is_playing(fake_audio):
    audio.stop_playback()
    assert fake_audio.stops == 1        # a no-op in PortAudio, not an error


def test_stop_playback_never_raises(monkeypatch, fake_audio):
    """Interrupting speech must not itself become a failure."""
    def _boom():
        raise OSError("stream gone")

    monkeypatch.setattr(fake_audio, "stop", _boom)
    audio.stop_playback()               # must not raise
