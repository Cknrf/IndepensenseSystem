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
import sys
import types

import numpy as np
import pytest

from indepensense.intents.base import Intent
from indepensense.intents.embeddings import (
    EmbeddingMatcher,
    Match,
    Rejection,
    build_matcher,
)


class _StubEncoder:
    """Returns a fixed vector per text, so distances are chosen by hand.

    Unknown texts encode to a unit vector pointing nowhere near the bank,
    which makes "nothing matched" expressible without inventing a number.
    """

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors
        self.calls: list[tuple[list[str], bool]] = []

    def encode(self, texts, normalize_embeddings=True, show_progress_bar=False):
        self.calls.append((list(texts), normalize_embeddings))
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
def custom_matcher(tmp_path, monkeypatch):
    """A matcher over any bank and vectors, with the encoder stubbed out."""

    def _build(bank_text, vectors, score_threshold=0.86, margin_threshold=0.02):
        bank = tmp_path / "bank.md"
        bank.write_text(bank_text)
        monkeypatch.setattr(
            EmbeddingMatcher, "_load_model",
            staticmethod(lambda _name: _StubEncoder(vectors)),
        )
        return EmbeddingMatcher(
            model_path=tmp_path / "stub",
            bank_path=bank,
            score_threshold=score_threshold,
            margin_threshold=margin_threshold,
        )

    return _build


@pytest.fixture
def matcher(custom_matcher):
    """A matcher over `_BANK`."""

    def _build(score_threshold=0.86, margin_threshold=0.02):
        return custom_matcher(_BANK, _VECTORS, score_threshold, margin_threshold)

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


def test_score_threshold_is_inclusive(matcher):
    """A score exactly on the threshold answers. Pinned because the gate is
    a bare `<`, and flipping it to `<=` would silently move every tuned
    threshold by one ulp's worth of cases."""
    score = matcher(score_threshold=0.0, margin_threshold=0.0).explain("the query").score
    result = matcher(score_threshold=score, margin_threshold=0.0).explain("the query")
    assert isinstance(result, Match)


def test_margin_threshold_is_inclusive(matcher):
    margin = matcher(score_threshold=0.0, margin_threshold=0.0).explain("the query").margin
    result = matcher(score_threshold=0.0, margin_threshold=margin).explain("the query")
    assert isinstance(result, Match)


def test_two_escalate_buckets_do_not_contest_each_other(custom_matcher):
    """Different escalate buckets are one decision: the LLM gets it either
    way. If the margin were keyed on the raw bucket, a transcript squarely
    among the negatives would report as a near-tie — `contested` instead
    of `escalate_class` — and send the probe reader after the wrong fix."""
    bank = """
## system.time
far-time

## __escalate__:destinations
near-destination

## __escalate__:chitchat
near-chitchat
"""
    vectors = {
        "the query": _unit(0),
        "near-destination": _unit(10),   # cos ~0.985
        "near-chitchat": _unit(11),      # cos ~0.982, a different bucket
        "far-time": _unit(40),           # cos ~0.766
    }
    result = custom_matcher(bank, vectors, margin_threshold=0.05).explain("the query")
    assert isinstance(result, Rejection)
    assert result.reason == "escalate_class"
    assert result.margin == pytest.approx(math.cos(math.radians(10)) - math.cos(math.radians(40)), abs=1e-3)


def test_different_slot_values_of_one_intent_do_contest(custom_matcher):
    """`device.status:battery` and `device.status:gps` share an intent but
    take different actions, so a near-tie between them must escalate."""
    bank = """
## device.status:battery
near-battery

## device.status:gps
near-gps
"""
    vectors = {
        "the query": _unit(0),
        "near-battery": _unit(10),
        "near-gps": _unit(11),
    }
    result = custom_matcher(bank, vectors).explain("the query")
    assert isinstance(result, Rejection)
    assert result.reason == "contested"


def test_a_single_class_bank_reports_the_score_as_its_margin(custom_matcher):
    """Documented in `Match`: with no other class to compare against, the
    margin falls back to the score rather than to zero or an exception."""
    bank = "## system.time\nnear-time\nmid-time\n"
    vectors = {"the query": _unit(0), "near-time": _unit(16), "mid-time": _unit(20)}
    result = custom_matcher(bank, vectors).explain("the query")
    assert isinstance(result, Match)
    assert result.margin == result.score


# --- match() -----------------------------------------------------------------

def test_match_returns_the_hit_with_its_details(matcher):
    result = matcher().match("the query")
    assert result == Match(
        intent=Intent.SYSTEM_TIME,
        parameters={},
        score=pytest.approx(math.cos(math.radians(16)), abs=1e-3),
        margin=pytest.approx(0.961 - 0.914, abs=1e-3),
        matched_example="near-time",
    )


@pytest.mark.parametrize(
    "query, thresholds",
    [
        ("the query", {"score_threshold": 0.99}),                          # below_score
        ("the query", {"margin_threshold": 0.05}),                         # contested
        ("near-escalate", {"score_threshold": 0.0, "margin_threshold": 0.0}),  # escalate_class
    ],
    ids=["below_score", "contested", "escalate_class"],
)
def test_match_collapses_every_rejection_to_none(matcher, query, thresholds):
    """`None` is the only escalation signal `TieredIntentParser` reads, so
    each of the three routes must produce it — a `Rejection` leaking out
    would be truthy and read as a hit."""
    assert matcher(**thresholds).match(query) is None


