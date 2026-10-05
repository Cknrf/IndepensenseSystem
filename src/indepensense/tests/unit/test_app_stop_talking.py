"""Unit tests for the dual-purpose repeat button.

Until this existed nothing could interrupt the wearable. `vision.read` on
a menu is thirty seconds of Piper and `sd.play` blocks with no interrupt,
so the only recourse was to wait it out or power the device off.

The button now means "stop" while it is talking and "repeat" while it is
not. These tests cover that split, that stopping reaches both the speaker
and the queue, and that the pre-existing repeat behaviour is unchanged.
"""
import pytest

from indepensense import app as app_module
from indepensense.app_mock import MockApp
from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.routing.mock import MockGeocoder, MockRouter


class _SpyAnnouncer:
    def __init__(self):
        self.said: list[tuple[str, bool]] = []
        self.clears = 0

    def say(self, text, language, critical=False):
        self.said.append((text, critical))

    def clear(self):
        self.clears += 1


class _SpyExecutor:
    """Returns a canned response and records what it was asked to do."""

    def __init__(self, response="the last thing I said"):
        self.response = response
        self.intents: list[Intent] = []

    def emergency_acknowledgement(self) -> str:
        # Present so the emergency path takes the branch that ships.
        # Without it `_on_emergency_press` logs and falls back to
        # announcing after dispatch — the pre-fix behaviour — so the
        # test would pass while exercising the wrong code.
        return self.response

    def execute(self, result: IntentResult) -> str:
        self.intents.append(result.intent)
        return self.response


@pytest.fixture
def app(monkeypatch):
    instance = MockApp()
    instance.announcer = _SpyAnnouncer()
    instance.executor = _SpyExecutor()
    # Motor ack would otherwise sleep; it is covered elsewhere.
    monkeypatch.setattr(instance, "_play_button_ack", lambda: None)
    return instance


def _playing(monkeypatch, value: bool):
    monkeypatch.setattr(app_module, "is_playing", lambda: value)


@pytest.fixture(autouse=True)
def cues(monkeypatch):
    """Records which audio cue was played, and keeps the suite silent.

    Autouse because every press now answers with one — left real, these
    tests would open a PortAudio stream and emit tones on the dev
    machine, and a swallowed exception would hide which cue was chosen.
    """
    played: list[str] = []
    monkeypatch.setattr(app_module, "play_stop_cue", lambda: played.append("stop"))
    monkeypatch.setattr(app_module, "play_busy_cue", lambda: played.append("busy"))
    return played


@pytest.fixture
def stopped(monkeypatch):
    """Records calls to `stop_playback`."""
    record = {"stops": 0}
    monkeypatch.setattr(
        app_module, "stop_playback",
        lambda: record.__setitem__("stops", record["stops"] + 1),
    )
    return record


# --- stopping ----------------------------------------------------------------

def test_a_press_while_talking_stops_the_speaker(app, monkeypatch, stopped):
    _playing(monkeypatch, True)

    app._on_repeat_press()

    assert stopped["stops"] == 1


def test_stopping_also_drops_what_is_queued(app, monkeypatch, stopped):
    """Aborting playback alone would let the next queued announcement start
    a moment later, which reads as the button not working."""
    _playing(monkeypatch, True)

    app._on_repeat_press()

    assert app.announcer.clears == 1


def test_stopping_does_not_also_repeat(app, monkeypatch, stopped):
    """One press, one meaning. Speaking again right after being told to be
    quiet is the opposite of what was asked."""
    _playing(monkeypatch, True)

    app._on_repeat_press()

    assert app.executor.intents == []
    assert app.announcer.said == []


def test_stopping_works_while_the_voice_pipeline_is_busy(app, monkeypatch, stopped):
    """The case this feature exists for: `vision.read` is reading out a
    menu on the voice thread, so `_voice_active` is set. The old guard
    ignored the press outright, which is exactly when the user most wants
    it to land."""
    _playing(monkeypatch, True)
    app._voice_active.set()

    app._on_repeat_press()

    assert stopped["stops"] == 1


def test_a_missing_announcer_does_not_break_stopping(app, monkeypatch, stopped):
    _playing(monkeypatch, True)
    app.announcer = None

    app._on_repeat_press()

    assert stopped["stops"] == 1


# --- repeating (unchanged behaviour) -----------------------------------------

def test_a_press_while_silent_repeats(app, monkeypatch, stopped):
    _playing(monkeypatch, False)

    app._on_repeat_press()

    assert app.executor.intents == [Intent.NAVIGATION_REPEAT]
    assert app.announcer.said == [("the last thing I said", False)]
    assert stopped["stops"] == 0


def test_the_repeat_is_not_critical(app, monkeypatch, stopped):
    """A user asking to hear something again is not an emergency — it must
    not preempt a warning that is queued behind it."""
    _playing(monkeypatch, False)

    app._on_repeat_press()

    assert app.announcer.said[0][1] is False


def test_a_press_while_silent_but_mid_command_is_still_ignored(app, monkeypatch, stopped):
    """Pre-existing behaviour: the pipeline is between stages (recording,
    transcribing) with nothing yet to repeat or interrupt."""
    _playing(monkeypatch, False)
    app._voice_active.set()

    app._on_repeat_press()

    assert app.executor.intents == []


