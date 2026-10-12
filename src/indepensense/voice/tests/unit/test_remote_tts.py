"""Unit tests for the remote (OmniVoice) TTS driver.

No network: `requests.Session.post` is monkeypatched.

The property worth pinning hardest is that **nothing but real audio is
ever written to the clip path**. A clip is content-addressed and
permanent — `find` returns whatever sits at that name forever — so a
JSON error body or a truncated response written with a `.wav` name is
not a transient failure, it is a sentence the wearable can never say
again until someone deletes the file by hand.
"""
import json
import wave

import pytest
import requests

from indepensense.voice.remote import RemoteTTS

URL = "https://tts.test/tts"


@pytest.fixture
def tts():
    return RemoteTTS(url=URL, language="tl", voice="07")


def _response(status_code=200, body=b"", content_type="audio/wav", payload=None):
    response = requests.Response()
    response.status_code = status_code
    if payload is not None:
        response._content = json.dumps(payload).encode()
        content_type = "application/json"
    else:
        response._content = body
    response.headers["Content-Type"] = content_type
    return response


def _capture(monkeypatch, response=None, raises=None):
    sent = {}

    def _post(self, url, json=None, timeout=None, **kw):
        sent["url"] = url
        sent["json"] = json
        sent["timeout"] = timeout
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(requests.Session, "post", _post)
    return sent


# --- construction -------------------------------------------------------------

def test_plaintext_http_is_refused():
    """Not a bearer token, but still the sentence the device is about to
    speak and the audio of it. `require_https` is the existing rule."""
    with pytest.raises(ValueError):
        RemoteTTS(url="http://tts.test/tts", language="tl", voice="07")


def test_the_voice_is_part_of_the_engine_identity():
    """Changing voice must re-render, which only happens if the identity
    changes with it — see `clips.digest`."""
    assert RemoteTTS(URL, "tl", "07").voice_id == "omnivoice:07"
    assert RemoteTTS(URL, "tl", "12").voice_id != RemoteTTS(URL, "tl", "07").voice_id


# --- the request --------------------------------------------------------------

def test_the_request_carries_text_model_and_voice(tts, tmp_path, monkeypatch):
    sent = _capture(monkeypatch, _response(body=b"RIFF....WAVE"))

    tts.synthesize("Magandang umaga po", tmp_path / "a.wav")

    assert sent["json"] == {
        "text": "Magandang umaga po", "model": "omnivoice", "voice": "07",
    }
    assert sent["url"] == URL


def test_a_language_the_engine_does_not_hold_is_rejected(tts, tmp_path):
    """Same guard as `MmsTTS`: one engine, one language, and routing is
    `MultiEngineTTS`'s job."""
    with pytest.raises(ValueError):
        tts.synthesize("hello", tmp_path / "a.wav", language="en")


def test_the_session_is_reused_across_calls(tts, tmp_path, monkeypatch):
    """A batch render makes over a hundred calls in a row; paying the TLS
    handshake each time would dominate it."""
    _capture(monkeypatch, _response(body=b"RIFF....WAVE"))

    tts.synthesize("una", tmp_path / "a.wav")
    first = tts._session
    tts.synthesize("pangalawa", tmp_path / "b.wav")

    assert tts._session is first


# --- what reaches the clip path -----------------------------------------------

def test_audio_is_written_verbatim(tts, tmp_path, monkeypatch):
    _capture(monkeypatch, _response(body=b"RIFF1234WAVEfmt "))
    out = tmp_path / "clip.wav"

    tts.synthesize("Magandang umaga po", out)

    assert out.read_bytes() == b"RIFF1234WAVEfmt "


@pytest.mark.parametrize("status,payload", [
    (400, {"detail": "unknown voice '99', available: ['07']"}),
    (422, {"detail": "text too long"}),
    (500, {"detail": "synthesis failed: cuda oom"}),
])
def test_an_error_response_raises_and_writes_nothing(
    tts, tmp_path, monkeypatch, status, payload,
):
    """`clips.render` deletes the partial and re-raises, so the caller
    decides. Writing the error body under the clip's name would poison
    that sentence permanently."""
    _capture(monkeypatch, _response(status_code=status, payload=payload))
    out = tmp_path / "clip.wav"

    with pytest.raises(RuntimeError) as exc:
        tts.synthesize("Magandang umaga po", out)

    assert not out.exists()
    assert payload["detail"][:20] in str(exc.value)


def test_a_200_that_is_not_audio_raises(tts, tmp_path, monkeypatch):
    """The endpoint promises raw audio on 200. If that ever changes, a
    JSON blob written with a `.wav` name would be found by `find` and
    served as a clip forever — fail loudly instead."""
    _capture(monkeypatch, _response(payload={"url": "https://somewhere/a.wav"}))
    out = tmp_path / "clip.wav"

    with pytest.raises(RuntimeError, match="expected audio/wav"):
        tts.synthesize("Magandang umaga po", out)

    assert not out.exists()


def test_a_transport_failure_propagates(tts, tmp_path, monkeypatch):
    """Unlike the cloud parser, this raises rather than degrading: its
    callers are a batch render that counts failures, and a future runtime
    wrapper that will own the fallback."""
    _capture(monkeypatch, raises=requests.ConnectionError("no route"))

    with pytest.raises(requests.ConnectionError):
        tts.synthesize("Magandang umaga po", tmp_path / "clip.wav")


