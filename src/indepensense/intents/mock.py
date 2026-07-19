"""Deterministic mock intent parser for off-device development.

Simple keyword matching — enough to exercise executor logic on a Mac
without spinning up Ollama. Not a substitute for the real LLM in accuracy
or coverage.
"""
from indepensense.intents.base import Intent, IntentResult


class MockIntentParser:
    """Keyword-based fake for unit tests and Mac development.

    Matches loosely — the point is to produce a plausible IntentResult for
    common phrasings, not to be a real classifier. When you need real
    accuracy, use OllamaIntentParser.
    """

    def parse(self, transcript: str) -> IntentResult:
        text = transcript.lower().strip()

        if any(w in text for w in ("emergency", "help", "sos", "tulong")):
            return IntentResult(Intent.EMERGENCY_TRIGGER, {}, transcript, "")

        if any(w in text for w in ("cancel navigation", "stop navigation", "ihinto")):
            return IntentResult(Intent.NAVIGATION_STOP, {}, transcript, "")

        if any(w in text for w in ("repeat", "say that again", "ulitin")):
            return IntentResult(Intent.NAVIGATION_REPEAT, {}, transcript, "")

        if any(w in text for w in ("where am i", "nasaan ako", "my location", "my address")):
            return IntentResult(Intent.NAVIGATION_LOCATION, {}, transcript, "")

        if "time" in text or "oras" in text:
            return IntentResult(Intent.SYSTEM_TIME, {}, transcript, "")

        if "battery" in text:
            return IntentResult(
                Intent.DEVICE_STATUS, {"status_field": "battery"}, transcript, ""
            )
        if "gps" in text:
            return IntentResult(
                Intent.DEVICE_STATUS, {"status_field": "gps"}, transcript, ""
            )
        if "signal" in text:
            return IntentResult(
                Intent.DEVICE_STATUS, {"status_field": "signal"}, transcript, ""
            )

        for prefix in (
            "navigate to ",
            "take me to ",
            "guide me to ",
            "bring me to ",
            "go to ",
            "dalhin mo ako sa ",
            "puntahan mo ang ",
        ):
            if text.startswith(prefix):
                destination = text[len(prefix):].strip()
                nearest = any(
                    m in destination for m in ("nearest", "closest", "pinakamalapit", "malapit na")
                )
                for m in ("nearest ", "closest ", "pinakamalapit na ", "pinakamalapit ", "malapit na "):
                    destination = destination.replace(m, "")
                destination = destination.strip()
                return IntentResult(
                    Intent.NAVIGATION_START,
                    {"location": destination, "nearest": nearest},
                    transcript,
                    "",
                )

        return IntentResult(Intent.UNKNOWN, {}, transcript, "")
