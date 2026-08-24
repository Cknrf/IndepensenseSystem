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
    EMERGENCY_TRIGGER = "emergency.trigger"
    DEVICE_STATUS = "device.status"
    SYSTEM_TIME = "system.time"
    VISION_DESCRIBE = "vision.describe"
    VISION_READ = "vision.read"
    SYSTEM_LANGUAGE = "system.language"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class IntentResult:
    """The structured output of parsing one user utterance.

    `parameters` are already normalised (e.g. `navigation.start` responses
    are guaranteed to have `nearest` present; `unknown` responses always
    have an empty parameters dict).

    `raw_llm_response` is retained for debugging and audit — if a downstream
    surprise appears, we can inspect exactly what the LLM produced.
    """
    intent: Intent
    parameters: dict[str, Any] = field(default_factory=dict)
    raw_transcript: str = ""
    raw_llm_response: str = ""


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
    def answer(self, question: str, language: str) -> CloudAnswer:
        """Answer an open question that local intents couldn't handle.

        `question` is the user's transcript — text only. The recorded
        audio never leaves the device; see `intents/cloud.py`.

        `language` is the code the answer must come back in, so the
        provider replies in the language the user is speaking rather than
        forcing a translation step.

        Implementations must not raise — report failure via `reason`. The
        answer should be short enough to speak aloud; the executor
        truncates as a backstop but a provider returning three paragraphs
        makes for a poor spoken response even truncated.
        """


class IntentExecutor(Protocol):
    def execute(self, result: IntentResult) -> str:
        """Perform the action described by `result` and return the response
        text to be spoken to the user."""
