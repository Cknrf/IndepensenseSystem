"""Types and protocols for the intent-recognition layer.

An `IntentParser` turns a raw transcript string into a structured
`IntentResult` (intent name + typed parameters). An `IntentExecutor` takes
an `IntentResult` and the running system's service dependencies and
performs the requested action, returning the response text that the TTS
layer will speak.

Intent names are namespaced strings (e.g. `navigation.start`) both in the
JSON exchanged with the LLM and in the `Intent` enum values. New intent
categories go under new namespaces (`vision.describe`, `ocr.read`,
`guardian.alert`, ...) without touching existing ones.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol


class Intent(Enum):
    NAVIGATION_START = "navigation.start"
    NAVIGATION_STOP = "navigation.stop"
    NAVIGATION_REPEAT = "navigation.repeat"
    NAVIGATION_LOCATION = "navigation.location"
    NAVIGATION_PROGRESS = "navigation.progress"
    EMERGENCY_TRIGGER = "emergency.trigger"
    DEVICE_STATUS = "device.status"
    SYSTEM_TIME = "system.time"
    VISION_DESCRIBE = "vision.describe"
    VISION_READ = "vision.read"
    SYSTEM_LANGUAGE = "system.language"
    SYSTEM_HELP = "system.help"
    SYSTEM_VOLUME = "system.volume"
    SYSTEM_SHUTDOWN = "system.shutdown"
    PLACE_SAVE = "place.save"
    PLACE_DELETE = "place.delete"
    PLACE_LIST = "place.list"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentResult:
    """The structured output of parsing one user utterance.

    `parameters` are already normalised (e.g. `navigation.start` responses
    are guaranteed to have `nearest` present; `unknown` responses always
    have an empty parameters dict).

    `raw_llm_response` is retained for debugging and audit — if a downstream
    surprise appears, we can inspect exactly what the LLM produced.

    `failure` separates "the model declined" from "the model never usably
    answered". Both used to arrive as a bare `UNKNOWN`, which made a 30 s
    Ollama timeout indistinguishable from a genuine "I don't understand" —
    and since `unknown` is the cloud fallback's trigger, an Ollama hiccup
    during "take me to the hospital" forwarded that sentence to a chatbot.
    `intents/cloud.py` justifies the whole fallback on the premise that the
    cloud only sees utterances the local model already declined; this field
    is what makes the premise true.

    - `None` — the model answered. `UNKNOWN` here means it really did
      decline, and the cloud may take the question.
    - `"transport"` — the request failed or timed out. There is no output.
    - `"malformed"` — a reply arrived but was not valid JSON.

    The last two both mean *we hold no usable classification*, so we cannot
    know the utterance was not a real command. Neither may reach the cloud.
    An intent name outside the enum is deliberately **not** a failure: that
    is a readable answer that maps to nothing we support, which is a
    decline.

    `source` names the engine that produced this result — `"embedding"`
    for the semantic fast path, `"llm"` for the local model. Two engines
    now answer utterances and nothing else on this object distinguishes
    them, which would make a journald line describing a wrong action
    unattributable to the thing that produced it. It is also the raw
    material for the fast path's hit rate, which is a measured result
    rather than a claim. Defaults to `"llm"` so every existing
    construction site keeps meaning what it already meant.
    """
    intent: Intent
    parameters: dict[str, Any] = field(default_factory=dict)
    raw_transcript: str = ""
    raw_llm_response: str = ""
    failure: str | None = None
    source: str = "llm"


class IntentParser(Protocol):
    def parse(self, transcript: str) -> IntentResult:
        """Turn a transcript into a structured intent + parameters."""


@dataclass(frozen=True)
class CloudAnswer:
    """The result of asking a cloud LLM an open question.

    `text` is the spoken answer, or None when there isn't one. `reason`
    says why, and exists so the wearable can tell the user something
    specific instead of a generic failure:

      - "ok"       — `text` holds the answer
      - "offline"  — no internet; nothing was sent anywhere
      - "error"    — reached the provider but got no usable answer
                     (timeout, rate limit, bad key, refusal)

    The distinction matters to the user: "no internet connection" is
    actionable — move somewhere with signal — while a provider error is
    not, and telling them the wrong one wastes their time.
    """
    text: str | None = None
    reason: str = "ok"


class CloudAnswerer(Protocol):
    def answer(
        self,
        question: str,
        language: str,
        previous: tuple[str, str] | None = None,
    ) -> CloudAnswer:
        """Answer an open question that local intents couldn't handle.

        `question` is the user's transcript — text only. The recorded
        audio never leaves the device; see `intents/cloud.py`.

        `language` is the code the answer must come back in, so the
        provider replies in the language the user is speaking rather than
        forcing a translation step.

        `previous` is the `(question, answer)` of the last cloud exchange,
        or None. It exists because people ask follow-ups: "what is the
        tallest mountain" then "what about the second". Without it the
        second question is unanswerable, and the wearable said so — a
        field log has the user rephrasing the same question three times.

        Implementations must not raise — report failure via `reason`. The
        answer should be short enough to speak aloud; the executor
        truncates as a backstop but a provider returning three paragraphs
        makes for a poor spoken response even truncated.
        """


class IntentExecutor(Protocol):
    def execute(self, result: IntentResult) -> str:
        """Perform the action described by `result` and return the response
        text to be spoken to the user."""
