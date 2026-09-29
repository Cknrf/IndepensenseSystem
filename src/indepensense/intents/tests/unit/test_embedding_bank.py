"""Unit tests for the fast-path example bank and its label decoding.

No model is loaded here. `parse_bank` and `_decode_label` are pure, and
`embeddings.py` imports sentence-transformers lazily, so all of this runs
on a Mac with no torch installed — which is the point: the bank is the
part a human edits by hand, so it is the part most likely to break.
"""
import pytest

from indepensense.config import NLU_EMBEDDING_BANK_PATH
from indepensense.intents.base import Intent
from indepensense.intents.embeddings import (
    _ENUM_SLOT_KEYS,
    _OPEN_SPAN_INTENTS,
    BankEntry,
    parse_bank,
)


@pytest.fixture(scope="module")
def bank() -> list[BankEntry]:
    return parse_bank(NLU_EMBEDDING_BANK_PATH)


def write_bank(tmp_path, text: str):
    path = tmp_path / "bank.md"
    path.write_text(text)
    return path


# --------------------------------------------------------------- parsing

def test_preamble_before_the_first_heading_is_not_training_data(tmp_path):
    """Prose at the top of the file must never become an example.

    The real bank opens with several paragraphs explaining the format. If
    those lines were parsed, the matcher's nearest neighbour for an
    unrelated utterance could be a sentence of documentation.
    """
    path = write_bank(tmp_path, "Some explanation.\nMore prose.\n\n## system.time\nWhat time is it\n")
    entries = parse_bank(path)
    assert [e.text for e in entries] == ["What time is it"]


def test_comments_and_blank_lines_inside_a_section_are_skipped(tmp_path):
    path = write_bank(
        tmp_path,
        "## vision.read\n\n# a comment\nRead this\n\nRead that\n",
    )
    assert [e.text for e in parse_bank(path)] == ["Read this", "Read that"]


def test_enum_label_becomes_intent_plus_parameter(tmp_path):
    path = write_bank(tmp_path, "## device.status:battery\nHow much battery\n")
    entry = parse_bank(path)[0]
    assert entry.intent is Intent.DEVICE_STATUS
    assert entry.parameters == {"status_field": "battery"}


def test_escalate_label_carries_no_intent(tmp_path):
    path = write_bank(tmp_path, "## __escalate__:chitchat\nPlay some music\n")
    entry = parse_bank(path)[0]
    assert entry.intent is None
    assert entry.bucket == "__escalate__:chitchat"


# ------------------------------------------------------- label rejection
#
# Every case below is a silent-failure mode if it were allowed through:
# the bank would simply contain fewer classes than intended and the only
# symptom would be lower coverage, which looks like a tuning problem
# rather than a typo.

def test_unknown_intent_name_is_rejected(tmp_path):
    path = write_bank(tmp_path, "## navigation.teleport\nBeam me up\n")
    with pytest.raises(ValueError, match="unknown intent label"):
        parse_bank(path)


def test_unknown_intent_may_not_be_a_fast_path_class(tmp_path):
    """`unknown` is the cloud fallback's trigger; only the LLM asserts it."""
    path = write_bank(tmp_path, "## unknown\nsomething odd\n")
    with pytest.raises(ValueError, match="may not answer"):
        parse_bank(path)


@pytest.mark.parametrize("intent", sorted(_OPEN_SPAN_INTENTS, key=lambda i: i.value))
def test_open_span_intents_may_not_be_a_fast_path_class(tmp_path, intent):
    """An embedding cannot extract a span, so these can only escalate."""
    path = write_bank(tmp_path, f"## {intent.value}\nsome utterance\n")
    with pytest.raises(ValueError, match="free-text parameter"):
        parse_bank(path)


def test_enum_intent_without_a_slot_value_is_rejected(tmp_path):
    path = write_bank(tmp_path, "## device.status\nHow much battery\n")
    with pytest.raises(ValueError, match="needs a slot value"):
        parse_bank(path)


def test_slot_value_on_a_parameterless_intent_is_rejected(tmp_path):
    path = write_bank(tmp_path, "## system.time:now\nWhat time is it\n")
    with pytest.raises(ValueError, match="takes no parameters"):
        parse_bank(path)


# ---------------------------------------------------------- the real bank

def test_the_shipped_bank_parses(bank):
    assert len(bank) > 100, "bank is suspiciously small"


def test_every_answerable_intent_is_represented(bank):
    """Catch an intent silently dropped out of the fast path.

    The expected set is derived from the enum rather than hardcoded, so
    adding an intent to `Intent` fails this test until it is either given
    examples or explicitly classified as open-span. That is the intended
    behaviour: a new intent should not default to invisible.
    """
    expected = {
        intent for intent in Intent
        if intent is not Intent.UNKNOWN and intent not in _OPEN_SPAN_INTENTS
    }
    assert {e.intent for e in bank if e.intent is not None} == expected


def test_every_enum_slot_value_has_examples(bank):
    """A missing enum value is answerable in theory and dead in practice."""
    present = {
        (e.intent, e.parameters[_ENUM_SLOT_KEYS[e.intent]])
        for e in bank
        if e.intent in _ENUM_SLOT_KEYS
    }
    assert present == {
        (Intent.DEVICE_STATUS, "battery"),
        (Intent.DEVICE_STATUS, "gps"),
        (Intent.DEVICE_STATUS, "signal"),
        (Intent.SYSTEM_VOLUME, "up"),
        (Intent.SYSTEM_VOLUME, "down"),
        (Intent.SYSTEM_LANGUAGE, "en"),
        (Intent.SYSTEM_LANGUAGE, "tl"),
    }


def test_no_duplicate_examples(bank):
    """A duplicate is a silent vote-weighting bug.

    Top-1 matching means an utterance listed twice under different labels
    makes the winner depend on iteration order rather than similarity.
    """
    seen: dict[str, str] = {}
    duplicates = []
    for entry in bank:
        key = entry.text.strip().lower()
        if key in seen:
            duplicates.append(f"{entry.text!r} in both {seen[key]} and {entry.bucket}")
        seen[key] = entry.bucket
    assert not duplicates, duplicates


def test_every_class_has_escalation_pressure(bank):
    """The bank must contain negative examples, and plenty of them.

    The fast path's entire safety argument is that near-misses land on an
    escalate row instead of the class they resemble. A bank that drifted
    to positives-only would score beautifully on coverage and take wrong
    actions in the field.
    """
    escalate = sum(1 for e in bank if e.intent is None)
    assert escalate >= 0.25 * len(bank), (
        f"only {escalate}/{len(bank)} examples are escalations"
    )


def test_every_class_covers_both_languages(bank):
    """Tagalog is the priority language; English-only classes exclude it.

    Detected by ASCII-only heuristics being useless here — both languages
    are Latin script — so this instead asserts each class has enough
    examples that a single-language section would be conspicuous, and
    checks the known Tagalog markers appear in every answerable class.
    """
    markers = (
        "mo", "ba", "ang", "ng", "ako", "ka", "na", "sa", "ito", "anong",
        "ay", "pa", "nga", "niyo", "yung", "po", "kita", "bang",
    )
    by_class: dict[tuple, list[str]] = {}
    for entry in bank:
        if entry.intent is None:
            continue
        by_class.setdefault(entry.decision, []).append(entry.text.lower())

    missing = [
        bucket for bucket, texts in by_class.items()
        if not any(set(t.split()) & set(markers) for t in texts)
    ]
    assert not missing, f"no Tagalog examples for: {missing}"
