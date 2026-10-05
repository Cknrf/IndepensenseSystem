"""Ollama-backed intent parser.

Thin wrapper around a local Ollama HTTP server. Sends each transcript with
the system prompt from `prompts/nlu_system.md`, requests JSON-formatted
output, and normalises the response into an `IntentResult`.

Thinking mode is disabled on every request (`"think": False`). Qwen 3 is a
hybrid reasoning model: by default it emits a `<think>...</think>` block
before its answer. That is actively harmful here — it spends seconds of the
latency budget reasoning about a 10-way classification, and the leading
prose breaks `format: "json"`. We want the model's language coverage, not
its reasoning. Ollama rejects this flag on models that cannot think, so it
must be dropped if we ever move back to a non-reasoning model.

Normalisation handles two known LLM quirks observed during benchmarking:

- `navigation.start` responses sometimes omit `nearest`. We inject
  `nearest: false` as the default so the executor never has to guess.
- `unknown` responses sometimes include hallucinated parameters. We strip
  them — an unknown intent has no meaningful parameters.

Unrecognised intent names in the LLM's output (e.g. the model invents
`music.play`) map to `Intent.UNKNOWN` rather than raising. Same for
non-JSON responses. HTTP/timeout errors are logged to stderr and also fall
back to `UNKNOWN` — a wrong `unknown` is safer than a hard crash mid-command.

Resilience choices
------------------

Every defensive knob below was added deliberately after real failures
observed during hardware integration. Kept together here so the reasoning
survives beyond commit history:

- **Startup warmup with full system prompt.** Cold-loading a model in this
  size class on the Pi 5 takes ~25-40 s (measured on Qwen 2.5 1.5B; re-measure
  for Qwen 3 1.7B). Doing this once at construction — with the
  actual system prompt the parser will send later, not just a throwaway
  "ok" — means the model *and* its prompt-prefix KV cache are hot before
  the first real user query. Without this the first command of every
  session would appear to time out.
- **Tiered timeouts.** Warmup uses `warmup_timeout_s` (~90 s default) to
  accommodate cold loads. Per-query uses `timeout_s` (~30 s default) which
  is tight enough to surface real failures quickly while giving warm
  queries room to complete under CPU contention with GraphHopper + Photon.
- **`keep_alive: -1`.** Ollama's default idle-unload is 5 minutes. On a
  wearable that must respond snappily whenever the user speaks, cold
  reloads are unacceptable — the 25-40 s first-query pause would ruin the
  UX. Setting `keep_alive` to `-1` pins the model in memory until Ollama
  itself restarts. Costs ~1.4 GB of RAM permanently on Qwen 2.5 1.5B; Qwen 3
  1.7B is a larger parameter count so expect somewhat more — confirm with
  `llm_probe` on the Pi before assuming the budget still holds.
- **A capped `num_predict`.** See `_MAX_OUTPUT_TOKENS`. Bounds the worst
  case so a model that never stops generating fails in a second rather
  than eating the whole per-query timeout.
- **Compact-JSON prefill (`compact_prefill=True`).** Instead of JSON mode,
  the request goes to `/api/chat` with the reply already begun —
  `{"intent":"` as a partial assistant message — and stops at the first
  newline. Qwen 3 4B pretty-prints JSON whatever the prompt says: the same
  answer cost it ~20 output tokens against ~12 compact, and on a CPU every
  output token is the slow part. The prefill also supplies the first few
  tokens itself, so the model generates ~7. JSON mode cannot be combined
  with it — Ollama's grammar restarts the object and ignores the prefill —
  so validity is no longer enforced by the server. A reply that does not
  parse takes the existing `"malformed"` path and never reaches the cloud;
  measured at 0 of 170 on the pipeline_probe sets. Off by default: it buys
  speed and accuracy on 4B, but slightly more false triggers on 1.7B.
- **stderr logging on failure.** When the HTTP call fails we log the exact
  exception before returning UNKNOWN. Early builds swallowed these errors
  silently, which cost hours during debugging when the model weights had
  actually become corrupted on disk and the failure looked identical to a
  classification miss. Never swallow again.
"""
import json
import sys
from pathlib import Path

