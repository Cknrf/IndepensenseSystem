"""Unit tests for `Announcer` and the non-blocking cue path.

The bug this exists to prevent: navigation announcements were synthesised
and played straight from the 100 Hz loop, so fall detection and obstacle
polling stopped for ~3-4 s during every turn instruction. The first test
below is the regression test for exactly that, and it is the reason the
class exists at all.

No real audio. `synthesize` and `play` are replaced with fakes that record
what they were asked to do and can be made deliberately slow.
"""
import pathlib
import threading
import time

import pytest

import indepensense.app as app_module
from indepensense.app import Announcer
from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockVibrationMotor
from indepensense.navigation.monitor import NavigationCue


class _FakeTTS:
    """Records every synthesis, optionally taking its time about it.

    Writes the text into the file it was given, so the playback fake can
    report what actually reached the speaker. Synthesised and played are
    genuinely different lists: an announcement can be synthesised and then
    abandoned when a critical alert preempts it mid-flight.
    """

    def __init__(self, delay_s: float = 0.0):
        self.delay_s = delay_s
        self.calls: list[tuple[str, str]] = []       # (text, language)
        self._lock = threading.Lock()

    def synthesize(self, text, path, language="en"):
        if self.delay_s:
            time.sleep(self.delay_s)
        pathlib.Path(path).write_text(text)
        with self._lock:
            self.calls.append((text, language))

    def synthesised(self) -> list[str]:
        with self._lock:
            return [text for text, _ in self.calls]


@pytest.fixture
def audio(monkeypatch):
    """Replace playback and stop with recorders. Returns the record."""
    record = {"played": [], "stops": 0}

    def _play(path):
        # Mirrors the real `play`, which reads back the file `synthesize`
        # wrote — so this list is what actually reached the speaker.
        record["played"].append(pathlib.Path(path).read_text())

    def _stop():
        record["stops"] += 1

    monkeypatch.setattr(app_module, "play", _play)
    monkeypatch.setattr(app_module, "stop_playback", _stop)
    return record


@pytest.fixture
def announcer(tmp_path, audio):
    """A started announcer, stopped again at the end of the test."""
    created: list[Announcer] = []

    def _make(tts):
        instance = Announcer(tts, tmp_path)
        instance.start()
        created.append(instance)
        return instance

    yield _make
    for instance in created:
        instance.stop(timeout_s=2.0)


