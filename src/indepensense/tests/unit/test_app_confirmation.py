"""Unit tests for `App._confirm_destination`.

The executor decides whether to ask and what to do with the answer
(`intents/tests/unit/test_executor.py`). This covers the half that talks
to hardware: speak the question, borrow the PTT button, wait, hand it
back.

Timing matters here in a way it usually doesn't, so the confirmation
window is shortened per test rather than waiting out the real 4 s.
"""
import threading
import time

import pytest

from indepensense.app_mock import MockApp
from indepensense.feedback.mock import MockButton


class _SilentApp(MockApp):
    """Captures the spoken question instead of synthesising audio.

    `_confirm_destination` speaks through `_speak_error`, the same
    best-effort helper the navigation cues use. Overriding it keeps these
    tests off the audio stack while the wait logic itself runs for real.
    """

    def __init__(self):
        super().__init__()
        self.spoken: list[str] = []

    def _speak_error(self, message: str) -> None:
        self.spoken.append(message)


@pytest.fixture
def app():
    instance = _SilentApp()
    instance.ptt_button = MockButton()
    # Register the handler `start()` would have installed, so we can prove
    # the borrowed button is handed back to the right owner.
    instance.ptt_button.on("pressed", instance._on_ptt_press)
    return instance


def _press_after(app, delay_s: float) -> threading.Thread:
    """Press PTT from another thread, the way a user would mid-wait."""
    def _run():
        time.sleep(delay_s)
        app.ptt_button.press()

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    return thread


# --- the two answers ---------------------------------------------------------

def test_a_press_within_the_window_confirms(app, monkeypatch):
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 2.0)
    _press_after(app, 0.1)

    assert app._confirm_destination("Jollibee Manila. Press the left button.") is True


def test_silence_declines(app, monkeypatch):
    """The prototype has no spare button for "no", so a timeout is the
    decline — and it fails in the safe direction."""
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 0.2)

    assert app._confirm_destination("Jollibee Manila?") is False


def test_the_question_is_spoken_before_waiting(app, monkeypatch):
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 0.1)
    app._confirm_destination("Is this correct?")

    assert app.spoken == ["Is this correct?"]


def test_it_returns_as_soon_as_the_button_is_pressed(app, monkeypatch):
    """A yes must not sit out the rest of the window — that delay is the
    latency the button approach exists to avoid."""
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 5.0)
    _press_after(app, 0.1)

    started = time.monotonic()
    app._confirm_destination("Is this correct?")

    assert time.monotonic() - started < 1.0


# --- borrowing the button ----------------------------------------------------

def test_the_ptt_handler_is_restored_after_confirming(app, monkeypatch):
    """The next press has to start a new voice command, not re-confirm a
    destination that is already being navigated to."""
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 0.2)
    app._confirm_destination("Is this correct?")

    assert app.ptt_button._handlers["pressed"] == app._on_ptt_press


def test_the_ptt_handler_is_restored_even_when_speaking_fails(app, monkeypatch):
    """Leaving the button borrowed would strand the user with a device that
    no longer responds to PTT at all."""
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 0.2)

    def _broken(message):
        raise OSError("audio device gone")

    monkeypatch.setattr(app, "_speak_error", _broken)

    with pytest.raises(OSError):
        app._confirm_destination("Is this correct?")

    assert app.ptt_button._handlers["pressed"] == app._on_ptt_press


# --- emergency preemption ----------------------------------------------------

def test_an_emergency_mid_wait_declines(app, monkeypatch):
    """The emergency path is already speaking and alerting. Starting
    turn-by-turn navigation on top of it would be absurd."""
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 5.0)

    def _cancel_soon():
        time.sleep(0.1)
        app._voice_cancel.set()

    threading.Thread(target=_cancel_soon, daemon=True).start()

    started = time.monotonic()
    assert app._confirm_destination("Is this correct?") is False
    assert time.monotonic() - started < 1.0    # bailed early, didn't wait it out


def test_an_emergency_before_the_question_declines(app, monkeypatch):
    monkeypatch.setattr("indepensense.app.DESTINATION_CONFIRM_TIMEOUT_S", 5.0)
    app._voice_cancel.set()

    assert app._confirm_destination("Is this correct?") is False


# --- degraded hardware -------------------------------------------------------

def test_no_button_proceeds_without_asking(app):
    """Reachable only in degraded setups — a PTT press is what starts a
    voice command, so the button exists whenever this runs. Refusing would
    make navigation impossible rather than merely unconfirmed."""
    app.ptt_button = None

    assert app._confirm_destination("Is this correct?") is True
    assert app.spoken == []
