"""Remote TTS over HTTP — the self-hosted OmniVoice Filipino endpoint.

A `TTSEngine` like `PiperTTS` and `MmsTTS`, so `MultiEngineTTS` routes to
it without learning a new concept: it renders text to a WAV at a path and
the clip store does not care which engine produced the bytes.

Why remote at all, when MMS already speaks Tagalog
--------------------------------------------------

Not latency. Measured 2026-10-12 from a laptop on a short EU hop, which
is the *best* case and excludes the wearable's cellular leg entirely:

    generation (ttfb)   1.08-1.29 s
    total               1.70-1.94 s
    response size       101-174 KB   (24 kHz mono 16-bit WAV)

against local MMS at 2.23 s on the Pi. Roughly a wash once the
Philippines-to-Finland round trip and a ~127 KB download over the modem
are added — and probably slower than the ONNX export of MMS, which
measured 1.23-1.43 s with no network at all.

The reason is **pronunciation**: OmniVoice is fine-tuned on Filipino and
sounds markedly more natural than MMS. That is worth paying for, but it
is worth paying for *once*, at render time, not on every utterance.

Which is why this is built for `tools/render_messages.py` first. The clip
store means speech is rendered once and replayed, so the 66 static
messages can be synthesised here ahead of time and then cost a file read
forever. Only genuinely dynamic text — place names, distances — would
ever reach this at runtime, and that path falls back to local MMS when
the endpoint cannot be reached. See `config.REMOTE_TTS_ENABLED`.

The endpoint
------------

`POST /tts` with `{"text": ...}` returns `audio/wav` directly — not JSON,
not a URL. Errors come back as JSON with a `detail` field: 400 for an
unknown voice, 422 for empty or over-long text, 500 for a synthesis
failure.

Two server constraints shape the code below. Each model serves **one
request at a time** and queues the rest, so callers must not fan out;
`render_messages` is sequential already. And text is capped at 2000
characters, which no single message approaches but a caller concatenating
them would.

Numbers and symbols read inconsistently — the same limitation MMS has,
and the reason `intents.messages` spells numbers out through
`speak_number` before any engine sees them. Nothing extra is needed here,
but the constraint travels with this code rather than living only in the
other driver's docstring.
"""
import array
import io
import sys
import threading
import wave
from pathlib import Path

from indepensense.net import (
    breaker_for, breaker_reason_for, has_network_route, require_https,
)

# What `router.voice_id` names clips rendered here. Includes the voice so
# that changing it re-renders rather than silently serving the old audio,
# exactly as swapping engines does.
ENGINE_NAME = "omnivoice"

# Connect-phase budget, kept separate from the read budget. `requests`
# applies a *scalar* timeout to each phase independently rather than to
# total elapsed time, so passing one number would have allowed that long
# to open the socket and the same again waiting for audio — double the
# ceiling anyone reading the config would expect. Only spent when the
# pooled socket is gone, which a batch render pays once.
_CONNECT_TIMEOUT_S = 2.0

# Largest magnitude of a signed 16-bit sample.
_FULL_SCALE = 32767


class RemoteTTS:
    """A single-language voice served over HTTP.

    Holds one language, like `MmsTTS` and for the same reason: the
    endpoint's voice is chosen per deployment, and routing across
    languages is `MultiEngineTTS`'s job.

    Raises on failure rather than writing silence, which matches
    `PiperTTS` and `MmsTTS` — `clips.render` deletes the partial file and
    lets the caller decide. `render_messages` counts it as a failure and
    carries on; at runtime `clips.render_first` turns it into a fallback
    to the local engine, filed under that engine's own voice.
    """

    def __init__(
        self,
        url: str,
        language: str,
        voice: str,
        model: str = "omnivoice",
        timeout_s: float = 60.0,
        peak_dbfs: float | None = None,
    ):
        # No credential travels on this request, so this is not the
        # bearer-token argument `require_https` was written for. It is
        # still the right check: the body is the sentence the wearable is
        # about to say aloud, and the reply is that sentence as audio.
        # Neither belongs in plaintext across hops we do not control.
        require_https(url, "REMOTE_TTS_URL")

        self.language = language
        self.voice = voice
        self._url = url
        self._model = model
        self._timeout_s = timeout_s
        self._peak_dbfs = peak_dbfs
        self._session = None
        # Guards creation of the session only, not its use — see
        # `_get_session`.
        self._session_lock = threading.Lock()
        # Shared with anything else talking to this host — see
        # `net.breaker_for`. Without it an unreachable endpoint costs an
        # unbounded DNS stall on the announcer thread for *every*
        # sentence, not just the first.
        self._breaker = breaker_for(url)

    @property
    def voice_id(self) -> str:
        """Identity for clip naming — see `router.voice_id`."""
        return f"{ENGINE_NAME}:{self.voice}"

    def synthesize(
        self,
        text: str,
        output_path: Path,
        language: str | None = None,
    ) -> None:
        import requests  # lazy: keeps the module importable off-device

        if language is not None and language != self.language:
            raise ValueError(
                f"RemoteTTS holds the '{self.language}' voice, asked for "
                f"'{language}'"
            )

        body = text.strip()
        if not body:
            # The server answers 422 for empty text. Writing an empty WAV
            # instead matches `MmsTTS`, whose tokeniser can also produce
            # nothing: silence is recoverable, an exception on the voice
            # thread reaches the user as silence anyway but kills the
            # utterance around it.
            _write_empty_wav(output_path)
            return

        # Checked before the breaker: no route is instant and self-
        # healing, where the breaker holds for 30 s after it trips.
        if not has_network_route():
            raise RuntimeError("remote TTS skipped: no network route")
        if not self._breaker.allow():
            raise RuntimeError("remote TTS skipped: host failed recently")

        try:
            response = self._get_session().post(
                self._url,
                json={"text": body, "model": self._model, "voice": self.voice},
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
            # Classified by the same policy as a raised exception, via a
            # synthetic HTTPError. Without this the status never reached
            # `breaker_reason_for`: a bad status raised a plain
            # RuntimeError, which the classifier correctly ignores, so a
            # 429 from this host opened no breaker while the same 429
            # from Mistral did. One policy means one policy.
            self._record_status_failure(response)
            raise RuntimeError(
                f"remote TTS {response.status_code}: {_detail(response)}"
            )

        # A 200 whose body is JSON means the contract moved under us — the
        # endpoint promises raw audio. Caught here rather than letting a
        # JSON blob be written with a .wav name, which `find` would then
        # serve forever as a clip that cannot be played.
        content_type = response.headers.get("Content-Type", "")
        if not content_type.startswith("audio/"):
            raise RuntimeError(
                f"remote TTS returned {content_type!r}, expected audio/wav: "
                f"{response.text[:120]}"
            )

        audio = response.content
        if self._peak_dbfs is not None:
            audio = normalise_peak(audio, self._peak_dbfs)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio)

    def _record_status_failure(self, response) -> None:
        """Let a bad HTTP status open the breaker when the policy says so.

        `breaker_reason_for` keys off exception types, and the natural
        reading of a non-ok response here is a `RuntimeError` — which is
        not a `RequestException`, so the classifier passes it over. The
        synthetic `HTTPError` carries the status into the same rules
        Mistral's parser uses, so 429 and 4xx open the breaker and 5xx
        does not, on every endpoint rather than only one.
        """
        import requests

        reason = breaker_reason_for(requests.HTTPError(response=response))
        if reason:
            self._breaker.record_failure(reason)

    def close(self) -> None:
        # Under the lock so a shutdown cannot null the session out from
        # between another thread's check and its return in `_get_session`.
        with self._session_lock:
            if self._session is not None:
                self._session.close()
                self._session = None

    def _get_session(self):
        """One session for the instance, so a batch render pays the TLS
        handshake once rather than per message — `render_messages` makes
        over a hundred calls in a row.

        The lock guards creation, not use: the announcer thread and a
        voice thread can both reach synthesis at once, and unguarded they
        each built a `Session` with one dropped unclosed. Sharing the
        survivor is the point — every request passes its own body and
        nothing mutates session state. `MmsTTS` takes a lock in the same
        place for a stricter reason: torch makes no thread-safety promise
        about a shared module, where a connection pool does."""
        with self._session_lock:
            if self._session is None:
                import requests
                self._session = requests.Session()
            return self._session


