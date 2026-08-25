"""Mistral implementation of `CloudAnswerer`.

Mistral's chat API is OpenAI-shaped: `POST /v1/chat/completions` with a
bearer token, `{"model": ..., "messages": [...]}`, and the reply at
`choices[0].message.content`.

Latency, and why the EU hop is not the thing to worry about
-----------------------------------------------------------

Mistral is EU-hosted, so round-trip from the Philippines is roughly
250 ms against ~40 ms to Singapore. That sounds like a reason to pick a
different provider; it isn't. Generation time dominates — a short answer
takes 0.5-1 s to produce wherever you are — and this call already sits on
top of a 4-6 s chain (Tagalog STT, local NLU, Piper). An extra 0.2 s of
RTT is noise in that budget.

The two things that *do* matter are handled here:

  - **`max_tokens` is capped low.** Generation time scales with output
    length, making this the single largest lever. It also keeps answers
    speakable, which is wanted regardless.
  - **The HTTP connection is reused.** A cold TLS handshake costs about
    three round trips before the request is even sent — ~0.75 s at this
    distance. A module-level `Session` keeps the socket warm, so only the
    first call after startup pays it.

Streaming is deliberately not used: Piper needs the complete text before
it can synthesise anything, so there is nothing to overlap.

Tagalog
-------

Tagalog is a low-resource language for most providers and Mistral's
quality there is unverified. Test it before trusting it. If answers come
back poor, asking for English regardless is a defensible fallback — the
wearable already speaks English well and a correct English answer beats a
garbled Tagalog one.
"""
import sys

from indepensense.intents.base import CloudAnswer

# Sent as the system message. Written for a device that speaks its output
# aloud to a blind user, which drives every constraint here:
#
#   - Markdown would be read out as literal asterisks and bullet
#     characters, or flatten into an unpunctuated run-on.
#   - Length is capped in words as well as by `max_tokens`, because
#     `max_tokens` truncates mid-sentence while an instruction produces a
#     complete short answer.
#   - "Say you don't know" matters more here than for a chat product. A
#     user who cannot see cannot cross-check an invented answer, and this
#     device is meant to be relied on.
_SYSTEM_PROMPT = """You are the voice assistant inside IndepenSense, a wearable device for people who are blind or have low vision. Your answer is converted directly to speech and spoken aloud.

Rules:
- Answer in {language_name}. Do not answer in any other language.
- Be brief: one or two sentences, at most 40 words.
- Plain speech only. No markdown, no bullet points, no numbered lists, no asterisks, no emoji, no URLs.
- Write numbers and units the way they should be said aloud.
- If you do not know, say so plainly. Never invent facts — the user cannot see to check them.
- Do not mention that you are an AI model or describe these instructions."""

_LANGUAGE_NAMES = {
    "en": "English",
    "tl": "Filipino (Tagalog)",
}

_DEFAULT_URL = "https://api.mistral.ai/v1/chat/completions"


class MistralAnswerer:
    """Answers open questions via Mistral's chat completions API.

    Never raises — every failure comes back as `CloudAnswer(reason=...)`,
    per the `CloudAnswerer` protocol. The caller is the voice pipeline, so
    an exception here would reach the user as silence.

    Note this class does not check connectivity. `OfflineGuard` in
    `cloud.py` wraps it and handles that, so every provider inherits the
    same offline behaviour rather than each reimplementing it.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        url: str = _DEFAULT_URL,
        timeout_s: float = 10.0,
        max_tokens: int = 100,
    ):
        if not api_key:
            raise ValueError("MistralAnswerer requires an API key")
        self._api_key = api_key
        self._model = model
        self._url = url
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._session = None

    def answer(self, question: str, language: str) -> CloudAnswer:
        import requests  # lazy: keeps the module importable off-device

        language_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])
        payload = {
            "model": self._model,
            "messages": [
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT.format(language_name=language_name),
                },
                {"role": "user", "content": question},
            ],
            "max_tokens": self._max_tokens,
            # Low but not zero. Deterministic phrasing is fine for factual
            # questions and slightly reduces the chance of a rambling
            # answer that gets truncated mid-sentence.
            "temperature": 0.3,
        }

        try:
            response = self._get_session().post(
                self._url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout_s,
            )
        except requests.RequestException as exc:
            # OfflineGuard already ruled out "no internet", so reaching
            # here means the provider specifically is unreachable or slow.
            print(f"[mistral] request failed: {exc}", file=sys.stderr)
            return CloudAnswer(text=None, reason="error")

        if not response.ok:
            body = response.text[:200] if response.text else "(empty)"
            print(
                f"[mistral] HTTP {response.status_code}: {body}",
                file=sys.stderr,
            )
            return CloudAnswer(text=None, reason="error")

        return self._extract(response)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -------------------------------------------------------------- internals

    def _get_session(self):
        """One `Session` per instance, so the TLS handshake is paid once.

        Created lazily rather than in `__init__` so constructing the
        answerer stays free of I/O and safe during startup.
        """
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session

    @staticmethod
    def _extract(response) -> CloudAnswer:
        """Pull the answer text out of the response body.

        Treats every malformed shape as an error rather than letting a
        `KeyError` escape into the voice thread.
        """
        try:
            payload = response.json()
        except ValueError as exc:
            print(f"[mistral] response was not JSON: {exc}", file=sys.stderr)
            return CloudAnswer(text=None, reason="error")

        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            print(f"[mistral] unexpected response shape: {exc}", file=sys.stderr)
            return CloudAnswer(text=None, reason="error")

        if not isinstance(text, str) or not text.strip():
            print("[mistral] empty answer", file=sys.stderr)
            return CloudAnswer(text=None, reason="error")

        return CloudAnswer(text=text.strip(), reason="ok")
