"""Primary parser with a local fallback — the cloud/Ollama handover.

`FallbackIntentParser` wraps two `IntentParser`s and presents one. The
primary is the cloud model; the fallback is Ollama. If the primary
returns a usable classification it is used, and if it does not, the
local model answers instead.

Why a third wrapper rather than a branch in `TieredIntentParser`
----------------------------------------------------------------

`tiered.py` is itself a wrapper rather than a branch inside
`OllamaIntentParser`, and its docstring gives the reason: the engines
have genuinely different failure modes and one of them is optional, so
folding them together would put an `if` in the middle of a driver that
does one thing. That argument did not stop applying when a third engine
arrived. Composed instead:

    TieredIntentParser(matcher, llm=FallbackIntentParser(cloud, ollama))

so the fast path still decides first, and only the escalated utterances
reach the network at all. The two-stage story in `tiered.py` is
unchanged, this class is testable with two mocks and no network, and
`app.py` wires it in one place.

What counts as "the primary failed"
-----------------------------------

Exactly `IntentResult.failure is not None` — nothing new is invented
here, because `base.py` already drew this line for the Ollama-timeout
case and `cloud.py` already depends on it:

  - `"transport"` — the request failed, timed out, or was refused
  - `"malformed"` — a reply arrived that was not usable JSON

**A clean `unknown` is not a failure and must not fall back.** That is
the single most important line in this module. `unknown` with
`failure=None` means the model understood and declined, which is the
cloud *answerer's* trigger in `cloud.py`. Falling back there would be
wrong twice over: it would spend a local inference re-answering
something already answered correctly, and the local model's much lower
`unknown` recall means it would often reclassify a genuine open question
into a bogus intent — destroying the exact improvement the cloud was
added to buy.

Equally, the fallback's own result is returned as-is, failure and all.
A `transport` from Ollama after a `transport` from the cloud is the
honest answer: both engines are down, the caller must hear that rather
than a fabricated decline.
"""
import sys

from indepensense.intents.base import IntentParser, IntentResult


class FallbackIntentParser:
    """Try `primary`; on a failed classification, ask `fallback`."""

    def __init__(self, primary: IntentParser, fallback: IntentParser):
        self._primary = primary
        self._fallback = fallback

    def warm_up(self, timeout_s: float) -> None:
        """Warm both engines, since either may answer.

        The budget is passed to each rather than split: they warm
        different things — a TLS session and a remote prefix cache on one
        side, ~2,500 tokens of local prefill on the other — and halving
        the local model's allowance would make it time out for no reason.
        Called on the voice-stack thread, never from `start()`.

        A primary that cannot be warmed is not fatal. It is also not
        silent: the fallback is slower, and a device quietly running on
        the slow path for a week is the outcome this print exists to
        prevent.
        """
        for name, engine in (("primary", self._primary), ("fallback", self._fallback)):
            warm = getattr(engine, "warm_up", None)
            if warm is None:
                continue
            try:
                warm(timeout_s)
            except Exception as exc:   # noqa: BLE001 - see docstring
                print(f"[fallback] {name} warmup failed: {exc}", file=sys.stderr)

    def parse(self, transcript: str) -> IntentResult:
        result = self._try_primary(transcript)

        if result is not None and result.failure is None:
            return result

        if result is not None:
            # Logged at the moment of handover rather than inferred later
            # from two lines in different modules. `source` on the final
            # result says which engine answered; this says why the first
            # one did not, which is the question asked when the device is
            # unexpectedly slow.
            print(
                f"[fallback] cloud returned {result.failure!r}, "
                f"falling back to the local model",
                file=sys.stderr,
            )

        return self._fallback.parse(transcript)

    def _try_primary(self, transcript: str) -> IntentResult | None:
        """Run the primary, treating a raised exception as a failure.

        `MistralIntentParser` is documented never to raise, and its tests
        pin that. This exists for the case where it does anyway — a
        provider SDK swapped in later, a bug in a future driver. The
        caller is the voice thread, where an escaping exception reaches
        the user as silence, and there is a working local model one line
        away.
        """
        try:
            return self._primary.parse(transcript)
        except Exception as exc:   # noqa: BLE001 - see docstring
            print(
                f"[fallback] primary parser raised, falling back: {exc}",
                file=sys.stderr,
            )
            return None

    def close(self) -> None:
        """Release whichever engines hold resources — the cloud parser's
        HTTP session, in practice. Tolerates engines without `close`,
        since `IntentParser` does not require it."""
        for engine in (self._primary, self._fallback):
            closer = getattr(engine, "close", None)
            if closer is not None:
                closer()
