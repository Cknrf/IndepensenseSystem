"""Semantic fast path: a sentence-embedding nearest-neighbour matcher.

Sits in front of `OllamaIntentParser`. Most utterances the wearable hears
are short fixed requests — "repeat that", "nasaan ako", "tulong" — and
paying 1-2 s of local LLM generation to classify them is the largest
avoidable cost in a ~5 s STT → NLU → TTS chain. This module answers those
in tens of milliseconds and hands everything else to the LLM untouched.

What it can and cannot do
-------------------------

A sentence embedding is one vector for the **whole utterance**. Nearest
neighbour over a labelled bank therefore yields a *label and a score* —
never a span of the input. That is the whole design constraint: the
matcher can decide `vision.read`, but it can never produce
`{"location": "SM Lipa"}`, because the destination is a substring, not a
property of the sentence. Span extraction would need a token-level tagger
trained per slot; the LLM already does it, so it keeps that job.

This splits the intent table cleanly, and the split is static — decided
by which intent won, not by confidence:

- **No parameters** (`navigation.stop`, `.repeat`, `.location`,
  `.progress`, `emergency.trigger`, `system.time`, `.help`, `.shutdown`,
  `vision.describe`, `.read`) — the label alone is the complete answer.
- **Closed-enum slot** (`device.status`, `system.volume` direction,
  `system.language` between the two supported codes) — the slot value is
  folded into the label, so `device.status:battery` is simply its own
  class. A closed enum is just more labels.
- **Open span** (`navigation.start`, `place.save`, `place.delete`,
  a numeric volume, an unsupported language name) — always escalates.
  These appear in the bank only as negative examples.

Why this returns `Match | None` and not `IntentResult`
------------------------------------------------------

It deliberately does **not** implement `IntentParser`. A parser promises
an answer for every transcript; this cannot, by construction, for the
open-span intents above. Satisfying the protocol would mean inventing an
`IntentResult` for inputs it has no ability to classify. `None` means
"ask the LLM", and `TieredIntentParser` is the thing that implements
`IntentParser` by composing the two.

Why the fast path never answers `unknown`
-----------------------------------------

`unknown` is the sole trigger for the cloud fallback (see `cloud.py`), so
a false `unknown` does not merely fail — it forwards a real command to a
chatbot. Deciding that boundary was expensive to get right once, in the
system prompt. It stays there: "nothing cleared the bar" returns `None`
and the LLM decides, rather than the matcher asserting `unknown` itself.

Confidence: score *and* margin
------------------------------

Two conditions, not one. Absolute cosine similarity is poorly calibrated
— its useful range varies by model and by utterance length, and a short
transcript scores high against almost anything. The **margin** between
the best neighbour and the best neighbour *of a different class* is the
better signal: it asks "is this decision contested?" rather than "does
this look vaguely familiar?". Both must clear their threshold.

k-NN over individual examples, not per-class centroids
------------------------------------------------------

The escalate class is deliberately multi-modal: destinations, saved
places, chit-chat and near-misses have nothing in common but their
destination. A centroid of those lands in empty space and matches
nothing, which would silently disable every negative example in the bank
— the one part that carries the safety argument. Top-1 over individual
vectors has no such failure mode, and the bank is small enough (a few
hundred rows) that a full dot product is free next to the encode.

Model
-----

`intfloat/multilingual-e5-small` — 118M params, 384-dim, sentence-trained,
covering XLM-R's 100 languages including Tagalog. Chosen over XLM-R
itself, which is a masked-LM encoder: mean-pooled XLM-R vectors are known
to be poor under cosine similarity without sentence-level fine-tuning
(the result that produced SBERT from BERT), and at 278M params it costs
more RAM to do the job worse. e5 rides on the torch + transformers
install that YOLO and MMS-TTS already require, so it adds no second
inference runtime — the same argument that selected MMS-TTS.

e5 was trained with instruction prefixes and the model card specifies
`"query: "` on both sides for symmetric similarity. `_E5_PREFIX` is
applied to bank entries and transcripts alike; dropping it measurably
degrades the embedding, so it is not optional decoration.
"""
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from indepensense.intents.base import Intent

# Applied to every string before encoding. See the module docstring — this
# is part of the model's contract, not a tunable, so it lives here rather
# than in `config.py`.
_E5_PREFIX = "query: "

# Labels whose suffix after `:` is a closed-enum slot value, mapped to the
# parameter key that value belongs under. `device.status:battery` becomes
# `Intent.DEVICE_STATUS` with `{"status_field": "battery"}`.
#
# This is the label-space encoding the matcher itself defines, so it lives
# with the matcher. Note the values here are only the ones the fast path
# may answer: `system.volume` has no `level` entry because a numeric level
# is an open slot, and `system.language` covers only `en`/`tl` because any
# other language must reach the LLM to be rejected by name.
_ENUM_SLOT_KEYS: dict[Intent, str] = {
    Intent.DEVICE_STATUS: "status_field",
    Intent.SYSTEM_VOLUME: "direction",
    Intent.SYSTEM_LANGUAGE: "language",
}

