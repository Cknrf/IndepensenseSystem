"""Unit tests for how long push-to-talk recordings are kept.

`VOICE_TEST_DIR` collected one `{timestamp}_command.wav` per utterance
and nothing ever reclaimed any of it — 32 KB per second of speech,
forever, on a card that has already shown write corruption, holding the
recorded voice of a user who cannot see what the device is storing.

The fix is a cap rather than a delete, and that asymmetry is the thing
worth pinning: `voice.tests.manual.latency_bench` replays these exact
files to produce the thesis's STT and NLU timings, so a pipeline that
tidied up after itself would take the quantitative latency claim with
it. These tests cover both halves — that the directory stays bounded,
and that it is not emptied.

**The clock is stubbed, and has to be.** Recordings are named from
`datetime.now()` at second resolution, so six cycles in a millisecond of
test time all write the same filename and overwrite each other. Every
assertion below would pass against a directory holding exactly one file,
measuring nothing. On the device the resolution is ample — a cycle
cannot complete in under a second — but here it has to be forced.
"""
from datetime import datetime, timedelta

import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.intents.base import Intent, IntentResult
from indepensense.voice.base import Transcript, TranscriptSegment

# Each stubbed recording is this many bytes, and the cap is two and a
# half of them — so a sweep leaves exactly the two newest.
_RECORDING_BYTES = 1000
_CAP_BYTES = 2500


class _STT:
    def transcribe(self, path, language="en", initial_prompt=None):
        return Transcript(
            text="what time is it", language=language,
            segments=[TranscriptSegment(text="x", start_s=0, end_s=1)],
        )


class _Parser:
    def parse(self, text):
        return IntentResult(intent=Intent.SYSTEM_TIME)


class _Executor:
    def execute(self, result):
        return "It is three o'clock."


class _Engine:
    def synthesize(self, text, path, language=None):
        path.write_bytes(b"RIFF....WAVE")


class _Clock:
    """A `datetime` stand-in whose `now()` advances a second per call.

    Only the naked `now()` is faked. A call with a timezone is the alert
    path asking for a real wall-clock instant, which has nothing to do
    with filenames and must not be frozen underneath it.
    """

    def __init__(self):
        self._t = datetime(2026, 10, 13, 9, 0, 0)

    def now(self, tz=None):
        if tz is not None:
            return datetime.now(tz)
        self._t += timedelta(seconds=1)
        return self._t


@pytest.fixture
def app(monkeypatch, tmp_path):
    """A pipeline whose recorder writes a file of a known size.

    The real `record_until_button` writes the WAV, so the stub has to as
    well — otherwise there is no retention to measure.
    """
    instance = MockApp()
    instance.cloud = None
    instance.stt = _STT()
    instance.parser = _Parser()
    instance.executor = _Executor()
    instance.tts = _Engine()

    def _record(button, path, **kwargs):
        path.write_bytes(b"\0" * _RECORDING_BYTES)
        return 3.0

    monkeypatch.setattr(app_module, "record_until_button", _record)
    monkeypatch.setattr(app_module, "play", lambda path: None)
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)
    monkeypatch.setattr(app_module, "datetime", _Clock())
    monkeypatch.setattr(instance, "_play_press_feedback",
                        lambda rising_chime: None)
    monkeypatch.setattr(app_module, "VOICE_RECORDING_SWEEP_EVERY", 2)
    monkeypatch.setattr(app_module, "VOICE_RECORDING_MAX_BYTES", _CAP_BYTES)
    return instance, tmp_path


def _run(app, n=1):
    for _ in range(n):
        app._voice_active.set()
        app._voice_cancel.clear()
        app._voice_pipeline()


def _recordings(directory):
    return sorted(directory.glob("*_command.wav"))


# --- the clock stub is load-bearing ------------------------------------------

def test_each_cycle_writes_its_own_recording(app):
    """Guards the harness itself. Without the clock stub every cycle
    writes the same filename and every test below passes against one
    file, which is not a measurement of anything."""
    instance, directory = app

    _run(instance, n=2)

    assert len(_recordings(directory)) == 2


# --- the cap holds -----------------------------------------------------------

def test_recordings_stop_accumulating_once_the_cap_is_reached(app):
    """The whole point. Without this the directory is a monotonic record
    of everything the user has ever said to the device."""
    instance, directory = app

    _run(instance, n=10)

    retained = sum(p.stat().st_size for p in _recordings(directory))
    assert retained <= _CAP_BYTES
    assert len(_recordings(directory)) == 2


def test_the_newest_recordings_are_the_ones_kept(app):
    """Oldest-first, so what survives is the most recent session — which
    is what a benchmark run or a field-failure diagnosis wants."""
    instance, directory = app

    _run(instance, n=2)
    first_two = [p.name for p in _recordings(directory)]
    _run(instance, n=4)
    survivors = [p.name for p in _recordings(directory)]

    assert not set(survivors) & set(first_two), "oldest should have gone"
    assert survivors == sorted(survivors)


# --- but the corpus is not emptied -------------------------------------------

def test_a_recording_survives_the_cycle_that_made_it(app):
    """A delete-after-transcribe would satisfy every cap test above and
    silently break `latency_bench`, which replays `*_command.wav`."""
    instance, directory = app

    _run(instance, n=1)

    assert len(_recordings(directory)) == 1


def test_a_generous_cap_discards_nothing(app, monkeypatch):
    """Guards the opposite failure: a sweep that deleted regardless of
    size would make retention a function of the counter rather than the
    cap, and the cap is the part that is argued for in config."""
    instance, directory = app
    monkeypatch.setattr(app_module, "VOICE_RECORDING_MAX_BYTES",
                        10 * 1024 * 1024)

    _run(instance, n=6)

    assert len(_recordings(directory)) == 6


# --- the cadence -------------------------------------------------------------

def test_the_sweep_does_not_run_on_every_utterance(app, monkeypatch):
    """A sweep stats every file in the directory. Doing that after every
    command would spend syscalls on a directory that moved by one file."""
    instance, _ = app
    sweeps = []
    monkeypatch.setattr(app_module.clips, "sweep",
                        lambda d, cap: sweeps.append(d) or 0)

    _run(instance, n=4)

    assert len(sweeps) == 2, "every second utterance, at SWEEP_EVERY=2"


def test_a_cancelled_cycle_still_counts_towards_the_sweep(app, monkeypatch):
    """It wrote a recording like any other. Counting only the cycles that
    finished would let someone who keeps pressing stop fill the card
    without the cap ever being consulted."""
    instance, _ = app
    sweeps = []
    monkeypatch.setattr(app_module.clips, "sweep",
                        lambda d, cap: sweeps.append(d) or 0)

    for _ in range(2):
        instance._voice_active.set()
        instance._voice_cancel.set()      # cancelled before transcription
        instance._voice_pipeline()

    assert len(sweeps) == 1


# --- failure containment -----------------------------------------------------

def test_a_failing_sweep_does_not_break_the_voice_cycle(app, monkeypatch):
    """A full or read-only card must not cost the user their answer. By
    the time this runs they have already heard it."""
    instance, _ = app

    def _boom(directory, cap):
        raise OSError("read-only filesystem")

    monkeypatch.setattr(app_module.clips, "sweep", _boom)

    _run(instance, n=2)   # must not raise
