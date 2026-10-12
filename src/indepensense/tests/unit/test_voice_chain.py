"""The voice chain: what `REMOTE_TTS_ENABLED` actually switches.

One flag has to move three things together — which engine the router
builds, which voice clips are named after, and which engine a failed
render falls back to. If any of them disagreed, clips would be filed
under a voice nothing ever looks for and the store would miss on every
message.
"""
import pytest

import indepensense.app as app_module
from indepensense.voice.router import RemoteSpec


@pytest.fixture
def remote_on(monkeypatch):
    """Switch Tagalog to the remote endpoint, as the flag does."""
    monkeypatch.setattr(
        app_module, "_remote_spec",
        lambda: RemoteSpec(url="https://tts.test/tts", voices={"tl": "07"}),
    )


def test_without_remote_each_language_has_one_voice(monkeypatch):
    """Forced off rather than read from config: this pins the behaviour
    of the flag, so it must not depend on what the flag happens to be
    set to today."""
    monkeypatch.setattr(app_module, "_remote_spec", lambda: None)

    assert app_module._voice_chain("en") == ["piper:en_US-lessac-medium"]
    assert app_module._voice_chain("tl") == ["mms:mms-tts-tgl"]


def test_a_remote_language_gains_a_local_fallback_voice(remote_on):
    """Two entries, preferred first. The second is what a fallback
    render produces when the endpoint is unreachable."""
    assert app_module._voice_chain("tl") == ["omnivoice:07", "mms:mms-tts-tgl"]


def test_a_language_served_locally_is_untouched_by_the_remote_flag(remote_on):
    """English stays on Piper — the exception is bounded to the language
    whose local quality was the problem."""
    assert app_module._voice_chain("en") == ["piper:en_US-lessac-medium"]


def test_the_static_set_covers_every_voice_in_the_chain(remote_on):
    """The announcer decides permanent-vs-cache by filename lookup. A set
    built for only the preferred voice would classify every fallback
    render as templated and let the sweep delete static messages — the
    emergency-delivery failures among them."""
    from indepensense.intents import messages

    names = app_module._static_clip_names(["tl"])
    key = next(iter(messages.static_keys()))
    text = messages.get(key, "tl")

    from indepensense.voice import clips
    for voice in app_module._voice_chain("tl"):
        assert clips.filename(text, "tl", voice) in names


def test_attempts_pair_each_voice_with_its_own_engine(remote_on):
    """The pairing is the invariant: a fallback render must be filed
    under the fallback's voice, never inherit the preferred one's."""
    app = app_module.App.__new__(app_module.App)
    app.tts = object()
    app.tts_local = object()

    attempts = app._tts_attempts("tl")

    assert [v for _, v in attempts] == ["omnivoice:07", "mms:mms-tts-tgl"]
    assert attempts[0][0] is app.tts
    assert attempts[1][0] is app.tts_local


def test_no_fallback_engine_means_a_single_attempt(remote_on):
    """`_try_open_local_tts` returning None must not produce a
    `(None, voice)` pair that would raise inside `render_first`."""
    app = app_module.App.__new__(app_module.App)
    app.tts = object()
    app.tts_local = None

    assert len(app._tts_attempts("tl")) == 1
