"""Remote speech-to-text — the self-hosted Whisper large-v3-turbo endpoint.

Two classes: `RemoteSTT`, an `STTEngine` that uploads a clip and gets a
transcript back, and `RoutedSTT`, which sends only the configured
languages to it and falls back to the on-device model when it cannot be
reached. The router lives here rather than in its own module because it
exists solely to serve the remote case — with remote STT off, `app`
returns the bare `FasterWhisperSTT` and neither class is constructed.

Why Tagalog goes to the server and English does not
---------------------------------------------------

Measured on the Pi 2026-10-12 with `latency_bench`:

    en, Whisper 'tiny'    median 1.13 s
    tl, Whisper 'small'   median 5.29 s   p95 5.69 s   RTF 2.23x

Tagalog is **slower than real time** on this hardware: a 5-second command
costs about 11 seconds to transcribe. It is also the weaker transcript —
`config.WHISPER_MODELS` records that `tiny` and `base` were too mangled
to use for Tagalog at all, which is why it runs `small` and pays for it.

English at 1.13 s is neither slow nor weak, so it stays local. Bounding
the exception to the language whose local quality was the actual problem
keeps English audio on the device entirely, which is a much easier
position to defend than moving speech recognition wholesale.

The server reports 0.15-0.25 s of processing for a 3-9 s clip, so the
round trip and the upload dominate — which is what the Opus encoding
below is for.

Upload, and why it is compressed
--------------------------------

STT reverses the direction that matters. TTS sends ~100 bytes up and
gets audio back; here the *audio is the request*, and uplink is the
SIM7600's weaker side. A 5 s clip at 16 kHz mono 16-bit is ~160 KB as
WAV and about 10 KB as Opus, for the same transcript — the endpoint's
own documentation measures 165 KB against 10 KB on a 3.4 s clip.

So clips are transcoded to Opus before sending, and fall back to the
original bytes if the installed `libsndfile` cannot write it. Encoding
costs tens of milliseconds against ~150 KB of cellular uplink; the trade
is not close. It degrades rather than failing because Opus support
depends on the `libsndfile` build, which varies by platform and is not
worth making a hard dependency for an optimisation.

Two behaviours of this endpoint worth knowing
---------------------------------------------

**Numbers come back as digits.** "alas otso" transcribes as "alas 8",
"apatnapu't limang piso" as "45 piso". That is the opposite of the
convention on the *output* side, where `intents.messages` spells numbers
out because the TTS voices mangle digits. It is fine here — the intent
prompts already handle digits in input ("volume 80" is an example in
`nlu_system_cloud.md`) — but it is a real difference between this
transcript and the local model's, and anything matching on transcript
text should not assume words.

**Whisper invents text on silence.** A clip containing only noise can
come back as a plausible sentence rather than an empty string, and the
pipeline downstream cannot tell the difference. The local model has the
same failure; sending only audio that contains speech is the mitigation,
and it belongs upstream of this driver rather than here.
"""
import sys
import threading
from pathlib import Path

from indepensense.net import (
    breaker_for, breaker_reason_for, has_network_route, require_https,
)
from indepensense.voice.base import Transcript

# Opus at 16 kHz mono. The endpoint accepts any rate and both channel
# counts, but recordings are already mono 16 kHz — Whisper's own input
# format — so nothing is resampled and no quality is traded here.
_UPLOAD_NAME = "clip.ogg"
_UPLOAD_TYPE = "audio/ogg"

# Connect-phase budget, separate from the read budget — see the same
# constant in `voice/remote.py`. `requests` applies a scalar timeout per
# phase, not to total elapsed time, so one number would mean double the
# ceiling the config appears to set.
_CONNECT_TIMEOUT_S = 2.0


