"""Deterministic mock intent parser for off-device development.

Simple keyword matching — enough to exercise executor logic on a Mac
without spinning up Ollama. Not a substitute for the real LLM in accuracy
or coverage.
"""
from indepensense.intents.base import CloudAnswer, Intent, IntentResult


class MockIntentParser:
    """Keyword-based fake for unit tests and Mac development.

    Matches loosely — the point is to produce a plausible IntentResult for
    common phrasings, not to be a real classifier. When you need real
    accuracy, use OllamaIntentParser.
    """

    def parse(self, transcript: str) -> IntentResult:
        text = transcript.lower().strip()

        # Checked before emergency, and only on whole phrasings: the
        # emergency test below matches "help" as a substring, so
        # "what can you do to help" would otherwise fire an alert. The real
        # prompt draws the same line — bare "help" is a cry for help, a
        # sentence asking about abilities is not.
        if any(w in text for w in (
            "what can you do",
            "what can i ask",
            "how do i use",
            "kaya mong gawin",
            "paano ito gamitin",
            "anong mga utos",
        )):
            return IntentResult(Intent.SYSTEM_HELP, {}, transcript, "")

        if any(w in text for w in ("emergency", "help", "sos", "tulong")):
            return IntentResult(Intent.EMERGENCY_TRIGGER, {}, transcript, "")

        # Language switching. Checked before the other intents because
        # "switch to English" contains no keyword that would collide, and
        # putting it first keeps the target-language extraction simple.
        if any(w in text for w in ("switch to", "speak", "lumipat sa", "magsalita")):
            if any(w in text for w in ("english", "ingles")):
                return IntentResult(
                    Intent.SYSTEM_LANGUAGE, {"language": "en"}, transcript, "",
                )
            if any(w in text for w in ("tagalog", "filipino", "tagalog na")):
                return IntentResult(
                    Intent.SYSTEM_LANGUAGE, {"language": "tl"}, transcript, "",
                )

        # Saved places. Checked before navigation so "save this place as
        # home" isn't caught by a destination prefix, and before the
        # generic matchers so the label survives intact.
        for prefix in (
            "save this place as ",
            "save this as ",
            "remember this as ",
            "i-save mo ito bilang ",
            "tandaan mo ito bilang ",
        ):
            if text.startswith(prefix):
                return IntentResult(
                    Intent.PLACE_SAVE,
                    {"label": transcript.strip()[len(prefix):].strip()},
                    transcript,
                    "",
                )

        for prefix in (
            "forget the place saved as ",
            "forget the place ",
            "delete the place ",
            "kalimutan mo ang ",
            "burahin mo ang ",
        ):
            if text.startswith(prefix):
                return IntentResult(
                    Intent.PLACE_DELETE,
                    {"label": transcript.strip()[len(prefix):].strip()},
                    transcript,
                    "",
                )

        # Volume. Before the language matcher, which claims "speak" —
        # "speak louder" is a volume request, not a language switch.
        if any(w in text for w in ("volume", "louder", "quieter", "lakas ng tunog",
                                   "palakasin", "pahinaan", "hinaan", "lakasan")):
            import re
            match = re.search(r"(\d+)", text)
            if match:
                return IntentResult(
                    Intent.SYSTEM_VOLUME, {"level": int(match.group(1))},
                    transcript, "",
                )
            if any(w in text for w in ("louder", "up", "palakasin", "lakasan",
                                       "increase", "raise")):
                return IntentResult(
                    Intent.SYSTEM_VOLUME, {"direction": "up"}, transcript, "",
                )
            if any(w in text for w in ("quieter", "down", "pahinaan", "hinaan",
                                       "lower", "decrease", "softer")):
                return IntentResult(
                    Intent.SYSTEM_VOLUME, {"direction": "down"}, transcript, "",
                )
            return IntentResult(Intent.SYSTEM_VOLUME, {}, transcript, "")

        if any(w in text for w in ("cancel navigation", "stop navigation", "ihinto")):
            return IntentResult(Intent.NAVIGATION_STOP, {}, transcript, "")

        if any(w in text for w in ("repeat", "say that again", "ulitin")):
            return IntentResult(Intent.NAVIGATION_REPEAT, {}, transcript, "")

        # Before the "where am i" matcher: "how much further am i" would
        # otherwise be caught by it and answered with the wrong question.
        if any(w in text for w in (
            "how far", "how much further", "how much longer", "how far along",
            "gaano pa kalayo", "malayo pa ba", "ilan pa",
        )):
            return IntentResult(Intent.NAVIGATION_PROGRESS, {}, transcript, "")

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

        # Ordered longest-first where prefixes overlap: "take me to X" must
        # match before the bare "take me X", or the destination would come
        # out as "to X". The bare forms are what reach a saved place —
        # "take me home" has no preposition.
        for prefix in (
            "navigate to ",
            "take me to ",
            "take me ",
            "guide me to ",
            "bring me to ",
            "go to ",
            "dalhin mo ako sa ",
            "dalhin mo ako ",
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


class MockCloudAnswerer:
    """Scripted cloud LLM for off-device development and unit tests.

    Defaults to echoing a plausible short answer so the fallback path can
    be exercised without a provider or an API key. Configure `reason` to
    rehearse the failure paths — `"offline"` and `"error"` produce
    different spoken responses and both need testing.

    `asked` records every (question, language) pair, which is how a test
    asserts that the transcript really was forwarded and that the active
    language was passed through rather than assumed.
    """

    def __init__(self, text: str | None = None, reason: str = "ok"):
        self._text = text
        self._reason = reason
        self.asked: list[tuple[str, str]] = []

    def answer(self, question: str, language: str) -> CloudAnswer:
        self.asked.append((question, language))
        if self._reason != "ok":
            return CloudAnswer(text=None, reason=self._reason)
        if self._text is not None:
            return CloudAnswer(text=self._text, reason="ok")
        # Deliberately mentions the question so a test can tell the
        # transcript was forwarded, and differs per language so a
        # language-passing bug is visible.
        prefix = "Ayon sa cloud" if language == "tl" else "According to the cloud"
        return CloudAnswer(text=f"{prefix}: {question}", reason="ok")
