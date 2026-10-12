"""Mistral drivers: the `CloudAnswerer`, and the cloud `IntentParser`.

Two classes, one provider, opposite jobs — and one file, because they
share the endpoint, the auth, the session discipline and the error
mapping. Splitting them would duplicate all four to separate forty lines.

  - `MistralAnswerer` answers open questions the local model declined.
  - `MistralIntentParser` classifies into the fixed intent set, as the
    primary in front of `OllamaIntentParser`.

**They have deliberately opposite conversation contracts, and that is the
thing to keep straight when editing either.** The answerer replays one
prior turn, because people ask follow-ups ("what about the second one").
The parser replays *nothing*: intent classification must be independent
per utterance, so that a previous "take me to Jollibee" cannot colour the
next "stop", and so no context can contaminate an emergency phrasing.
Each press of the button is a fresh classification. See
`MistralIntentParser` for why the cache does not undermine this.

Mistral's chat API is OpenAI-shaped: `POST /v1/chat/completions` with a
bearer token, `{"model": ..., "messages": [...]}`, and the reply at
`choices[0].message.content`.

Latency, and why the network is not the thing to worry about
------------------------------------------------------------

Measured from the deployed Pi on 2026-10-12, over the SIM7600 rather
than the bench WiFi (`curl --interface wwan0` — the modem is the
metric-700 default and loses to `wlan0` at a desk, so anything measured
without binding is not the field case):

                              median    worst    TCP connect
    wwan0 (SIM7600)           743 ms   1263 ms     35-50 ms
    wlan0 (WiFi)              577 ms    978 ms     33-45 ms

n=15 each, warm-connection equivalent (`total` minus `appconnect`, which
is what the module-level `Session` below gives after the first call),
with the real ~2,600-token NLU prompt.

Two things that earlier guesswork got wrong. Round-trip to Mistral from
the Philippines is ~40 ms, not the ~250 ms this docstring used to claim
— the TCP connect times above measure it directly. And **the cellular
link costs only ~170 ms over WiFi**, so the modem is not the constraint
it was assumed to be. What dominates is prefill plus generation on their
side, which is also where all the variance lives.

The two things that *do* matter are handled here:

  - **`max_tokens` is capped low.** Generation time scales with output
    length, making this the single largest lever. It also keeps answers
    speakable, which is wanted regardless.
  - **The HTTP connection is reused.** TCP plus TLS measured 95-250 ms
    before the request is even sent. A `Session` per instance keeps the
    socket warm, so only the first call after startup pays it.

Streaming is deliberately not used: Piper needs the complete text before
it can synthesise anything, so there is nothing to overlap.

Tagalog
-------

Tagalog is a low-resource language for most providers. For *answers* —
free Tagalog prose — Mistral's quality remains unverified. Test it before
trusting it. If answers come back poor, asking for English regardless is
a defensible fallback: the wearable already speaks English well and a
correct English answer beats a garbled Tagalog one.

Classification is the easier task and has one data point: "dalhin mo ako
sa Jollibee" came back as `navigation.start` with `location: "Jollibee"`
and `nearest: false` on the first attempt. One case is not a result —
`llm_probe` over the full prompt set is what settles it.
"""
import sys
from pathlib import Path

