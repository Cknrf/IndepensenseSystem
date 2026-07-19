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
non-JSON responses. The parser never raises for malformed model output —
it degrades gracefully to `UNKNOWN` so the executor can respond with a
"sorry, I didn't understand" message rather than crashing.
"""
import json
from pathlib import Path

from indepensense.intents.base import Intent, IntentResult


class OllamaIntentParser:
    def __init__(
        self,
        model: str,
        ollama_url: str,
        prompt_path: Path,
        timeout_s: float = 20.0,
    ):
        self._model = model
        self._url = f"{ollama_url.rstrip('/')}/api/generate"
        self._system_prompt = prompt_path.read_text()
        self._timeout_s = timeout_s

    def parse(self, transcript: str) -> IntentResult:
        import requests  # lazy: keeps the module importable off-device

        payload = {
            "model": self._model,
            "system": self._system_prompt,
            "prompt": transcript,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0},
        }
        try:
            response = requests.post(self._url, json=payload, timeout=self._timeout_s)
            response.raise_for_status()
            raw = response.json().get("response", "")
        except (requests.RequestException, ValueError):
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