def _wait_until(predicate, timeout_s: float = 3.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


# --- the regression test -----------------------------------------------------

def test_say_returns_immediately_even_when_synthesis_is_slow(announcer, audio):
    """The whole point. A caller on the 100 Hz loop must not wait on audio."""
    tts = _FakeTTS(delay_s=1.0)
    a = announcer(tts)

    started = time.monotonic()
    a.say("In ninety meters, turn left", "en")
    elapsed = time.monotonic() - started

    assert elapsed < 0.05, f"say() blocked for {elapsed:.2f}s"
    assert _wait_until(lambda: audio["played"] == ["In ninety meters, turn left"])


def test_the_main_loop_cue_path_does_not_block(tmp_path, audio):
    """`_fire_navigation_cue` runs on the main loop. Firing a cue that
    speaks AND pulses every motor must still return promptly."""
    instance = MockApp()
    instance.tts = _FakeTTS(delay_s=1.0)
    instance.announcer = Announcer(instance.tts, tmp_path)
    instance.announcer.start()
    instance.front_motor = MockVibrationMotor()
    instance.left_motor = MockVibrationMotor()
    instance.right_motor = MockVibrationMotor()
    try:
        started = time.monotonic()
        instance._fire_navigation_cue(
            NavigationCue(kind="arrive", text="You have arrived.")
        )
        elapsed = time.monotonic() - started

        assert elapsed < 0.05, f"cue blocked the loop for {elapsed:.2f}s"
        # and the work still happens, just elsewhere
        assert _wait_until(lambda: instance.front_motor.events)
        assert _wait_until(lambda: audio["played"] == ["You have arrived."])
    finally:
        instance.announcer.stop(timeout_s=2.0)


# --- ordering and queueing ---------------------------------------------------

def test_announcements_are_spoken_in_order(announcer, audio):
    a = announcer(_FakeTTS())

    for text in ("first", "second", "third"):
        a.say(text, "en")

    assert _wait_until(lambda: audio["played"] == ["first", "second", "third"])


def test_the_language_is_captured_per_item(announcer):
    """The text was already rendered in one language before it got here.
    Synthesising it with a voice chosen later would pair Tagalog words with
    an English voice if the user switched in between."""
    tts = _FakeTTS(delay_s=0.05)
    a = announcer(tts)

    a.say("Kinansela na ang nabigasyon.", "tl")
    a.say("Navigation cancelled.", "en")

    assert _wait_until(lambda: len(tts.calls) == 2)
    assert tts.calls == [
        ("Kinansela na ang nabigasyon.", "tl"),
        ("Navigation cancelled.", "en"),
    ]


def test_the_queue_is_bounded_and_drops_the_oldest(tmp_path, audio):
    """A backstop, not the rate limiter — but an unbounded queue would let
    a misbehaving producer grow it without limit."""
    a = Announcer(_FakeTTS(), tmp_path)     # never started: nothing drains it
    for i in range(Announcer._MAX_PENDING + 5):
        a.say(f"item {i}", "en")

    assert a.pending_count() == Announcer._MAX_PENDING
    # The newest survived; the oldest were dropped.
    assert a._pending[-1][0] == f"item {Announcer._MAX_PENDING + 4}"


def test_clear_drops_everything_pending(tmp_path, audio):
    a = Announcer(_FakeTTS(), tmp_path)
    a.say("one", "en")
    a.say("two", "en")

    a.clear()

    assert a.pending_count() == 0


def test_empty_text_is_ignored(tmp_path, audio):
    a = Announcer(_FakeTTS(), tmp_path)
    a.say("", "en")
    assert a.pending_count() == 0


# --- critical preemption -----------------------------------------------------

def test_a_critical_alert_aborts_whatever_is_playing(tmp_path, audio):
    """Draining the queue only skips speech that has not started. A fall
    part-way through a turn instruction has to cut it off."""
    a = Announcer(_FakeTTS(), tmp_path)

    a.say("Fall detected. Alerting your guardian.", "en", critical=True)

    assert audio["stops"] == 1


def test_a_critical_alert_drops_pending_non_critical_work(tmp_path, audio):
    a = Announcer(_FakeTTS(), tmp_path)
    a.say("in ninety meters turn left", "en")
    a.say("battery low", "en")

    a.say("Fall detected.", "en", critical=True)

    assert a.pending_count() == 1
    assert a._pending[0][0] == "Fall detected."


def test_a_critical_alert_does_not_discard_another_critical_one(tmp_path, audio):
    """Two safety events in quick succession must both be heard — dropping
    one because a newer one arrived would lose the very messages this
    mechanism exists to prioritise."""
    a = Announcer(_FakeTTS(), tmp_path)
    a.say("Fall detected.", "en", critical=True)

    a.say("Battery critically low.", "en", critical=True)

    assert a.pending_count() == 2
    assert {item[0] for item in a._pending} == {
        "Fall detected.", "Battery critically low.",
    }


def test_a_critical_alert_goes_to_the_front(tmp_path, audio):
    a = Announcer(_FakeTTS(), tmp_path)
    a.say("Fall detected.", "en", critical=True)
    a.say("Battery critically low.", "en", critical=True)

    assert a._pending[0][0] == "Battery critically low."


def test_the_fall_during_an_announcement_scenario(announcer, audio):
    """End to end: a turn instruction is under way, a fall happens.

    Expected — the announcement is cut off, the pending non-critical work
    is discarded, and the fall warning is what actually reaches the speaker.

    Note the two different lists: "Your battery is low." may well have been
    *synthesised* before the alert landed. What matters is that it was never
    *played* — an in-flight announcement is abandoned after synthesis rather
    than making the alert wait it out.
    """
    tts = _FakeTTS(delay_s=0.4)
    a = announcer(tts)

    a.say("In ninety meters, turn left onto Rizal Street.", "en")
    a.say("Your battery is low.", "en")
    assert _wait_until(lambda: len(tts.calls) >= 1)      # first one is under way

    a.say("Fall detected. Alerting your guardian.", "en", critical=True)

    assert _wait_until(
        lambda: "Fall detected. Alerting your guardian." in audio["played"]
    )
    assert "Your battery is low." not in audio["played"]


# --- resilience --------------------------------------------------------------

def test_a_failing_announcement_does_not_kill_the_worker(announcer, audio):
    """Every later warning would go unspoken, with nothing to show why."""
    class _FlakyTTS(_FakeTTS):
        def synthesize(self, text, path, language="en"):
            if text == "boom":
                raise OSError("audio device gone")
            super().synthesize(text, path, language)

    tts = _FlakyTTS()
    a = announcer(tts)

    a.say("boom", "en")
    a.say("still here", "en")

    assert _wait_until(lambda: audio["played"] == ["still here"])


def test_stop_is_bounded_even_mid_playback(tmp_path, audio):
    """A worker blocked inside a long `play()` would otherwise hold up
    shutdown for the remaining length of the audio."""
    a = Announcer(_FakeTTS(delay_s=5.0), tmp_path)
    a.start()
    a.say("a very long announcement", "en")
    time.sleep(0.05)

    started = time.monotonic()
    a.stop(timeout_s=1.0)
    elapsed = time.monotonic() - started

    assert elapsed < 1.5
    assert audio["stops"] >= 1       # stop_playback was used to unblock it


def test_announcing_without_a_started_announcer_is_a_no_op():
    """Losing an announcement is not worth taking down the loop that
    detects falls."""
    instance = MockApp()
    instance.announcer = None

    instance._announce("nobody is listening")     # must not raise
