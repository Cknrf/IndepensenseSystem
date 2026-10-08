"""Safety features come up before the voice stack loads.

Measured on the Pi, Whisper, the TTS voices, the embedding model and
YOLO took ~200 s to load from the SD card, and `start()` loaded all of
them before it opened a single button. For that long at every boot there
was no fall detection, no obstacle warning and no emergency button —
none of which needs a model. `start()` now opens the safety devices and
returns; the models load on the one-shot `voice-stack` thread while the
loop runs.

These tests hold the Whisper load open and check what works underneath
it, what is refused, and what happens when a load fails or a shutdown
arrives part-way through.
"""
import threading
import time

import pytest

from indepensense import app as app_module
from indepensense.app import Announcer, run_app
from indepensense.app_mock import MockApp
from indepensense.voice.mock import MockSTT, MockTTS


def _wait_for(condition, timeout_s=3.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def held(monkeypatch):
    """A mock app whose Whisper load blocks until the test releases it."""
    app = MockApp()
    release = threading.Event()
    entered = threading.Event()
    greetings = []

    def open_stt():
        entered.set()
        release.wait(timeout=5.0)
        return MockSTT()

    monkeypatch.setattr(app, "_open_stt", open_stt)
    monkeypatch.setattr(app, "_render_boot_clips", lambda: None)
    monkeypatch.setattr(app, "_speak_greeting", lambda: greetings.append(True))
    monkeypatch.setattr(app, "_announce_battery_status", lambda: None)
    yield app, release, entered, greetings
    release.set()
    app._shutdown.set()
    app.stop()


def test_the_safety_devices_are_open_before_whisper_has_loaded(held):
    app, _release, entered, _ = held

    app.start()                                 # returns with the load held

    assert entered.wait(2.0), "the loader never reached Whisper"
    assert app.imu is not None
    assert app.top_sensor is not None and app.bottom_sensor is not None
    assert app.emergency_button is not None and app.ptt_button is not None
    assert app.front_motor is not None and app.buzzer is not None
    assert app.alert_sink is not None, "no alert path while the models load"
    assert app.stt is None and app.tts is None and app.parser is None
    assert not app._voice_stack_ready.is_set()


def test_a_ptt_press_while_loading_gets_the_busy_cue(held, monkeypatch):
    app, _release, entered, _ = held
    cues = []
    monkeypatch.setattr(app, "_play_cue", lambda cue: cues.append(cue))
    app.start()
    entered.wait(2.0)

    app.ptt_button.press()

    assert cues == [app_module.play_busy_cue]
    assert app._voice_thread is None, "a voice cycle started with no STT"


def test_an_emergency_press_while_loading_still_sends_the_alert(held, monkeypatch):
    app, _release, entered, _ = held
    spoken = []
    monkeypatch.setattr(app, "_announce",
                        lambda text, critical=False: spoken.append(text))
    app.start()
    entered.wait(2.0)

    app.emergency_button.press()

    assert _wait_for(lambda: len(app.buffered._inner.alerts) == 1)
    assert spoken, "the wearer heard nothing about the alert"


def test_the_voice_stack_is_ready_once_the_loads_finish(held):
    app, release, entered, greetings = held
    app.start()
    entered.wait(2.0)
    assert greetings == [], "ready was announced before anything loaded"

    release.set()

    assert app.wait_for_voice_stack(timeout_s=3.0)
    assert app.stt is not None and app.tts is not None and app.parser is not None
    assert app.announcer._tts is app.tts
    assert app.executor._camera is app.camera
    assert greetings == [True]


def test_a_shutdown_during_the_load_does_not_wait_for_it(held):
    app, release, entered, _ = held
    app.start()
    entered.wait(2.0)

    started = time.monotonic()
    app._shutdown.set()
    app.stop()

    assert time.monotonic() - started < 4.0
    release.set()
    app.wait_for_voice_stack(timeout_s=3.0)
    assert app.tts is None, "the loader carried on after the shutdown"


def test_a_model_that_fails_to_load_stops_the_runtime(monkeypatch):
    app = MockApp()

    def broken():
        raise FileNotFoundError("Whisper 'small' for 'tl' not found")

    monkeypatch.setattr(app, "_open_stt", broken)
    try:
        app.start()

        assert app.wait_for_voice_stack(timeout_s=3.0) is False
        assert app._shutdown.is_set(), "the loop was left running without a voice"
        assert isinstance(app._startup_error, FileNotFoundError)
    finally:
        app.stop()


def test_run_app_exits_non_zero_when_a_model_failed_to_load(monkeypatch, tmp_path):
    """The `_open_*` contract survives the move off the main thread: a
    missing model still fails the process, so systemd restarts it with
    the error in the journal rather than leaving a voiceless wearable."""
    app = MockApp()
    monkeypatch.setattr(app_module, "VOICE_TEST_DIR", tmp_path)

    def broken():
        raise FileNotFoundError("no model")

    monkeypatch.setattr(app, "_open_stt", broken)

    with pytest.raises(SystemExit) as exited:
        run_app(app)

    assert exited.value.code == 1


# --- the announcer without a voice --------------------------------------------

def test_the_announcer_holds_speech_until_a_voice_is_attached(tmp_path, monkeypatch):
    played = []
    monkeypatch.setattr(app_module, "play", lambda path: played.append(path))
    announcer = Announcer(None, tmp_path / "messages", tmp_path / "cache")
    announcer.start()
    try:
        announcer.say("nothing rendered for this", "en")
        time.sleep(0.3)
        assert played == [], "spoke with no engine to synthesise"

        announcer.attach_tts(MockTTS())

        assert _wait_for(lambda: len(played) == 1)
    finally:
        announcer.stop()


def test_stopping_a_voiceless_announcer_does_not_hang(tmp_path):
    announcer = Announcer(None, tmp_path / "messages", tmp_path / "cache")
    announcer.start()
    announcer.say("held forever otherwise", "en")

    started = time.monotonic()
    announcer.stop(timeout_s=2.0)

    assert time.monotonic() - started < 2.0
    assert not announcer._thread.is_alive()

