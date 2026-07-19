"""Ollama-backed intent parser.

Thin wrapper around a local Ollama HTTP server. Sends each transcript with
the system prompt from `prompts/nlu_system.md`, requests JSON-formatted
output, and normalises the response into an `IntentResult`.

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

- **Startup warmup with full system prompt.** Cold-loading Qwen 2.5 1.5B on
  the Pi 5 takes ~25-40 s. Doing this once at construction — with the
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
  itself restarts. Costs ~1.4 GB of RAM permanently but that budget was
  planned for.
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


class OllamaIntentParser:
    def __init__(
        self,
        model: str,
        ollama_url: str,
        prompt_path: Path,
        timeout_s: float = 30.0,
        warmup: bool = True,
        warmup_timeout_s: float = 90.0,
    ):
        self._model = model
        self._url = f"{ollama_url.rstrip('/')}/api/generate"
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
            requests.post(
                self._url,
                json={
                    "model": self._model,
                    "system": self._system_prompt,     # same prompt → warms prefix cache
                    "prompt": "ok",
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.0, "num_predict": 32},
                    "keep_alive": -1,
                },
                timeout=timeout_s,
            )
            print(f"  Warmup done in {_time.time() - t0:.1f}s.", flush=True)
        except requests.RequestException as exc:
            print(
                f"  Warmup failed after {_time.time() - t0:.1f}s: {exc}. "
                f"Continuing anyway.",
                file=sys.stderr,
            )

    def parse(self, transcript: str) -> IntentResult:
        import requests  # lazy: keeps the module importable off-device

        payload = {
            "model": self._model,
            "system": self._system_prompt,
            "prompt": transcript,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
            "keep_alive": -1,           # keep model resident between queries
        }
        try:
            response = requests.post(self._url, json=payload, timeout=self._timeout_s)
            response.raise_for_status()
            raw = response.json().get("response", "")
        except (requests.RequestException, ValueError) as exc:
            print(f"[parser] Ollama request failed: {exc}", file=sys.stderr)
            return IntentResult(
                intent=Intent.UNKNOWN,
                parameters={},
                raw_transcript=transcript,
                raw_llm_response="",
            )

        return parse_llm_response(raw, transcript)


def parse_llm_response(raw: str, transcript: str) -> IntentResult:
    """Parse an LLM's raw JSON response into a normalised IntentResult.

    Pulled out as a pure function so it can be unit-tested without an LLM
    or an Ollama server.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return IntentResult(
            intent=Intent.UNKNOWN,
            parameters={},
            raw_transcript=transcript,
            raw_llm_response=raw,
        )

    intent_name = payload.get("intent", "unknown")
    try:
        intent = Intent(intent_name)
    except ValueError:
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
    """
    if intent is Intent.UNKNOWN:
        return {}

    if intent is Intent.NAVIGATION_START:
        result = dict(params)
        result.setdefault("nearest", False)
        # Force to bool in case model returned a string like "true"
        result["nearest"] = _to_bool(result["nearest"])
        return result

    return dict(params)


def _to_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)