def test_match_carries_the_enum_slot_in_executor_shape(custom_matcher):
    bank = "## device.status:battery\nnear-battery\n"
    vectors = {"the query": _unit(0), "near-battery": _unit(10)}
    result = custom_matcher(bank, vectors).match("the query")
    assert result.intent is Intent.DEVICE_STATUS
    assert result.parameters == {"status_field": "battery"}


def test_mutating_a_matchs_parameters_does_not_corrupt_the_bank(custom_matcher):
    """The executor owns the dict it is handed. If `Match` aliased the bank
    entry's parameters, one handler editing them would change what every
    later utterance in that class resolves to, for the rest of the boot."""
    bank = "## device.status:battery\nnear-battery\n"
    vectors = {"the query": _unit(0), "near-battery": _unit(10)}
    instance = custom_matcher(bank, vectors)
    instance.match("the query").parameters["status_field"] = "gps"
    assert instance.match("the query").parameters == {"status_field": "battery"}


# --- encoding contract -------------------------------------------------------

def test_bank_and_transcript_are_encoded_with_the_e5_prefix_and_normalised(custom_matcher):
    """The e5 model card requires `"query: "` on both sides, and the dot
    product is only a cosine if both sides are unit length. The stub strips
    the prefix to keep fixtures readable, so without this test it could be
    dropped from the matcher and every other test would still pass."""
    bank = "## system.time\nnear-time\n"
    instance = custom_matcher(bank, {"the query": _unit(0), "near-time": _unit(10)})
    instance.match("the query")
    calls = instance._model.calls
    assert calls == [(["query: near-time"], True), (["query: the query"], True)]


def test_the_bank_is_encoded_once_at_construction(custom_matcher):
    """Encoding the bank per utterance would put the cost this class exists
    to remove back on the voice thread."""
    bank = "## system.time\nnear-time\nmid-time\n"
    instance = custom_matcher(bank, {"near-time": _unit(10), "mid-time": _unit(20)})
    for _ in range(3):
        instance.match("the query")
    assert [texts for texts, _ in instance._model.calls].count(
        ["query: near-time", "query: mid-time"]
    ) == 1


def test_neighbours_with_k_beyond_the_bank_returns_the_whole_bank(matcher):
    assert len(matcher().neighbours("the query", k=100)) == len(_VECTORS) - 1


# --- construction and degradation --------------------------------------------

def test_a_bank_with_headings_but_no_rows_is_rejected(custom_matcher):
    with pytest.raises(ValueError, match="is empty"):
        custom_matcher("## system.time\n\n# only a comment\n", {})


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Stand in for the real package so `_load_model` runs without torch
    and records what it was asked to load."""
    loaded: list[str] = []
    module = types.ModuleType("sentence_transformers")
    module.SentenceTransformer = lambda path: loaded.append(path) or object()
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return loaded


def test_load_model_refuses_a_missing_directory_and_names_the_fetch_tool(
    tmp_path, fake_sentence_transformers,
):
    """A missing model must fail with the fix in the message, never fall
    back to resolving a Hub repo id — see CLAUDE.md, decision 3."""
    with pytest.raises(FileNotFoundError, match="indepensense.tools.fetch_models"):
        EmbeddingMatcher._load_model(tmp_path / "absent")
    assert fake_sentence_transformers == []


def test_load_model_passes_the_local_directory_as_a_path(tmp_path, fake_sentence_transformers):
    model_dir = tmp_path / "e5"
    model_dir.mkdir()
    EmbeddingMatcher._load_model(model_dir)
    assert fake_sentence_transformers == [str(model_dir)]


def test_build_matcher_degrades_to_none_when_the_model_is_missing(
    tmp_path, capsys, fake_sentence_transformers,
):
    """The fast path is an optimisation; losing it must leave a working
    device that sends everything to the LLM, and say so on stderr."""
    bank = tmp_path / "bank.md"
    bank.write_text(_BANK)
    result = build_matcher(tmp_path / "absent", bank, 0.86, 0.02)
    assert result is None
    assert "fast path unavailable" in capsys.readouterr().err


def test_build_matcher_degrades_to_none_on_a_malformed_bank(tmp_path, capsys):
    bank = tmp_path / "bank.md"
    bank.write_text("## navigation.teleport\nBeam me up\n")
    assert build_matcher(tmp_path / "stub", bank, 0.86, 0.02) is None
    assert "unknown intent label" in capsys.readouterr().err


def test_build_matcher_returns_a_working_matcher(tmp_path, monkeypatch):
    bank = tmp_path / "bank.md"
    bank.write_text(_BANK)
    monkeypatch.setattr(
        EmbeddingMatcher, "_load_model",
        staticmethod(lambda _name: _StubEncoder(_VECTORS)),
    )
    result = build_matcher(tmp_path / "stub", bank, 0.86, 0.02)
    assert result.match("the query").intent is Intent.SYSTEM_TIME
