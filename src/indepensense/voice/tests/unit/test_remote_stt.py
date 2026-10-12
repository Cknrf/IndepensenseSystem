"""Unit tests for remote speech-to-text and its routing.

No network: `requests.Session.post` is monkeypatched.

The two properties that matter are that **only the configured languages
leave the device** — English audio must never be uploaded — and that a
remote failure becomes a local transcription rather than an empty
string. An empty transcript is a *valid* result, the one silence
produces, so returning one on a network error would be indistinguishable
from the user not having spoken and the pipeline would answer "I didn't
catch that" instead of falling back to a model that works.
"""
import json

import pytest
import requests

from indepensense.voice.base import Transcript
from indepensense.voice.remote_stt import RemoteSTT, RoutedSTT

URL = "https://stt.test/stt"


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.wav"
    path.write_bytes(b"RIFF0000WAVEfmt ")
    return path


@pytest.fixture
def remote():
    # Compression off: it needs soundfile, which is Pi-only, and what is
    # under test here is the request and the failure mapping.
    return RemoteSTT(url=URL, compress=False)


class FakeLocal:
    """Stands in for `FasterWhisperSTT`."""

    def __init__(self, text="local transcript"):
        self._text = text
        self.calls = []

    def transcribe(self, audio_path, language=None, initial_prompt=None):
        self.calls.append((audio_path, language, initial_prompt))
        return Transcript(text=self._text, language=language or "en", segments=[])

    def model_size_for(self, language):
        return "small"


def _response(status_code=200, payload=None, body=None):
    response = requests.Response()
    response.status_code = status_code
    response._content = (body if body is not None
                         else json.dumps(payload or {}).encode())
    response.headers["Content-Type"] = "application/json"
    return response


def _capture(monkeypatch, response=None, raises=None):
    sent = {}

    def _post(self, url, files=None, data=None, timeout=None, **kw):
        sent["url"] = url
        sent["files"] = files
        sent["data"] = data
        sent["timeout"] = timeout
        if raises is not None:
            raise raises
        return response

    monkeypatch.setattr(requests.Session, "post", _post)
    return sent


# --- construction -------------------------------------------------------------

def test_plaintext_http_is_refused():
    """The request body is a recording of the user's voice — the most
    sensitive thing this device transmits."""
    with pytest.raises(ValueError):
        RemoteSTT(url="http://stt.test/stt")


# --- the request --------------------------------------------------------------

def test_the_clip_is_uploaded_as_multipart(remote, clip, monkeypatch):
    sent = _capture(monkeypatch, _response(payload={"text": "kumanan ka"}))

    remote.transcribe(clip, language="tl")

    assert "file" in sent["files"]
    assert sent["files"]["file"][1] == b"RIFF0000WAVEfmt "
    assert sent["data"]["language"] == "tl"


def test_no_prompt_is_sent_when_there_is_none(remote, clip, monkeypatch):
    """Omitting it makes the server apply its Batangas place-name hint,
    which raised exact place-name matches from 66 to 87 of 120. This is a
    navigation device, so that default is wanted. Sending an empty string
    would disable it."""
    sent = _capture(monkeypatch, _response(payload={"text": "kumanan ka"}))

    remote.transcribe(clip, language="tl", initial_prompt=None)

    assert "prompt" not in sent["data"]


def test_a_prompt_is_forwarded_when_given(remote, clip, monkeypatch):
    sent = _capture(monkeypatch, _response(payload={"text": "x"}))

    remote.transcribe(clip, language="tl", initial_prompt="Jollibee, SM Lipa")

    assert sent["data"]["prompt"] == "Jollibee, SM Lipa"


def test_the_transcript_is_returned_stripped(remote, clip, monkeypatch):
    _capture(monkeypatch, _response(
        payload={"text": "  Dalhin mo ako sa Jollibee  ", "language": "tl"}))

    result = remote.transcribe(clip, language="tl")

    assert result.text == "Dalhin mo ako sa Jollibee"
    assert result.language == "tl"
    assert result.segments == []


# --- failures -----------------------------------------------------------------

@pytest.mark.parametrize("status,payload", [
    (400, {"detail": "could not decode audio: empty file"}),
    (422, {"detail": "field required"}),
    (500, {"detail": "boom"}),
])
def test_error_statuses_raise(remote, clip, monkeypatch, status, payload):
    """Never an empty transcript: that is what silence returns, and the
    caller could not tell the two apart."""
    _capture(monkeypatch, _response(status_code=status, payload=payload))

    with pytest.raises(RuntimeError):
        remote.transcribe(clip, language="tl")


def test_a_transport_failure_raises(remote, clip, monkeypatch):
    _capture(monkeypatch, raises=requests.Timeout("deadline"))

    with pytest.raises(requests.Timeout):
        remote.transcribe(clip, language="tl")


# --- routing ------------------------------------------------------------------

def test_a_language_that_is_not_routed_never_leaves_the_device(clip, monkeypatch):
    """The whole point of bounding this to Tagalog. English audio must
    not be uploaded, and the test fails loudly if it ever is."""
    def _explode(*a, **kw):
        raise AssertionError("English audio was sent to the network")

    monkeypatch.setattr(requests.Session, "post", _explode)
    local = FakeLocal()
    routed = RoutedSTT(local, RemoteSTT(URL, compress=False), ("tl",))

    result = routed.transcribe(clip, language="en")

    assert result.text == "local transcript"
    assert local.calls == [(clip, "en", None)]


def test_a_routed_language_goes_to_the_server(clip, monkeypatch):
    _capture(monkeypatch, _response(payload={"text": "kumanan ka", "language": "tl"}))
    local = FakeLocal()
    routed = RoutedSTT(local, RemoteSTT(URL, compress=False), ("tl",))

    result = routed.transcribe(clip, language="tl")

    assert result.text == "kumanan ka"
    assert local.calls == []


def test_a_remote_failure_falls_back_to_the_local_model(clip, monkeypatch):
    """The user is mid-command. A slower answer beats none — and unlike
    intent parsing there is no fast path underneath, so no transcript
    means nothing downstream runs at all."""
    _capture(monkeypatch, raises=requests.ConnectionError("no route"))
    local = FakeLocal()
    routed = RoutedSTT(local, RemoteSTT(URL, compress=False), ("tl",))

    result = routed.transcribe(clip, language="tl", initial_prompt="hint")

    assert result.text == "local transcript"
    assert local.calls == [(clip, "tl", "hint")]


def test_an_empty_remote_transcript_is_not_a_failure(clip, monkeypatch):
    """Silence legitimately transcribes to nothing. Treating it as an
    error would re-run the slow local model on every quiet clip."""
    _capture(monkeypatch, _response(payload={"text": "", "language": "tl"}))
    local = FakeLocal()
    routed = RoutedSTT(local, RemoteSTT(URL, compress=False), ("tl",))

    assert routed.transcribe(clip, language="tl").text == ""
    assert local.calls == []


def test_model_size_passes_through_for_diagnostics(clip):
    routed = RoutedSTT(FakeLocal(), RemoteSTT(URL, compress=False), ("tl",))

    assert routed.model_size_for("tl") == "small"


def test_the_timeout_bounds_connect_and_read_separately(clip, monkeypatch):
    """Same reason as the TTS driver: a scalar would double the ceiling,
    and here the fallback behind it is the 5.29 s local model."""
    sent = _capture(monkeypatch, _response(payload={"text": "x"}))

    RemoteSTT(URL, timeout_s=20.0, compress=False).transcribe(clip, language="tl")

    assert sent["timeout"] == (2.0, 20.0)
