"""Empirical probe: does a semantic fast path in front of the LLM pay?

Answers one question with numbers rather than argument: for a given
embedding model and a given pair of thresholds, **what fraction of
utterances can skip the LLM, and how often is the fast path wrong when
it fires?**

Coverage and precision are reported separately, and that separation is
the whole point. A single accuracy figure would hide the only failure
mode that matters: a fast path at 90% precision and 90% coverage is not
a faster device, it is a device that takes the wrong action one time in
ten. Coverage buys latency; precision is what it costs. The decision is
whether the exchange rate is acceptable, and that needs both numbers.

Both are reported per language group for the same reason `llm_probe`
does it — Tagalog is the priority language, and a blended figure lets a
model that aces English carry a model that fails Tagalog.

Test data
---------

The held-out cases are imported from `llm_probe`, so there is exactly
one labelled test set in the repo and it cannot drift from the one the
LLM is scored against. The example bank in `prompts/nlu_examples.md` is
written to be disjoint from it; `--check-overlap` verifies that, because
an accidental copy-paste would turn a generalisation score into a
memorisation score without changing anything visible in the output.

Cases whose expected intent has an open-text slot (`navigation.start`,
`place.save`, `place.delete`) are counted as *correct escalations* when
the fast path declines them. They are not failures — declining them is
the design.

Run from repo root (works on a Mac; needs no Pi hardware):

    python -m indepensense.intents.tests.manual.embedding_probe

    # sweep thresholds to pick the operating point
    python -m indepensense.intents.tests.manual.embedding_probe --sweep

    # compare a different encoder
    python -m indepensense.intents.tests.manual.embedding_probe \
        --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

Requires `pip install sentence-transformers` (pulls torch). On the Pi
that is already satisfied by `requirements-pi.txt`.
"""
import argparse
import time

from indepensense.config import (
    NLU_EMBEDDING_BANK_PATH,
    NLU_EMBEDDING_MARGIN_THRESHOLD,
    NLU_EMBEDDING_MODEL,
    NLU_EMBEDDING_SCORE_THRESHOLD,
)
from indepensense.intents.embeddings import (
    EmbeddingMatcher,
    Match,
    parse_bank,
)
from indepensense.intents.tests.manual.llm_probe import GROUPS, TEST_CASES

# Intents the matcher is designed never to answer. A case expecting one
# of these is scored as a correct escalation, not a miss. `unknown` is
# here for the reason given in `embeddings.py`: it is the cloud
# fallback's trigger and only the LLM may assert it.
ESCALATE_EXPECTED = {
    "navigation.start",
    "place.save",
    "place.delete",
    "unknown",
}

# Threshold grids for `--sweep`. Deliberately coarse: the goal is to find
# the knee of the coverage/precision curve, and a fine grid over 98 cases
# would be fitting noise.
#
# The score grid starts high and the margin grid is the fine one, because
# the first sweep showed score is nearly inert for e5: its cosine values
# are compressed into a narrow high band, so almost every transcript
# clears any absolute bar below ~0.88 and the threshold does no filtering.
# Margin does essentially all of the work. Keep a few low score points
# anyway — a different encoder will have a different distribution, and
# the flat region is itself the evidence for that claim.
SCORE_GRID = (0.80, 0.86, 0.88, 0.90, 0.92, 0.94)
MARGIN_GRID = (0.00, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06)


def expected_is_answerable(intent_name: str, slots: dict) -> bool:
    """Could the fast path legitimately answer this case at all?"""
    if intent_name in ESCALATE_EXPECTED:
        return False
    # A numeric volume level is an open slot even though the intent has a
    # closed-enum form for direction.
    if intent_name == "system.volume" and "level" in slots:
        return False
    # Only the two supported languages are in the label space; any other
    # named language must reach the LLM to be rejected by name.
    if intent_name == "system.language" and slots.get("language") not in ("en", "tl"):
        return False
    return True


