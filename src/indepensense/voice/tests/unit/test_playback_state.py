"""Unit tests for playback state tracking in `voice/audio.py`.

`is_playing()` is what lets the repeat button tell "stop talking" from
"repeat" without knowing which subsystem started the audio. If the flag
ever leaked — stayed set after playback ended — every later stop press
would be swallowed and the button would look broken.

The fakes live in `conftest.py`; see `test_audio_playback.py` for the
stream-ownership properties they were built to check.
"""
import threading

import pytest

from indepensense.voice import audio


def _wait_until(predicate, timeout_s: float = 2.0) -> bool:
    deadline = threading.Event()
    for _ in range(int(timeout_s / 0.01)):
        if predicate():
            return True
        deadline.wait(0.01)
    return predicate()


def test_nothing_is_playing_to_begin_with(fake_sd):
    assert audio.is_playing() is False


def test_the_flag_is_set_while_playing_and_cleared_after(fake_sd, wav):
    fake_sd.write_gate = threading.Event()      # hold playback inside the stream

    worker = threading.Thread(target=audio.play, args=(wav,), daemon=True)
    worker.start()

    assert _wait_until(audio.is_playing), "flag was never set during playback"

    fake_sd.write_gate.set()
    worker.join(timeout=2.0)
    assert audio.is_playing() is False, "flag leaked after playback ended"


def test_the_flag_is_cleared_when_playback_is_cut_short(fake_sd, fake_sf, wav):
    """`stop_playback` ends `play` early. If the flag survived that, the
    wearable would believe it was still talking forever."""
    fake_sf.frames = audio._BLOCK_FRAMES * 10
    fake_sd.after_write = audio.stop_playback

    audio.play(wav)

    assert fake_sd.streams[0].aborted == 1
    assert audio.is_playing() is False


def test_the_flag_is_cleared_when_playback_raises(fake_sd, wav):
    fake_sd.raise_on_write = True

    with pytest.raises(RuntimeError):
        audio.play(wav)

    assert audio.is_playing() is False


def test_a_chime_does_not_count_as_speaking(fake_sd):
    """A chime is ~120 ms of acknowledgement tone. Counting it would make a
    stop press land on nothing in the gap after a PTT press."""
    pytest.importorskip("numpy")
    audio.play_chime(rising=True)

    assert audio.is_playing() is False


def test_stop_playback_is_safe_when_nothing_is_playing(fake_sd):
    audio.stop_playback()           # a request with no speaker to cancel

    assert audio.is_playing() is False
    assert fake_sd.streams == []
