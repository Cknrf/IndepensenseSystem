"""Two-stage intent parsing: semantic fast path, then the local LLM.

`TieredIntentParser` is the only thing in the intents layer that
implements `IntentParser` twice over — it composes an `EmbeddingMatcher`
(tens of milliseconds, answers the utterances whose parameters are fully
determined by the intent) with `OllamaIntentParser` (1-2 s, answers
everything else) and presents the pair as one parser.

Everything downstream is unchanged by construction. The executor, the
cloud fallback, `messages.py` and every existing test still see a single
object satisfying `IntentParser` and returning `IntentResult`. That is
the reason this is a wrapper rather than a branch inside `parse()`: the
two engines have genuinely different failure modes and one of them is
optional, and folding both into `OllamaIntentParser` would put an
`if self._matcher is not None` in the middle of a driver that currently
does one thing.

What the fast path may decide
-----------------------------

Only what `EmbeddingMatcher` returns a `Match` for — see the constraints
in `embeddings.py`. Three consequences are load-bearing here:

- **A miss is not a failure.** `failure` stays `None` on the fast path
  and is set only by the LLM, so the `IntentResult` contract in `base.py`
  is untouched: `failure` still means "we hold no usable classification",
  never "the first stage declined". If it leaked a value here, an
  escalation would look like an Ollama timeout and `cloud.py` would stop
  forwarding genuine questions.

- **The fast path cannot produce `unknown`,** so it can never be the
  thing that sends a transcript to the cloud. That decision stays with
  the LLM and its system prompt, where it was tuned.

- **No matcher means no fast path.** A `None` matcher is the normal
  degraded state, not an error: every transcript goes to the LLM, which
  is exactly the behaviour before this layer existed.

Latency
-------

The fast path is on the critical path for *every* utterance, including
the ones it declines — a miss costs its ~20-30 ms before the LLM even
starts. That is under 2% of the LLM's own 1-2 s, so the expected saving
is positive as long as capture is meaningfully above zero. Measured at
86% capture on the held-out probe set; see `config.py` for the table.
"""
import sys

from indepensense.intents.base import Intent, IntentParser, IntentResult
from indepensense.intents.embeddings import EmbeddingMatcher


class TieredIntentParser:
    """An `IntentParser` that tries embeddings first, then the LLM."""

    def __init__(self, matcher: EmbeddingMatcher | None, llm: IntentParser):
        self._matcher = matcher
        self._llm = llm

    def parse(self, transcript: str) -> IntentResult:
        match = self._try_match(transcript)
        if match is None:
            return self._llm.parse(transcript)

        return IntentResult(
            intent=match.intent,
            parameters=dict(match.parameters),
            raw_transcript=transcript,
            # No LLM was called, so there is no response to record. The
            # matched example and its scores are the equivalent audit
            # trail — `raw_llm_response` is what a reader greps when a
            # wrong action needs explaining, and leaving it empty here
            # would make a fast-path mistake the one kind with no record.
            raw_llm_response=(
                f'{{"matched": {match.matched_example!r}, '
                f'"score": {match.score:.4f}, "margin": {match.margin:.4f}}}'
            ),
            failure=None,
            source="embedding",
        )

    def _try_match(self, transcript: str):
        """Run the fast path, treating any error in it as a miss.

        The matcher is an optimisation sitting in front of a working
        parser. A bug in it — a model that unloaded, a shape the encoder
        rejects — must degrade to the LLM, not fail the utterance. The
        user is mid-command and the LLM can still answer.
        """
        if self._matcher is None:
            return None
        try:
            return self._matcher.match(transcript)
        except Exception as exc:    # noqa: BLE001 - see docstring
            print(
                f"[tiered] fast path errored, falling back to the LLM: {exc}",
                file=sys.stderr,
            )
            return None


def describe(result: IntentResult) -> str:
    """One-line summary for the voice thread's log.

    Exists so the engine that answered is visible in `journalctl` without
    the caller reaching into `source` and formatting it at each site. The
    fast path's whole risk is a confident wrong answer, and the first
    question when one is reported will be which stage produced it.
    """
    detail = f" [{result.failure}]" if result.failure else ""
    if result.intent is Intent.UNKNOWN and not result.failure:
        detail = " [declined]"
    return f"{result.intent.value} via {result.source}{detail}"