def evaluate(matcher: EmbeddingMatcher, score_t: float, margin_t: float) -> dict:
    """Score every held-out case at one threshold pair.

    Thresholds are applied here rather than rebuilding the matcher, so a
    sweep encodes the bank and the test set once instead of once per
    grid point. That is the difference between seconds and minutes on a
    Pi, and it changes nothing about the result — the thresholds are
    pure post-processing on scores the model already produced.
    """
    matcher._score_threshold = score_t      # noqa: SLF001 - see docstring
    matcher._margin_threshold = margin_t

    stats = {
        g: {
            "fired": 0, "correct": 0, "escalated": 0,
            "missed": 0, "answerable": 0, "total": 0,
        }
        for g in GROUPS
    }
    mistakes = []

    for group, text, expected_intent, expected_slots in TEST_CASES:
        bucket = stats[group]
        bucket["total"] += 1
        answerable = expected_is_answerable(expected_intent, expected_slots)
        bucket["answerable"] += answerable
        result = matcher.explain(text)

        if isinstance(result, Match):
            bucket["fired"] += 1
            got_intent = result.intent.value
            got_slots = result.parameters
            ok = answerable and got_intent == expected_intent and _slots_match(
                expected_slots, got_slots
            )
            if ok:
                bucket["correct"] += 1
            else:
                mistakes.append(
                    (group, text, expected_intent, expected_slots, got_intent, got_slots, result)
                )
        else:
            bucket["escalated"] += 1
            if answerable:
                # Not an error — the LLM still answers it correctly. It is
                # lost latency, which is what `capture` measures.
                bucket["missed"] += 1

    return {"stats": stats, "mistakes": mistakes}


def _slots_match(expected: dict, got: dict) -> bool:
    """Required-slot equality, matching `llm_probe`'s checker.

    Only the slots the case declares are compared, case-insensitively for
    strings. Extra keys are tolerated for the same reason they are there.
    """
    for key, want in expected.items():
        have = got.get(key)
        if isinstance(want, str) and isinstance(have, str):
            if want.lower() != have.lower():
                return False
        elif want != have:
            return False
    return True


def report(result: dict, score_t: float, margin_t: float) -> None:
    print()
    print(f"  thresholds: score >= {score_t:.2f}, margin >= {margin_t:.2f}")
    print()
    print(
        f"  {'group':12s} {'cases':>6s} {'answerable':>11s} {'fired':>6s} "
        f"{'coverage':>9s} {'capture':>8s} {'precision':>10s}"
    )
    print("  " + "-" * 68)

    totals = {"fired": 0, "correct": 0, "total": 0, "answerable": 0}
    for group in GROUPS:
        s = result["stats"][group]
        for key in totals:
            totals[key] += s[key]
        print(
            f"  {group:12s} {s['total']:6d} {s['answerable']:11d} {s['fired']:6d} "
            f"{_pct(s['fired'], s['total']):>9s} "
            f"{_pct(s['fired'], s['answerable']):>8s} "
            f"{_pct(s['correct'], s['fired']):>10s}"
        )

    print("  " + "-" * 68)
    print(
        f"  {'OVERALL':12s} {totals['total']:6d} {totals['answerable']:11d} "
        f"{totals['fired']:6d} {_pct(totals['fired'], totals['total']):>9s} "
        f"{_pct(totals['fired'], totals['answerable']):>8s} "
        f"{_pct(totals['correct'], totals['fired']):>10s}"
    )

    wrong = totals["fired"] - totals["correct"]
    print()
    print("  coverage  = fired / all cases. What fraction of everything skips the LLM.")
    print("  answerable= cases whose intent the fast path is even allowed to answer;")
    print("              the rest have an open text slot, so escalating them is correct")
    print("              and coverage can never reach 100% by design.")
    print("  capture   = fired / answerable. How much of the reachable work it takes.")
    print("              This is the number to improve with more example phrasings.")
    print("  precision = correct / fired. The safety number. Must not drop below the")
    print("              LLM's own accuracy, or the fast path is a regression.")
    print()
    print(f"  {wrong} wrong answer(s) on the fast path — these are the ones that cost")
    print(f"  the user a wrong action. {totals['total'] - totals['fired']} case(s) fell through to the LLM,")
    print(f"  of which {sum(s['missed'] for s in result['stats'].values())} could have been answered here (lost latency, not lost correctness).")

    if result["mistakes"]:
        print()
        print("  MISTAKES")
        for group, text, exp_i, exp_s, got_i, got_s, m in result["mistakes"]:
            print(f"    [{group:11s}] {text!r}")
            print(f"        expected {exp_i} {exp_s}")
            print(f"        got      {got_i} {got_s}")
            print(
                f"        score {m.score:.3f}  margin {m.margin:.3f}  "
                f"nearest {m.matched_example!r}"
            )