from indepensense.intents.base import Intent, IntentResult

# Hard ceiling on generated tokens per query.
#
# The reply this parser wants is one small JSON object — the largest real
# one (`navigation.start` with a place name) is under 40 tokens. 128 leaves
# three times that headroom and still bounds the worst case, which is what
# this is for: without a cap a model that fails to emit a stop token
# generates until the context window fills, and on a Pi 5 CPU that is well
# past `NLU_TIMEOUT_S`. The user then waits the full timeout and gets
# `unknown` — the slowest possible way to say "I didn't understand".
#
# Not in `config.py` on purpose. This is dictated by the response schema the
# driver itself defines, so it is the chip-datasheet case rather than the
# tunable case; `_warmup`'s own 32 is here for the same reason. If a future
# intent needs a longer reply, this moves with the schema that changed it.
_MAX_OUTPUT_TOKENS = 128

# How much of a bad model reply to put in the log. Enough to recognise the
# shape of the failure, short enough that a runaway generation cannot flood
# the journal on a device with an SD card for a disk.
_LOG_EXCERPT_CHARS = 200

# The start of every reply under `compact_prefill`: written by us, continued
# by the model. Compact, so the model continues in the compact style; and the
# reply ends at the first newline, which compact JSON never contains.
_COMPACT_PREFIX = '{"intent":"'


class OllamaIntentParser:
    def __init__(
        self,
        model: str,
        ollama_url: str,
        prompt_path: Path,
        timeout_s: float = 30.0,
        warmup: bool = True,
        warmup_timeout_s: float = 90.0,
        compact_prefill: bool = False,
    ):
        self._model = model
        self._compact_prefill = compact_prefill
        endpoint = "/api/chat" if compact_prefill else "/api/generate"
        self._url = f"{ollama_url.rstrip('/')}{endpoint}"
        self._system_prompt = prompt_path.read_text()
        self._timeout_s = timeout_s

        if warmup:
            self._warmup(warmup_timeout_s)

    def _warmup(self, timeout_s: float) -> None:
        """Prime the model AND the system-prompt KV cache before real use.

        Uses the *same* system prompt real queries will use, so Ollama's
        prefix-cache is already computed on the first user query. Also
        pins the model with `keep_alive` so it doesn't get unloaded between
        queries.

        Failures are non-fatal — they will surface again on the next real
        query and the parser handles them there.
        """
        import time as _time
        import requests

        print(f"  Warming up {self._model} (up to {timeout_s:.0f}s if cold)...", flush=True)
        t0 = _time.time()
        try:
            # Built by the same method as a real query, so the warmed prefix
            # is the one queries reuse — in either request style.
            requests.post(self._url, json=self._payload("ok", 32), timeout=timeout_s)
            print(f"  Warmup done in {_time.time() - t0:.1f}s.", flush=True)
        except requests.RequestException as exc:
            print(
                f"  Warmup failed after {_time.time() - t0:.1f}s: {exc}. "
                f"Continuing anyway.",
                file=sys.stderr,
            )

    def _payload(self, transcript: str, num_predict: int) -> dict:
        """The request body, in whichever style this parser was built for."""
        common = {
            "model": self._model,
            "stream": False,
            "think": False,             # see module docstring
            "keep_alive": -1,           # keep model resident between queries
        }
        if not self._compact_prefill:
            return {
                **common,
                "system": self._system_prompt,
                "prompt": transcript,
                "format": "json",
                "options": {"temperature": 0.0, "num_predict": num_predict},
            }
        return {
            **common,
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": transcript},
                # A trailing assistant message is continued, not answered.
                {"role": "assistant", "content": _COMPACT_PREFIX},
            ],
            "options": {
                "temperature": 0.0,
                "num_predict": num_predict,
                "stop": ["\n"],
            },
        }

    def parse(self, transcript: str) -> IntentResult:
        import requests  # lazy: keeps the module importable off-device

        try:
            response = requests.post(
                self._url,
                json=self._payload(transcript, _MAX_OUTPUT_TOKENS),
                timeout=self._timeout_s,
            )
            response.raise_for_status()
            body = response.json()
            if self._compact_prefill:
                raw = _COMPACT_PREFIX + (body.get("message") or {}).get("content", "")
            else:
                raw = body.get("response", "")
        except (requests.RequestException, ValueError) as exc:
            print(f"[parser] Ollama request failed: {exc}", file=sys.stderr)
            return IntentResult(
                intent=Intent.UNKNOWN,
                parameters={},
                raw_transcript=transcript,
                raw_llm_response="",
                failure="transport",
            )

        return parse_llm_response(raw, transcript)


