"""Unit tests for `EmbeddingMatcher`'s decision and diagnostic surfaces.

The encoder is Pi-only (`requirements-pi.txt`), so these inject a stub in
place of `_load_model` and hand-pick vectors. That is not a compromise —
it is the only way to assert *exact* ordering and margin arithmetic. With
a real model the numbers move whenever the weights or the bank change,
and the test would be checking the encoder rather than this class.

The scored end-to-end behaviour lives in `tests/manual/embedding_probe`,
which needs the real model and reports coverage and precision.
"""
import math

import numpy as np
import pytest

from indepensense.intents.base import Intent
from indepensense.intents.embeddings import EmbeddingMatcher, Match, Rejection


class _StubEncoder:
    """Returns a fixed vector per text, so distances are chosen by hand.

    Unknown texts encode to a unit vector pointing nowhere near the bank,
    which makes "nothing matched" expressible without inventing a number.
    """

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        out = []
        for text in texts:
            # The matcher prefixes everything with "query: " per the e5
            # model card; strip it so the fixtures stay readable.
            key = text.removeprefix("query: ")
            vector = np.array(self._vectors.get(key, [0.0, 0.0, 1.0]), dtype="float32")
            if normalize_embeddings:
                vector = vector / np.linalg.norm(vector)
            out.append(vector)
        return np.stack(out)


def _unit(degrees: float) -> list[float]:
    """A 3-D unit vector at `degrees` from the x-axis, in the xy plane.

    Cosine similarity between two of these is just the cosine of the angle
    between them, so a fixture reads as "0.90 similar" rather than as
    three opaque floats.
    """
    radians = math.radians(degrees)
    return [math.cos(radians), math.sin(radians), 0.0]


# A bank where every row's similarity to the query is set by its angle.
# The query sits at 0°, so smaller angle == nearer.
_BANK = """
## system.time

near-time
mid-time
far-time

Anong oras na

## vision.describe

near-vision

Ano ang nasa harap

## __escalate__:chitchat

near-escalate

Kumusta ka
"""

_VECTORS = {
    "the query":      _unit(0),
    "near-time":      _unit(16),     # cos ~0.961
    "mid-time":       _unit(20),     # cos ~0.940
    "far-time":       _unit(30),     # cos ~0.866
    "near-vision":    _unit(24),     # cos ~0.914
    "near-escalate":  _unit(36),     # cos ~0.809
    # The Tagalog rows exist only so the bank is well formed; park them
    # far away so they never participate.
    "Anong oras na":     _unit(80),
    "Ano ang nasa harap": _unit(85),
    "Kumusta ka":        _unit(88),
}


@pytest.fixture
def matcher(tmp_path, monkeypatch):
    """A matcher over `_BANK`, with the encoder stubbed out."""
    bank = tmp_path / "bank.md"
    bank.write_text(_BANK)
    monkeypatch.setattr(
        EmbeddingMatcher, "_load_model",
        staticmethod(lambda _name: _StubEncoder(_VECTORS)),
    )

    def _build(score_threshold=0.86, margin_threshold=0.02):
        return EmbeddingMatcher(
            model_path=tmp_path / "stub",
            bank_path=bank,
            score_threshold=score_threshold,
            margin_threshold=margin_threshold,
        )

    return _build


# --- neighbours() ------------------------------------------------------------

def test_neighbours_are_ordered_nearest_first(matcher):
    ranked = matcher().neighbours("the query", k=4)
    assert [entry.text for _score, entry in ranked] == [
        "near-time", "mid-time", "near-vision", "far-time",
    ]


def test_neighbours_respects_k(matcher):
    assert len(matcher().neighbours("the query", k=2)) == 2


def test_neighbours_reports_the_bucket_that_explains_a_rejection(matcher):
    """The reason `neighbours` exists: `explain` names the winner, but a
    `contested` verdict is only actionable once you know which other class
    it was contested against."""
    ranked = matcher().neighbours("the query", k=3)
    buckets = [entry.bucket for _score, entry in ranked]
    assert buckets == ["system.time", "system.time", "vision.describe"]


def test_neighbours_does_not_disturb_the_decision(matcher):
    """It is a diagnostic. Calling it must not change what `match` says —
    the probe interleaves the two."""
    instance = matcher()
    before = instance.match("the query")
    instance.neighbours("the query", k=5)
    after = instance.match("the query")
    assert before == after


# --- the margin gate ---------------------------------------------------------

def test_margin_is_measured_against_the_nearest_different_decision(matcher):
    """Not against the runner-up. `near-time` and `mid-time` agree, so the
    margin is the gap to `near-vision` — 0.961 - 0.914."""
    result = matcher(margin_threshold=0.0).explain("the query")
    assert isinstance(result, Match)
    assert result.intent is Intent.SYSTEM_TIME
    assert result.margin == pytest.approx(0.961 - 0.914, abs=1e-3)


def test_a_unanimous_top_k_is_still_rejected_when_the_margin_is_thin(matcher):
    """Documents the rule as it stands, because it surprised us in the
    field: four agreeing neighbours do not outvote one close competitor
    from another class. `embedding_probe --try` showed real transcripts
    escalating this way with their top four unanimous."""
    result = matcher(margin_threshold=0.05).explain("the query")
    assert isinstance(result, Rejection)
    assert result.reason == "contested"
    # The winner really was the unanimous class — this is a margin
    # rejection, not a disagreement about which class is nearest.
    assert result.bucket == "system.time"


def test_score_gate_rejects_before_the_margin_gate(matcher):
    """`below_score` and `contested` call for different fixes, so a case
    that fails both must report the one a reader should act on first."""
    result = matcher(score_threshold=0.99, margin_threshold=0.99).explain("the query")
    assert isinstance(result, Rejection)
    assert result.reason == "below_score"


def test_an_escalate_winner_reports_escalate_class(matcher):
    result = matcher(score_threshold=0.0, margin_threshold=0.0).explain("near-escalate")
    assert isinstance(result, Rejection)
    assert result.reason == "escalate_class"
