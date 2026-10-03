"""`_warning_lock` must never be held across a blocking audio call.

The lock serialises motor and buzzer patterns so two events cannot leave
a motor stuck on. Audio has its own lock, inside `voice/audio.py`, and
the announcer holds that one for a whole utterance — thirty seconds on an
OCR read.

`_play_press_feedback` used to hold `_warning_lock` across `play_chime`,
which joins the two. A PTT press during a long utterance then froze:

  * gpiozero's callback thread, so the button stopped responding
  * `_play_emergency_feedback`, so the emergency buzzer could not fire
  * every obstacle warning pattern

Reported from the field as "the whole program gets stuck and PTT won't
work any more". The emergency buzzer being blocked by a chime is the part
that matters: it is the output that has to work when nothing else does.
"""
import inspect
import threading

import pytest

from indepensense.app import App

# Anything that can block on the audio layer's own lock.
_AUDIO_CALLS = (
    "play_chime", "play_cue", "play_stop_cue", "play_busy_cue",
    "play_waiting_tick", "self._announce", "self._speak",
)


def _warning_lock_blocks(source: str) -> list[str]:
    """Return the body of each `with self._warning_lock:` block."""
    lines = source.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if "with self._warning_lock:" not in line:
            continue
        indent = len(line) - len(line.lstrip())
        body = []
        for following in lines[index + 1:]:
            if following.strip() and (len(following) - len(following.lstrip())) <= indent:
                break
            body.append(following)
        blocks.append("\n".join(body))
    return blocks


@pytest.mark.parametrize("name", [
    "_play_press_feedback",
    "_play_emergency_feedback",
    "_play_warning_pattern",
    "_play_button_ack",
    "_spawn_haptic",
])
def test_no_audio_runs_while_the_warning_lock_is_held(name):
    source = inspect.getsource(getattr(App, name))

    for body in _warning_lock_blocks(source):
        for call in _AUDIO_CALLS:
            assert call not in body, (
                f"{name} holds _warning_lock across {call}() — a long "
                "utterance would freeze the emergency buzzer with it"
            )


def test_the_press_feedback_still_pulses_and_chimes():
    """The fix narrows the lock; it must not drop either half."""
    source = inspect.getsource(App._play_press_feedback)

    assert "_pulse_all_motors" in source
    assert "play_chime" in source
    assert "with self._warning_lock:" in source, (
        "the motor pulse still needs serialising — only the chime moved out"
    )


def test_a_blocked_chime_cannot_hold_up_the_emergency_buzzer():
    """The cascade itself, reproduced against the real lock.

    A chime that never returns must not stop an emergency acknowledgement
    acquiring `_warning_lock`. Guards the behaviour rather than the text,
    so a future refactor that reintroduces the coupling by another route
    still fails.
    """
    app = App.__new__(App)                 # no hardware, no start()
    app._warning_lock = threading.Lock()
    app.buzzer = None
    app.left_motor = app.right_motor = app.front_motor = None

    stuck = threading.Event()
    entered = threading.Event()

    def _never_returns(**_kwargs):
        entered.set()
        stuck.wait(timeout=5.0)            # as a stalled audio write would

    app._pulse_all_motors = lambda duration_s=0.0: None

    import indepensense.app as app_module
    original = app_module.play_chime
    app_module.play_chime = _never_returns
    try:
        presser = threading.Thread(target=app._play_press_feedback,
                                   kwargs={"rising_chime": True})
        presser.start()
        assert entered.wait(timeout=2.0), "the chime never ran"

        # The emergency path only needs the haptics lock. With the chime
        # wedged it must still get it, promptly.
        done = threading.Event()
        threading.Thread(
            target=lambda: (app._play_emergency_feedback(), done.set()),
        ).start()

        assert done.wait(timeout=2.0), (
            "the emergency acknowledgement was blocked by a stalled chime"
        )
    finally:
        app_module.play_chime = original
        stuck.set()
        presser.join(timeout=2.0)