# --- empty text ---------------------------------------------------------------

def test_empty_text_writes_a_valid_silent_wav(tts, tmp_path, monkeypatch):
    """The server answers 422 for empty text. `MmsTTS` writes silence
    when its tokeniser yields nothing, and the clip store expects a
    playable file at the path either way."""
    sent = _capture(monkeypatch, _response(body=b"should not be used"))
    out = tmp_path / "clip.wav"

    tts.synthesize("   ", out)

    assert sent == {}, "no request should be made for empty text"
    with wave.open(str(out)) as handle:
        assert handle.getnframes() == 0
        assert handle.getnchannels() == 1


def test_the_timeout_bounds_connect_and_read_separately(tmp_path, monkeypatch):
    """`requests` applies a scalar timeout to each phase independently,
    not to total elapsed time, so passing one number would allow that
    long to open the socket and the same again waiting for audio —
    double the ceiling the config appears to set."""
    sent = _capture(monkeypatch, _response(body=b"RIFF....WAVE"))

    RemoteTTS(URL, "tl", "07", timeout_s=6.0).synthesize("hi", tmp_path / "a.wav")

    assert sent["timeout"] == (2.0, 6.0)


def test_a_failure_stops_the_next_call_reaching_the_network(tts, tmp_path, monkeypatch):
    """Same guard as the STT driver. The announcer would otherwise pay an
    unbounded DNS stall for every sentence the clip store misses."""
    calls = []

    def _post(self, *a, **kw):
        calls.append(1)
        raise requests.ConnectionError("network is unreachable")

    monkeypatch.setattr(requests.Session, "post", _post)

    for i in range(4):
        with pytest.raises(Exception):
            tts.synthesize("Magandang umaga po", tmp_path / f"{i}.wav")

    assert len(calls) == 1, "only the first attempt should touch the network"


# --- loudness ----------------------------------------------------------------

import array
import io
import math

from indepensense.voice.remote import normalise_peak


def _tone(peak_frac, frames=2400, width=2, rate=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(width)
        handle.setframerate(rate)
        samples = array.array(
            "h", [int(peak_frac * 32767 * math.sin(i / 8)) for i in range(frames)]
        )
        handle.writeframes(samples.tobytes())
    return buf.getvalue()


def _peak_dbfs(wav_bytes):
    with wave.open(io.BytesIO(wav_bytes)) as handle:
        samples = array.array("h")
        samples.frombytes(handle.readframes(handle.getnframes()))
    peak = max(abs(min(samples)), abs(max(samples)))
    return 20 * math.log10(peak / 32767) if peak else float("-inf")


def test_quiet_audio_is_brought_up_to_the_ceiling():
    """OmniVoice returns ~-8 dBFS where Piper peak-normalises its own
    output, so Tagalog played 9.6 dB quieter than English."""
    assert _peak_dbfs(normalise_peak(_tone(0.398), -1.0)) == pytest.approx(-1.0, abs=0.1)


def test_loud_audio_is_brought_down_to_the_ceiling():
    """Normalisation, not just amplification — a clip already at full
    scale must come down to leave the inter-sample margin."""
    assert _peak_dbfs(normalise_peak(_tone(1.0), -1.0)) == pytest.approx(-1.0, abs=0.1)


def test_audio_already_at_the_ceiling_is_returned_untouched():
    """Byte-identical, so re-rendering an unchanged message does not
    churn the clip store."""
    at_ceiling = normalise_peak(_tone(0.398), -1.0)

    assert normalise_peak(at_ceiling, -1.0) == at_ceiling


def test_silence_is_left_alone():
    """There is no gain that makes silence louder, and dividing by its
    zero peak would raise."""
    silent = _tone(0.0)

    assert normalise_peak(silent, -1.0) == silent


def test_the_header_survives():
    """Rate and channel count must round-trip — the endpoint returns
    24 kHz mono and playback reads both from the file."""
    out = normalise_peak(_tone(0.398), -1.0)

    with wave.open(io.BytesIO(out)) as handle:
        assert handle.getframerate() == 24000
        assert handle.getnchannels() == 1
        assert handle.getsampwidth() == 2


def test_a_non_wav_body_is_passed_through_rather_than_raising():
    """A clip that plays quietly beats one that fails to render."""
    assert normalise_peak(b"not a wav at all", -1.0) == b"not a wav at all"


def test_normalisation_is_off_unless_asked_for(tmp_path, monkeypatch):
    """`peak_dbfs=None` must write the server's bytes verbatim."""
    quiet = _tone(0.398)
    _capture(monkeypatch, _response(body=quiet))
    out = tmp_path / "clip.wav"

    RemoteTTS(URL, "tl", "07").synthesize("Magandang umaga po", out)

    assert out.read_bytes() == quiet


def test_the_driver_normalises_when_configured(tmp_path, monkeypatch):
    _capture(monkeypatch, _response(body=_tone(0.398)))
    out = tmp_path / "clip.wav"

    RemoteTTS(URL, "tl", "07", peak_dbfs=-1.0).synthesize("Magandang umaga po", out)

    assert _peak_dbfs(out.read_bytes()) == pytest.approx(-1.0, abs=0.1)