# Intents the fast path may never answer, because at least one of their
# parameters is a span of the user's own words. Listed explicitly rather
# than inferred so that adding an intent with an open slot fails loudly
# here instead of quietly becoming answerable.
_OPEN_SPAN_INTENTS = frozenset({
    Intent.NAVIGATION_START,
    Intent.PLACE_SAVE,
    Intent.PLACE_DELETE,
    Intent.PLACE_LOCATE,
})

# Section label marking examples that must be handed to the LLM. Anything
# after the prefix is a human-readable bucket name, kept so the probe can
# report *which* kind of escalation won rather than a single lumped count.
_ESCALATE = "__escalate__"

_HEADING = re.compile(r"^##\s+(\S+)\s*$")


@dataclass(frozen=True)
class BankEntry:
    """One labelled example utterance, as read from the bank file."""
    text: str
    intent: Intent | None      # None for escalate rows
    parameters: dict[str, Any]
    bucket: str                # the raw section label, for reporting

    @property
    def decision(self) -> tuple:
        """What answering with this entry would actually do.

        Every escalate bucket collapses to one value. The margin measures
        whether the *decision* is contested, and two escalate buckets
        disagreeing is not a disagreement — the transcript goes to the
        LLM either way. Keying the margin on the raw bucket instead would
        report a confident escalation as a near-tie.
        """
        if self.intent is None:
            return (_ESCALATE,)
        return (self.intent, tuple(sorted(self.parameters.items())))


@dataclass(frozen=True)
class Match:
    """A fast-path hit.

    `parameters` is already in the shape the executor expects, so the
    caller can build an `IntentResult` from this without normalisation.

    `score` is cosine similarity to the nearest example. `margin` is the
    gap to the nearest example belonging to a *different* class, and is
    `score` itself when the bank holds only one class (which cannot
    happen in practice, but keeps the arithmetic total).
    """
    intent: Intent
    parameters: dict[str, Any]
    score: float
    margin: float
    matched_example: str


@dataclass(frozen=True)
class Rejection:
    """Why a transcript was not answered by the fast path.

    `reason` is one of:
      - `"below_score"`    — nothing in the bank was close enough
      - `"contested"`      — the top two decisions were too near each other
      - `"escalate_class"` — the winner was a negative example, working
                             as designed

    Only the probe reads this; `match()` collapses all three to None.
    They are kept apart because they call for different fixes: a
    `below_score` case wants another phrasing in the bank, a `contested`
    one wants the two classes pulled apart, and `escalate_class` wants
    nothing at all.
    """
    reason: str
    score: float
    margin: float
    bucket: str
    matched_example: str


def parse_bank(path: Path) -> list[BankEntry]:
    """Read `prompts/nlu_examples.md` into labelled entries.

    Pure and importable without torch, so the bank's structure is unit
    tested on a Mac with no model present.

    Raises `ValueError` on an unrecognised section label. Silently
    skipping one would drop a whole class out of the fast path, and the
    symptom — slightly lower coverage — is invisible. A typo in a heading
    should stop startup, not quietly shrink the bank.
    """
    entries: list[BankEntry] = []
    current: tuple[Intent | None, dict[str, Any], str] | None = None

    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.strip()

        heading = _HEADING.match(line)
        if heading:
            label = heading.group(1)
            try:
                current = (*_decode_label(label), label)
            except ValueError as exc:
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
            continue

        # Everything before the first heading is preamble; `#` lines
        # inside the bank are comments.
        if current is None or not line or line.startswith("#"):
            continue

        intent, parameters, bucket = current
        entries.append(
            BankEntry(text=line, intent=intent, parameters=dict(parameters), bucket=bucket)
        )

    return entries


def _decode_label(label: str) -> tuple[Intent | None, dict[str, Any]]:
    """Turn a section label into the intent + parameters it stands for."""
    if label.startswith(_ESCALATE):
        return None, {}

    name, _, enum_value = label.partition(":")
    try:
        intent = Intent(name)
    except ValueError:
        raise ValueError(f"unknown intent label {label!r}") from None

    if intent is Intent.UNKNOWN:
        raise ValueError(
            "the fast path may not answer `unknown` — it is the cloud "
            f"fallback's trigger. Move these rows under {_ESCALATE}."
        )
    if intent in _OPEN_SPAN_INTENTS:
        raise ValueError(
            f"{name!r} has a free-text parameter the matcher cannot "
            f"extract. It belongs under {_ESCALATE} as negative examples."
        )

    slot_key = _ENUM_SLOT_KEYS.get(intent)
    if slot_key and not enum_value:
        raise ValueError(f"{name!r} needs a slot value, e.g. {name}:<value>")
    if enum_value and not slot_key:
        raise ValueError(f"{name!r} takes no parameters, but label was {label!r}")

    return intent, ({slot_key: enum_value} if slot_key else {})


