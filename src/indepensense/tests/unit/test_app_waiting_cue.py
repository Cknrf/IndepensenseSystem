"""Unit tests for the "still working on it" blip.

The gap between the stop chime and the answer is 3-7 s of silence on the
Pi — Whisper, then a 1.7B model on a CPU. A field log shows it plainly:
every `[PTT] Captured ...` line is followed by several seconds of nothing
before `[PTT] Transcript:` appears. From the user's side that is
indistinguishable from a device that has died.

Timing is compressed by patching the two intervals rather than sleeping
for real — a test that waited 1.5 s per case would add half a minute to
the suite to assert arithmetic.
"""
import threading
import time

import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp


@pytest.fixture
def ticks(monkeypatch):
    """Record blips, and make them cheap enough to assert on."""
    recorded = []
    monkeypatch.setattr(app_module, "play_waiting_tick",
                        lambda: recorded.append(time.monotonic()))
    monkeypatch.setattr(app_module, "WAITING_CUE_DELAY_S", 0.05)
    monkeypatch.setattr(app_module, "WAITING_CUE_INTERVAL_S", 0.02)
    monkeypatch.setattr(app_module, "is_playing", lambda: False)
    return recorded


@pytest.fixture
def app():
    return MockApp()


def _settle(seconds=0.12):
    time.sleep(seconds)


def test_a_long_wait_blips(app, ticks):
    with app._waiting_cue():
        _settle()

    assert ticks, "silence through a long wait"


def test_a_fast_answer_never_blips(app, ticks):
    """The common quick reply — "what time is it" — must stay clean. The
    grace period before the first blip is what buys that."""
    with app._waiting_cue():
        time.sleep(0.01)

    _settle()
    assert ticks == []


def test_blipping_stops_when_the_block_ends(app, ticks):
    """The one thing that must never happen is the blip outliving the
    wait and talking under the answer."""
    with app._waiting_cue():
        _settle()
    count = len(ticks)

    _settle(0.1)
    assert len(ticks) == count


def test_an_early_return_still_stops_it(app, ticks):
    """The pipeline returns early from inside this block on a cancel, an
    empty transcript and an emergency. A `finally` is the only thing that
    covers all of them."""
    def _pipeline():
        with app._waiting_cue():
            _settle()
            return "bailed"

    assert _pipeline() == "bailed"
    count = len(ticks)
    _settle(0.1)
    assert len(ticks) == count


def test_an_exception_still_stops_it(app, ticks):
    with pytest.raises(RuntimeError):
        with app._waiting_cue():
            _settle()
            raise RuntimeError("pipeline blew up")

    count = len(ticks)
    _settle(0.1)
    assert len(ticks) == count


def test_it_stays_quiet_while_something_is_speaking(app, ticks, monkeypatch):
    """Keeps it out of the way of "let me think about that" and of an
    obstacle warning, without either of them knowing it exists."""
    monkeypatch.setattr(app_module, "is_playing", lambda: True)

    with app._waiting_cue():
        _settle()

    assert ticks == []


def test_it_stays_quiet_while_paused(app, ticks):
    """The destination confirmation is silent *on purpose* while it waits
    for a press, so `is_playing()` cannot see it. Blipping through the
    question would read as the wearable talking over itself."""
    app._waiting_paused.set()

    with app._waiting_cue():
        _settle()

    assert ticks == []


def test_pausing_mid_wait_is_honoured(app, ticks):
    with app._waiting_cue():
        _settle()
        assert ticks, "nothing to pause"
        app._waiting_paused.set()
        count = len(ticks)
        _settle()

    assert len(ticks) == count
    app._waiting_paused.clear()


def test_a_broken_speaker_gives_up_rather_than_retrying(app, monkeypatch):
    """One log line, not one per interval for the rest of the wait."""
    calls = []

    def _explode():
        calls.append(1)
        raise OSError("output device disappeared")

    monkeypatch.setattr(app_module, "play_waiting_tick", _explode)
    monkeypatch.setattr(app_module, "WAITING_CUE_DELAY_S", 0.02)
    monkeypatch.setattr(app_module, "WAITING_CUE_INTERVAL_S", 0.01)
    monkeypatch.setattr(app_module, "is_playing", lambda: False)

    with app._waiting_cue():
        _settle()

    assert len(calls) == 1


def test_the_thread_does_not_outlive_the_block(app, ticks):
    """Daemon or not, a blip thread per voice command that never exited
    would accumulate one per press for the life of the device."""
    before = {t.name for t in threading.enumerate()}

    with app._waiting_cue():
        _settle()
    _settle(0.1)

    after = [t for t in threading.enumerate()
             if t.name == "waiting-cue" and t.name not in before]
    assert after == []