from indepensense.intents.base import CloudAnswer, Intent, IntentResult
from indepensense.intents.parser import parse_llm_response
from indepensense.net import breaker_for

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

    def answer(
        self,
        question: str,
        language: str,
        previous: tuple[str, str] | None = None,
    ) -> CloudAnswer:
        import requests  # lazy: keeps the module importable off-device

        language_name = _LANGUAGE_NAMES.get(language, _LANGUAGE_NAMES["en"])
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": _SYSTEM_PROMPT.format(language_name=language_name),
            },
        ]
        if previous is not None:
            # Replayed as a real turn rather than stuffed into the system
            # prompt, so the model resolves "what about the second one"
            # the way it resolves any follow-up. Exactly one turn: the
            # device speaks its answers aloud, so a long history would
            # cost tokens on every question to serve a conversation the
            # user cannot scroll back through anyway.
            past_question, past_answer = previous
            messages.append({"role": "user", "content": past_question})
            messages.append({"role": "assistant", "content": past_answer})
        messages.append({"role": "user", "content": question})

        payload = {
            "model": self._model,
            "messages": messages,
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


# Matches `parser._MAX_OUTPUT_TOKENS`. A classification is a few dozen
# tokens; this only exists so a model that starts rambling is cut off
# rather than billed for and waited on.
_MAX_OUTPUT_TOKENS = 128

# Connect-phase budget, separate from the read budget — see `_post`. Only
# spent when the pooled socket is gone (first call, or after the provider
# drops an idle connection), since `warm_up` opens it at startup.
_CONNECT_TIMEOUT_S = 1.0


class MistralIntentParser:
    """An `IntentParser` backed by Mistral, for use in front of Ollama.

    Emits the same JSON contract as the local model and hands it to
    `parse_llm_response`, so the failure taxonomy that `IntentResult` and
    `cloud.py` depend on is defined in exactly one place. `source` is
    `"cloud"`, which is what makes a wrong action in `journalctl`
    attributable to the engine that produced it now that three can.

    Stateless, and why the cache does not change that
    -------------------------------------------------

    Every request carries exactly two messages — the system prompt, then
    this transcript. No history, ever. The reasoning is in the module
    docstring; the enforcement is `_payload`, and a unit test asserts the
    shape, because this is the sort of invariant that a well-meaning
    "let's give it some context" edit erases silently.

    Mistral caches the prompt prefix server-side: measured at 2,560 of
    2,591 tokens on the first attempt, so most of the prefill is neither
    recomputed nor billed at full rate. That is an arithmetic
    optimisation, not a memory — the cached tensors for a fixed prefix are
    identical to the ones a cold request would compute, and the part that
    *varies* (the transcript) is the uncached remainder by construction.
    So the calls are cached and independent at the same time. Nothing in
    the prompt needs to ask for isolation, and asking would be worse than
    useless: it would spend tuned prompt budget on a property the request
    shape already guarantees, and a model cannot honour an instruction
    about state it has no access to.

    What that *does* impose is a stable prefix. Three rules follow:

      - the system message stays first and stays byte-identical —
        `prompt_path.read_text()`, never `.format()`;
      - nothing variable is prepended (no timestamp, GPS or battery);
      - the transcript goes last.

    Note `MistralAnswerer` above interpolates the language into its own
    system prompt, which splits its cache into one variant per language.
    Acceptable there, and deliberately not done here: `nlu_system.md`
    already covers both languages, so one prefix serves every utterance.

    Never raises. Every failure becomes `failure="transport"`, which is
    what tells `FallbackIntentParser` to try the local model — and,
    equally important, what stops a failed request from reaching
    `cloud.py` as if it were a genuine decline.
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        prompt_path: Path,
        url: str = _DEFAULT_URL,
        timeout_s: float = 2.5,
        max_tokens: int = _MAX_OUTPUT_TOKENS,
    ):
        if not api_key:
            raise ValueError("MistralIntentParser requires an API key")
        self._api_key = api_key
        self._model = model
        # Read once at construction, like `OllamaIntentParser`. Re-reading
        # per call would let an edit mid-session change the cached prefix
        # under the running device.
        self._system_prompt = prompt_path.read_text()
        self._url = url
        self._timeout_s = timeout_s
        self._max_tokens = max_tokens
        self._session = None
        self._breaker = breaker_for(url)

    def warm_up(self, timeout_s: float) -> bool:
        """Pay the TLS handshake and populate the remote prefix cache.

        The same idea as `OllamaIntentParser.warm_up` and for the same
        reason — the first query should not be the one that pays for the
        prefix — except that here it also covers the ~95-250 ms of TCP and
        TLS. Built from `_payload` so the warmed prefix is byte-identical
        to the one real queries reuse; a warmup that differed would warm
        nothing. Failures are non-fatal: they resurface on the next real
        query, where `parse` already handles them.
        """
        import requests  # lazy: keeps the module importable off-device

        try:
            response = self._post(self._payload("ok"), timeout_s)
            response.raise_for_status()
            return True
        except (requests.RequestException, ValueError) as exc:
            print(f"[mistral] NLU warmup failed: {exc}", file=sys.stderr)
            return False

    def parse(self, transcript: str) -> IntentResult:
        import requests  # lazy: keeps the module importable off-device

        if not self._breaker.allow():
            # Skipped without a request, because the cost being avoided is
            # an unbounded DNS stall on the voice thread — see
            # `net.HostBreaker`. Reported as `transport` like any other
            # unreachable provider, so `FallbackIntentParser` hands over
            # to the local model exactly as it would on a timeout.
            print("[mistral] skipped: host failed recently", file=sys.stderr)
            return IntentResult(
                intent=Intent.UNKNOWN, parameters={}, raw_transcript=transcript,
                raw_llm_response="", failure="transport", source="cloud",
            )

        try:
            response = self._post(self._payload(transcript), self._timeout_s)
            response.raise_for_status()
            raw = response.json()["choices"][0]["message"]["content"]
            self._breaker.record_success()
        except (requests.RequestException, ValueError, KeyError, IndexError,
                TypeError) as exc:
            # Timeouts land here too — `Timeout` is a `RequestException` —
            # which is the common case rather than the exceptional one:
            # the deadline is set to fall back, not to signal a fault.
            self._breaker.record_failure()
            print(f"[mistral] NLU request failed: {exc}", file=sys.stderr)
            return IntentResult(
                intent=Intent.UNKNOWN,
                parameters={},
                raw_transcript=transcript,
                raw_llm_response="",
                failure="transport",
                source="cloud",
            )

        return parse_llm_response(raw, transcript, source="cloud")

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None

    # -------------------------------------------------------------- internals

    def _payload(self, transcript: str) -> dict:
        """The request body. Two messages, system first, transcript last.

        The ordering is the cache contract, not a style choice — see the
        class docstring.
        """
        return {
            "model": self._model,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": transcript},
            ],
            "max_tokens": self._max_tokens,
            # Zero, unlike the answerer's 0.3. A classifier should return
            # the same label for the same words every time; the variation
            # that makes prose read better is only a source of
            # irreproducibility here, and the thesis quotes these numbers.
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }

    def _post(self, payload: dict, timeout_s: float):
        """POST with the connect and read budgets bounded separately.

        `requests` applies a *scalar* timeout to the connect phase and the
        read phase independently — it is not a limit on total elapsed
        time. Passing `2.5` therefore allowed 2.5 s to open the socket
        and a further 2.5 s of server silence, so the real worst case was
        ~5 s on a cold connection while the config comment claimed 2.5 s.

        The tuple makes the ceiling explicit: `_CONNECT_TIMEOUT_S` +
        `timeout_s`. Connect is the generous half because it almost never
        applies — the session is reused, so after `warm_up` the socket is
        already open and only the read budget is live. Measured TCP plus
        TLS over the modem was 95-250 ms, so 1 s is slack rather than a
        constraint.

        This still is not a wall-clock deadline: a server trickling bytes
        slower than the read timeout could in principle run longer. It
        cannot here — the reply is one small non-streamed body — and the
        probe measures true elapsed time anyway, which is what the 0 of
        226 over 2.5 s is counting.
        """
        return self._get_session().post(
            self._url,
            json=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=(_CONNECT_TIMEOUT_S, timeout_s),
        )

    def _get_session(self):
        """One `Session` per instance — see `MistralAnswerer._get_session`.

        Not shared with the answerer: they are opened by different
        factories and either may be absent, so a shared session would make
        one class's lifetime depend on the other's.
        """
        if self._session is None:
            import requests
            self._session = requests.Session()
        return self._session
