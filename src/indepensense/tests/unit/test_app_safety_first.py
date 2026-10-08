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
import pathlib
import threading
import time

import pytest

from indepensense import app as app_module
from indepensense.app import Announcer, run_app
from indepensense.app_mock import MockApp
from indepensense.intents import messages
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


def test_a_transient_load_failure_is_retried(monkeypatch):
    """Most load failures are a bad read or a moment of memory pressure,
    and a retry is cheaper than the restart that used to be the only
    recovery — it keeps whatever already loaded."""
    app = MockApp()
    attempts = []
    real = app._open_stt

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise OSError("transient read error")
        return real()

    monkeypatch.setattr(app, "_open_stt", flaky)
    try:
        app.start()

        assert app.wait_for_voice_stack(timeout_s=5.0) is True
        assert len(attempts) == 2
        assert not app._voice_degraded.is_set()
    finally:
        app.stop()


def test_a_retry_keeps_what_already_loaded(monkeypatch):
    """Whisper is two minutes on the device. Re-loading it because TTS
    failed would make the retry cost more than the restart it replaces."""
    app = MockApp()
    stt_loads = []
    real_stt, real_tts = app._open_stt, app._open_tts
    tts_calls = []

    monkeypatch.setattr(app, "_open_stt", lambda: (stt_loads.append(1), real_stt())[1])

    def flaky_tts():
        tts_calls.append(1)
        if len(tts_calls) == 1:
            raise OSError("transient")
        return real_tts()

    monkeypatch.setattr(app, "_open_tts", flaky_tts)
    try:
        app.start()

        assert app.wait_for_voice_stack(timeout_s=5.0) is True
        assert len(stt_loads) == 1, "re-loaded Whisper on the retry"
    finally:
        app.stop()


def test_a_persistent_failure_degrades_instead_of_stopping_the_loop(monkeypatch):
    """The decision this replaced: exiting handed systemd a restart loop
    in which safety was up for eight seconds out of every ninety. Fall
    detection, obstacle warnings and the emergency button do not need a
    voice, and losing them is the worse outcome."""
    app = MockApp()
    monkeypatch.setattr(
        app, "_open_stt",
        lambda: (_ for _ in ()).throw(FileNotFoundError("no model")),
    )
    try:
        app.start()

        assert app.wait_for_voice_stack(timeout_s=5.0) is False
        assert app._voice_degraded.is_set()
        assert not app._shutdown.is_set(), "tore down a working safety loop"
        assert isinstance(app._startup_error, FileNotFoundError)
    finally:
        app.stop()


def test_degrading_still_reports_ready_to_systemd(monkeypatch, notify_socket):
    """Under `Type=notify` a unit that never reports is killed at
    `TimeoutStartSec`. Staying quiet would turn a degraded device into a
    dead one fifteen minutes later."""
    app = MockApp()
    monkeypatch.setattr(
        app, "_open_stt",
        lambda: (_ for _ in ()).throw(FileNotFoundError("no model")),
    )
    try:
        app.start()
        app.wait_for_voice_stack(timeout_s=5.0)

        assert any("READY=1" in m for m in notify_socket()), "never reported ready"
    finally:
        app.stop()


def test_a_degraded_ptt_press_says_so_rather_than_sounding_busy(monkeypatch):
    """The busy cue means "wait", and waiting will not help. Someone
    pressing every ten seconds would be answered by a sound that lies."""
    app = MockApp()
    said, cues = [], []
    monkeypatch.setattr(app, "_announce", lambda text, **kw: said.append(text))
    monkeypatch.setattr(app, "_play_cue", lambda cue: cues.append(cue))
    app._voice_degraded.set()

    app._on_ptt_press()

    assert cues == []
    assert said == [messages.get("system.voice_unavailable", "en")]


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


# --- systemd readiness ---------------------------------------------------------

@pytest.fixture
def notify_socket(monkeypatch):
    """A unix datagram socket standing in for systemd's NOTIFY_SOCKET.

    Not under `tmp_path`: pytest's directory names push the path past
    the 104-byte limit AF_UNIX allows on macOS.
    """
    import shutil
    import socket
    import tempfile
    directory = tempfile.mkdtemp()
    path = pathlib.Path(directory) / "notify.sock"
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(path))
    sock.settimeout(0.5)
    monkeypatch.setenv("NOTIFY_SOCKET", str(path))

    def received():
        got = []
        try:
            while True:
                got.append(sock.recv(4096).decode())
        except (socket.timeout, TimeoutError):
            pass
        return got

    yield received
    sock.close()
    shutil.rmtree(directory, ignore_errors=True)


def test_ready_is_signalled_only_once_the_voice_stack_is_loaded(held, notify_socket):
    app, release, entered, _ = held
    app.start()
    entered.wait(2.0)

    before = notify_socket()
    assert all("READY=1" not in m for m in before), before
    assert any(m.startswith("STATUS=") for m in before), "no progress reported"

    release.set()
    app.wait_for_voice_stack(timeout_s=3.0)

    assert any("READY=1" in m for m in notify_socket())


def test_notify_is_a_no_op_off_systemd(monkeypatch):
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    app_module._notify_systemd("READY=1")            # must not raise


def test_a_dead_notify_socket_does_not_break_startup(monkeypatch, tmp_path):
    monkeypatch.setenv("NOTIFY_SOCKET", str(tmp_path / "nobody-listens"))
    app_module._notify_systemd("STATUS=anything")    # must not raise