class RemoteSTT:
    """Transcribe by uploading the clip to the endpoint.

    Raises on any failure rather than returning an empty transcript.
    An empty string is a *valid* result — it is what silence produces —
    so returning one on a network error would be indistinguishable from
    the user not having spoken, and the voice pipeline would answer "I
    didn't catch that" instead of falling back to a model that works.
    `RoutedSTT` turns the exception into a fallback.
    """

    def __init__(self, url: str, timeout_s: float = 20.0, compress: bool = True):
        # The request body is a recording of the user's voice. No
        # credential travels with it, so this is not the bearer-token
        # case `require_https` was written for, but it is the most
        # sensitive payload the device sends anywhere.
        require_https(url, "REMOTE_STT_URL")

        self._url = url
        self._timeout_s = timeout_s
        self._compress = compress
        self._session = None
        # Guards creation of the session only, not its use — see
        # `_get_session`.
        self._session_lock = threading.Lock()
        self._breaker = breaker_for(url)
        # Logged once rather than per utterance — a device that cannot
        # encode Opus would otherwise print on every command.
        self._warned_compress = False

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> Transcript:
        import requests  # lazy: keeps the module importable off-device

        payload, name, content_type = self._upload_body(audio_path)

        fields: dict[str, str] = {}
        if language:
            fields["language"] = language
        # Omitted when there is no prompt, which is deliberate: the
        # server then applies its Batangas place-name hint, measured to
        # raise exact place-name matches from 66 to 87 of 120. This is a
        # navigation device, so that default is the one we want. Passing
        # an empty string would *disable* it, which is the right choice
        # only for general conversation.
        if initial_prompt:
            fields["prompt"] = initial_prompt

        # Checked before the breaker: no route is instant and self-
        # healing, where the breaker holds for 30 s after it trips.
        if not has_network_route():
            raise RuntimeError("remote STT skipped: no network route")
        if not self._breaker.allow():
            raise RuntimeError("remote STT skipped: host failed recently")

        try:
            response = self._get_session().post(
                self._url,
                files={"file": (name, payload, content_type)},
                data=fields,
                timeout=(_CONNECT_TIMEOUT_S, self._timeout_s),
            )
        except BaseException as exc:
            # Shared with every other cloud driver — two endpoints backing
            # off differently is not a policy anyone could defend.
            reason = breaker_reason_for(exc)
            if reason:
                self._breaker.record_failure(reason)
            raise
        self._breaker.record_success()
        if not response.ok:
            raise RuntimeError(
                f"remote STT {response.status_code}: {_detail(response)}"
            )

        body = response.json()
        return Transcript(
            text=(body.get("text") or "").strip(),
            language=body.get("language") or language or "",
            # The endpoint does not return word-level timestamps, and
            # nothing outside the tests reads them.
            segments=[],
        )

    def close(self) -> None:
        # Under the lock so a shutdown cannot null the session out from
        # between another thread's check and its return in `_get_session`.
        with self._session_lock:
            if self._session is not None:
                self._session.close()
                self._session = None

    # -------------------------------------------------------------- internals

    def _upload_body(self, audio_path: Path):
        """The bytes to send, as (payload, filename, content type)."""
        if not self._compress:
            return audio_path.read_bytes(), audio_path.name, "audio/wav"

        encoded = self._to_opus(audio_path)
        if encoded is None:
            return audio_path.read_bytes(), audio_path.name, "audio/wav"
        return encoded, _UPLOAD_NAME, _UPLOAD_TYPE

    def _to_opus(self, audio_path: Path) -> bytes | None:
        """Opus bytes, or None if this build cannot produce them.

        None rather than raising: a clip that uploads as 160 KB of WAV
        still transcribes correctly, so losing the compression is a cost,
        not a failure, and it must not cost the user their command.
        """
        import io

        try:
            import soundfile as sf  # lazy: Pi-only, like the engines

            data, sample_rate = sf.read(str(audio_path), dtype="float32")
            buffer = io.BytesIO()
            sf.write(buffer, data, sample_rate, format="OGG", subtype="OPUS")
            return buffer.getvalue()
        except Exception as exc:   # noqa: BLE001 - see docstring
            if not self._warned_compress:
                self._warned_compress = True
                print(
                    f"[stt] cannot encode Opus ({exc}); uploading WAV, which "
                    f"is roughly 16x larger on the uplink",
                    file=sys.stderr,
                )
            return None

    def _get_session(self):
        """One session for the instance. The lock guards its creation,
        not its use — see `RemoteTTS._get_session` for the whole argument;
        this driver reaches it from the voice thread only today, and the
        lock costs nothing uncontended."""
        with self._session_lock:
            if self._session is None:
                import requests
                self._session = requests.Session()
            return self._session


class RoutedSTT:
    """Remote for the configured languages, local for everything else.

    Unlike the TTS fallback, this can be a plain wrapper: a transcript is
    a return value, not a stored artifact, so there is no filename to be
    attributed to the wrong engine and no state left behind when the
    remote attempt fails.

    The local engine is always constructed and stays resident. It has to:
    it is the fallback, and unlike intent parsing there is no fast path
    beneath STT — no transcript means nothing downstream runs at all,
    voice-triggered emergency included.
    """

    def __init__(self, local, remote: RemoteSTT, languages):
        self._local = local
        self._remote = remote
        self._languages = frozenset(languages)

    def model_size_for(self, language: str) -> str | None:
        """Pass-through for diagnostics — `app` prints this at startup."""
        getter = getattr(self._local, "model_size_for", None)
        return getter(language) if getter is not None else None

    def transcribe(
        self,
        audio_path: Path,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> Transcript:
        if language not in self._languages:
            return self._local.transcribe(
                audio_path, language=language, initial_prompt=initial_prompt,
            )

        try:
            return self._remote.transcribe(
                audio_path, language=language, initial_prompt=initial_prompt,
            )
        except Exception as exc:   # noqa: BLE001 - the whole point
            # The user is mid-command and the local model can still
            # answer, slower. Logged at the handover so an unexpectedly
            # sluggish device is explainable from the journal.
            print(
                f"[stt] remote failed ({exc}); falling back to the local model",
                file=sys.stderr,
            )
            return self._local.transcribe(
                audio_path, language=language, initial_prompt=initial_prompt,
            )

    def close(self) -> None:
        self._remote.close()


def _detail(response) -> str:
    """The server's `detail` field, or the raw body if it isn't JSON."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:160]
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])[:160]
    return str(payload)[:160]