def test_a_raising_executor_does_not_propagate(app, monkeypatch, stopped):
    """This runs on a gpiozero callback thread; an escape would be silent."""
    _playing(monkeypatch, False)

    class _Broken:
        def execute(self, result):
            raise RuntimeError("executor exploded")

    app.executor = _Broken()
    app._on_repeat_press()


def test_repeat_after_a_stop_replays_the_cancelled_response(app, monkeypatch, stopped):
    """Someone who stopped a sentence for a passing jeepney wants *that*
    sentence again, not the one before it. Stopping never touches the
    executor, so its last response is still the cancelled one."""
    executor = IntentExecutor(router=MockRouter(), geocoder=MockGeocoder())
    app.executor = executor
    original = executor.execute(IntentResult(Intent.SYSTEM_TIME))

    _playing(monkeypatch, True)
    app._on_repeat_press()              # stop it mid-sentence

    _playing(monkeypatch, False)
    app._on_repeat_press()              # ask again

    assert app.announcer.said == [(original, False)]


# --- the emergency confirmation now goes through the announcer ---------------

def test_the_emergency_confirmation_is_announced_critically(app, monkeypatch):
    """It used to synthesise and play on gpiozero's callback thread, making
    it a second uncoordinated speaker that could talk over the announcer."""
    monkeypatch.setattr(app, "_play_emergency_feedback", lambda: None)
    app.executor = _SpyExecutor(response="Emergency alert sent.")

    app._on_emergency_press()

    assert app.executor.intents == [Intent.EMERGENCY_TRIGGER]
    assert app.announcer.said == [("Emergency alert sent.", True)]


# --- the press always answers ------------------------------------------------
#
# Interrupting is silent by design — silence is what was asked for — but
# silence is also exactly what a dead device produces, and the two were
# indistinguishable. Every press now makes a sound saying which happened.

def test_stopping_speech_plays_the_stop_cue(app, monkeypatch, stopped, cues):
    _playing(monkeypatch, True)

    app._on_repeat_press()

    assert cues == ["stop"]


def test_the_stop_cue_is_a_tone_not_a_sentence(app, monkeypatch, stopped, cues):
    """Answering "I have stopped talking" with more talking contradicts
    the request and invites a second press to stop that."""
    _playing(monkeypatch, True)

    app._on_repeat_press()

    assert app.announcer.said == []


def test_repeating_does_not_play_the_stop_cue(app, monkeypatch, stopped, cues):
    """A press while silent means repeat, which answers with speech. A
    stop cue in front of it would say the opposite of what happens next."""
    _playing(monkeypatch, False)

    app._on_repeat_press()

    assert cues == []


# --- cancelling a command in flight ------------------------------------------
#
# A press used to abort playback only, so one during the 3-7 seconds of
# transcription and classification did nothing at all and the answer
# arrived anyway. The only way to take back a question was to trigger a
# real emergency alert to a guardian.

def test_a_press_while_thinking_cancels_the_command(app, monkeypatch, stopped, cues):
    _playing(monkeypatch, False)
    app._voice_active.set()

    app._on_repeat_press()

    assert app._voice_cancel.is_set()
    assert cues == ["stop"]


def test_cancelling_does_not_also_repeat(app, monkeypatch, stopped, cues):
    """The user asked to stop, not to hear the previous answer again."""
    _playing(monkeypatch, False)
    app._voice_active.set()

    app._on_repeat_press()

    assert app.executor.intents == []


def test_a_press_mid_response_stops_both_the_audio_and_the_pipeline(
    app, monkeypatch, stopped, cues,
):
    """Playing its answer means both are true. Stopping only the speaker
    would let the pipeline run on into the stage after playback."""
    _playing(monkeypatch, True)
    app._voice_active.set()

    app._on_repeat_press()

    assert stopped["stops"] == 1
    assert app._voice_cancel.is_set()
    assert cues == ["stop"]


def test_the_cancel_reason_distinguishes_a_user_from_an_emergency(app, monkeypatch, stopped, cues):
    """Both buttons set the same flag, because every pipeline stage wants
    the same answer. Only the journal afterwards needs to tell them
    apart."""
    _playing(monkeypatch, False)
    app._voice_active.set()

    app._on_repeat_press()

    assert app._cancel_reason() == "user"


def test_a_new_command_clears_a_previous_cancel(app, monkeypatch, stopped, cues):
    """A stale flag would abort the next command before it started."""
    app._voice_active.set()
    app._on_repeat_press()
    assert app._voice_cancel.is_set()

    app._voice_active.clear()
    monkeypatch.setattr(app, "_play_press_feedback", lambda rising_chime: None)
    monkeypatch.setattr(app, "_voice_pipeline", lambda: None)
    app._on_ptt_press()

    assert not app._voice_cancel.is_set()
    assert app._cancel_reason() == "unknown"


# --- a refused press still answers -------------------------------------------

def test_a_ptt_press_while_busy_plays_the_busy_cue(app, monkeypatch, cues):
    """The press is refused, but a button that produces nothing at all is
    indistinguishable from a broken one — and this is the button someone
    reaches for when they think the device stopped listening."""
    app._voice_active.set()

    app._on_ptt_press()

    assert cues == ["busy"]


def test_a_busy_ptt_press_does_not_start_a_second_pipeline(app, monkeypatch, cues):
    started = []
    monkeypatch.setattr(app, "_voice_pipeline", lambda: started.append(1))
    app._voice_active.set()

    app._on_ptt_press()

    assert started == []