def parse_llm_response(raw: str, transcript: str) -> IntentResult:
    """Parse an LLM's raw JSON response into a normalised IntentResult.

    Pulled out as a pure function so it can be unit-tested without an LLM
    or an Ollama server.

    Both degraded paths below log to stderr before returning. Silence here
    is what made the last round of debugging expensive: a malformed reply
    and a legitimate "I don't understand" produced byte-identical results,
    so `journalctl` gave no way to tell a model that was misbehaving from
    users asking things the model correctly declined. See `IntentResult`
    for why only one of the two blocks the cloud fallback.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print(
            f"[parser] malformed JSON from model, treating as unknown: "
            f"{raw[:_LOG_EXCERPT_CHARS]!r}",
            file=sys.stderr,
        )
        return IntentResult(
            intent=Intent.UNKNOWN,
            parameters={},
            raw_transcript=transcript,
            raw_llm_response=raw,
            failure="malformed",
        )

    intent_name = payload.get("intent", "unknown")
    try:
        intent = Intent(intent_name)
    except ValueError:
        # Readable answer, unsupported label — a decline, not a failure, so
        # this still reaches the cloud. Logged because a name the prompt
        # never offered means the prompt or the model has drifted.
        print(
            f"[parser] model returned an intent name that does not exist: "
            f"{intent_name!r}",
            file=sys.stderr,
        )
        intent = Intent.UNKNOWN

    raw_params = payload.get("parameters") or {}
    if not isinstance(raw_params, dict):
        raw_params = {}
    parameters = _normalise_parameters(intent, raw_params)

    return IntentResult(
        intent=intent,
        parameters=parameters,
        raw_transcript=transcript,
        raw_llm_response=raw,
    )


def _normalise_parameters(intent: Intent, params: dict) -> dict:
    """Apply per-intent normalisation to the LLM's parameter dict.

    - unknown: strip all parameters (LLM sometimes hallucinates them)
    - navigation.start: ensure `nearest` is always present as a bool
    - system.language: fold the language name the model returned down to
      a code, so the executor only ever sees `"en"`, `"tl"`, or a value
      it can reject
    """
    if intent is Intent.UNKNOWN:
        return {}

    if intent is Intent.NAVIGATION_START:
        result = dict(params)
        result.setdefault("nearest", False)
        # Force to bool in case model returned a string like "true"
        result["nearest"] = _to_bool(result["nearest"])
        return result

    if intent is Intent.SYSTEM_LANGUAGE:
        result = dict(params)
        result["language"] = _to_language_code(result.get("language"))
        return result

    return dict(params)


# Language names the model returns instead of the codes the prompt asks
# for. Small models comply with the schema most of the time but not
# always, and a language switch failing because the model said "English"
# rather than "en" would be an avoidable dead end for the user.
_LANGUAGE_ALIASES: dict[str, str] = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "ingles": "en",
    "tl": "tl",
    "tgl": "tl",
    "tagalog": "tl",
    "filipino": "tl",
    "fil": "tl",
}


def _to_language_code(value: object) -> str:
    """Map whatever the model returned to a language code.

    Unrecognised values are passed through lowercased rather than
    defaulted to a supported language: the executor answers "I can only
    speak English and Tagalog", which is honest. Silently substituting a
    language the user did not ask for would be worse.
    """
    if not isinstance(value, str):
        return ""
    return _LANGUAGE_ALIASES.get(value.strip().lower(), value.strip().lower())


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)