class EmbeddingMatcher:
    """Nearest-neighbour intent matcher over an encoded example bank.

    The model and the bank are loaded and encoded in `__init__`, not
    lazily on first use: the app's factory runs at startup, and a several
    hundred millisecond encode in front of the user's first command is
    exactly the cost this class exists to remove. Same reasoning as
    `OllamaIntentParser`'s warmup.
    """

    def __init__(
        self,
        model_name: str,
        bank_path: Path,
        score_threshold: float,
        margin_threshold: float,
    ):
        self._score_threshold = score_threshold
        self._margin_threshold = margin_threshold
        self._entries = parse_bank(bank_path)
        if not self._entries:
            raise ValueError(f"example bank {bank_path} is empty")

        self._model = self._load_model(model_name)
        self._vectors = self._encode([e.text for e in self._entries])

    def match(self, transcript: str) -> Match | None:
        """Classify `transcript`, or return None to escalate to the LLM.

        None covers all three escalation routes — nothing cleared the
        thresholds, the decision was contested, or the winner was an
        escalate example. The caller does not need to distinguish them;
        `explain()` does, for the probe.
        """
        best = self.explain(transcript)
        return best if isinstance(best, Match) else None

    def explain(self, transcript: str) -> "Match | Rejection":
        """Like `match`, but says why when it escalates.

        Split out so `embedding_probe` can report *which* gate rejected a
        case. Tuning a threshold against a lumped "escalated" count tells
        you nothing about which knob to turn.
        """
        query = self._encode([transcript])[0]
        scores = self._vectors @ query      # both sides are L2-normalised

        order = scores.argsort()[::-1]
        top = int(order[0])
        winner = self._entries[top]
        score = float(scores[top])

        margin = score
        for index in order[1:]:
            if self._entries[int(index)].decision != winner.decision:
                margin = score - float(scores[int(index)])
                break

        if score < self._score_threshold:
            return Rejection("below_score", score, margin, winner.bucket, winner.text)
        if margin < self._margin_threshold:
            return Rejection("contested", score, margin, winner.bucket, winner.text)
        if winner.intent is None:
            return Rejection("escalate_class", score, margin, winner.bucket, winner.text)

        return Match(
            intent=winner.intent,
            parameters=dict(winner.parameters),
            score=score,
            margin=margin,
            matched_example=winner.text,
        )

    def neighbours(self, transcript: str, k: int = 5) -> list[tuple[float, BankEntry]]:
        """The `k` nearest bank entries, nearest first. Diagnostics only.

        `explain` names the gate that rejected a transcript but only ever
        reports the *winner*, and for a `contested` rejection the winner
        is the less interesting half — what you need in order to fix the
        bank is the runner-up it was contested against. Deriving that from
        `score` and `margin` alone is not possible.

        Not used by `match`, and deliberately not folded into `explain`:
        the runtime needs one decision per utterance, and ranking the
        whole bank to hand back five rows it will discard is work on the
        voice thread's critical path. This is for `embedding_probe`.
        """
        query = self._encode([transcript])[0]
        scores = self._vectors @ query
        order = scores.argsort()[::-1][:k]
        return [(float(scores[i]), self._entries[int(i)]) for i in order]

    # -------------------------------------------------------------- internals

    @staticmethod
    def _load_model(model_name: str):
        # lazy: torch + sentence-transformers are Pi-only (requirements-pi.txt)
        from sentence_transformers import SentenceTransformer

        print(f"  Loading embedding model {model_name}...", flush=True)
        return SentenceTransformer(model_name)

    def _encode(self, texts: list[str]):
        return self._model.encode(
            [_E5_PREFIX + t for t in texts],
            normalize_embeddings=True,   # lets cosine collapse to a dot product
            show_progress_bar=False,
        )


def build_matcher(
    model_name: str,
    bank_path: Path,
    score_threshold: float,
    margin_threshold: float,
) -> EmbeddingMatcher | None:
    """Construct a matcher, or None if it cannot be built.

    Never raises. The fast path is an optimisation: without it the
    wearable behaves exactly as it does today, sending every transcript
    to the LLM. Aborting startup because a model file is missing would
    trade a working degraded device for a dead one.

    A malformed bank is reported the same way but is a genuine bug —
    hence the stderr log, which is the only signal that the device is
    silently running without its fast path.
    """
    try:
        return EmbeddingMatcher(
            model_name=model_name,
            bank_path=bank_path,
            score_threshold=score_threshold,
            margin_threshold=margin_threshold,
        )
    except Exception as exc:    # noqa: BLE001 - see docstring
        print(
            f"[embeddings] fast path unavailable, every utterance will go "
            f"to the LLM: {exc}",
            file=sys.stderr,
        )
        return None