def normalise_peak(wav_bytes: bytes, target_dbfs: float) -> bytes:
    """Scale a 16-bit PCM WAV so its loudest sample sits at `target_dbfs`.

    OmniVoice returns audio about 8 dB below full scale, where Piper
    peak-normalises its own output. Measured across the 66 static
    messages on 2026-10-13:

        en  piper       peak  -0.0 dBFS   RMS -15.4 dBFS
        tl  omnivoice   peak  -8.0 dBFS   RMS -25.0 dBFS

    so Tagalog played 9.6 dB quieter than English. On a device whose
    whole output is speech to someone who cannot see the screen, "can't
    hear it" is a fault rather than a polish item.

    **Peak rather than RMS.** Matching the RMS exactly needs +9.6 dB,
    which puts the loudest samples 1.6 dB past full scale — audible
    clipping on sibilants. Peak normalisation takes the +7 dB that fits
    and leaves Tagalog ~2.6 dB down, which is near the threshold of
    noticing. Closing the last part would mean compressing the dynamics,
    which risks artefacts on speech for a difference this small.

    Uses `wave` and `array` rather than soundfile or numpy: the endpoint
    returns 16-bit mono PCM, the arithmetic is a multiply, and keeping it
    in the standard library means it is testable off the Pi, where
    libsndfile is not installed.

    Anything that is not 16-bit PCM, or is pure silence, comes back
    untouched — there is no sensible gain for either, and a clip that
    plays quietly is better than one that fails to render.
    """
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as source:
            if source.getsampwidth() != 2:
                return wav_bytes
            params = source.getparams()
            frames = source.readframes(source.getnframes())
    except (wave.Error, EOFError):
        return wav_bytes

    samples = array.array("h")
    samples.frombytes(frames[: len(frames) - (len(frames) % 2)])
    if not samples:
        return wav_bytes

    peak = max(abs(min(samples)), abs(max(samples)))
    if peak == 0:
        return wav_bytes

    ceiling = int(_FULL_SCALE * (10.0 ** (target_dbfs / 20.0)))
    gain = ceiling / peak
    if abs(gain - 1.0) < 0.01:
        return wav_bytes

    for i, value in enumerate(samples):
        scaled = int(value * gain)
        # Clamp rather than wrap. A wrapped sample is not a quiet click,
        # it is full-scale noise of the opposite sign.
        samples[i] = _FULL_SCALE if scaled > _FULL_SCALE else (
            -_FULL_SCALE - 1 if scaled < -_FULL_SCALE - 1 else scaled
        )

    out = io.BytesIO()
    with wave.open(out, "wb") as sink:
        sink.setparams(params)
        sink.writeframes(samples.tobytes())
    return out.getvalue()


def _detail(response) -> str:
    """The server's `detail` field, or the raw body if it isn't JSON."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:160]
    if isinstance(payload, dict) and "detail" in payload:
        return str(payload["detail"])[:160]
    return str(payload)[:160]


def _write_empty_wav(output_path: Path) -> None:
    """A valid, silent WAV — same contract `MmsTTS` keeps for text that
    tokenises to nothing."""
    import wave

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(24000)
        handle.writeframes(b"")