def sweep(matcher: EmbeddingMatcher) -> None:
    """Coverage/precision across the threshold grid.

    Read this table by fixing a precision floor first — the fast path
    must not be less reliable than the LLM it bypasses — then taking the
    highest coverage that clears it. Picking the maximum of any single
    column is how a fast path ends up fast and wrong.
    """
    print()
    print(f"  {'score':>6s} {'margin':>7s} {'coverage':>9s} {'precision':>10s} {'wrong':>6s}")
    print("  " + "-" * 44)
    for score_t in SCORE_GRID:
        for margin_t in MARGIN_GRID:
            r = evaluate(matcher, score_t, margin_t)
            fired = sum(s["fired"] for s in r["stats"].values())
            correct = sum(s["correct"] for s in r["stats"].values())
            total = sum(s["total"] for s in r["stats"].values())
            print(
                f"  {score_t:6.2f} {margin_t:7.2f} {_pct(fired, total):>9s} "
                f"{_pct(correct, fired):>10s} {fired - correct:6d}"
            )
        print()


def check_overlap(bank_path) -> int:
    """Report any utterance present in both the bank and the test set."""
    bank = {e.text.strip().lower() for e in parse_bank(bank_path)}
    clashes = [t for _, t, _, _ in TEST_CASES if t.strip().lower() in bank]
    if clashes:
        print(f"  {len(clashes)} test case(s) also appear in the example bank:")
        for text in clashes:
            print(f"    {text!r}")
        print("  Remove them from the bank — accuracy here would be memorisation.")
    else:
        print("  No overlap. The test set is held out.")
    return len(clashes)


def _pct(part: int, whole: int) -> str:
    return "n/a" if not whole else f"{100 * part / whole:.1f}%"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=NLU_EMBEDDING_MODEL)
    ap.add_argument("--bank", default=NLU_EMBEDDING_BANK_PATH, type=str)
    ap.add_argument("--score", type=float, default=NLU_EMBEDDING_SCORE_THRESHOLD)
    ap.add_argument("--margin", type=float, default=NLU_EMBEDDING_MARGIN_THRESHOLD)
    ap.add_argument("--sweep", action="store_true", help="grid over both thresholds")
    ap.add_argument("--check-overlap", action="store_true", help="bank vs test set only")
    args = ap.parse_args()

    from pathlib import Path
    bank_path = Path(args.bank)

    print(f"\nExample bank: {bank_path}")
    if args.check_overlap:
        raise SystemExit(1 if check_overlap(bank_path) else 0)

    entries = parse_bank(bank_path)
    answerable = {e.decision for e in entries if e.intent is not None}
    print(f"  {len(entries)} examples across {len(answerable)} answerable classes")
    print(f"  {sum(1 for e in entries if e.intent is None)} escalate examples")
    check_overlap(bank_path)

    print(f"\nModel: {args.model}")
    t0 = time.time()
    matcher = EmbeddingMatcher(
        model_name=args.model,
        bank_path=bank_path,
        score_threshold=args.score,
        margin_threshold=args.margin,
    )
    print(f"  Loaded and encoded the bank in {time.time() - t0:.1f}s.")

    # Per-query latency on a warm model — the number the whole design is
    # trying to buy. Measured after a throwaway call so the first-call
    # graph build does not land in the average.
    matcher.match("warmup")
    t0 = time.time()
    for _, text, _, _ in TEST_CASES:
        matcher.match(text)
    per_query_ms = 1000 * (time.time() - t0) / len(TEST_CASES)
    print(f"  Mean match latency: {per_query_ms:.1f} ms/query over {len(TEST_CASES)} cases.")

    if args.sweep:
        sweep(matcher)
    else:
        report(evaluate(matcher, args.score, args.margin), args.score, args.margin)
    print()


if __name__ == "__main__":
    main()
