"""Score the whole intent pipeline — embedding fast path, then the LLM —
against a file of labelled transcripts.

`llm_probe` and `embedding_probe` each measure one stage in isolation. The
wearable runs both, in order, and the user only ever experiences the
combination: a transcript the fast path answers wrongly never reaches the
LLM, and one the LLM gets wrong may be one the fast path would have taken.
This probe builds the parser exactly as `App._open_parser` does — the same
`TieredIntentParser`, `build_matcher` and `OllamaIntentParser`, with the
values from `config.py` — so it also sends Ollama exactly what the device
sends (`num_predict`, `keep_alive`, `think: false`), which `llm_probe` does
not.

Why case files instead of a Python list
---------------------------------------

Prompt work needs two sets that are never mixed up:

- `cases/dev.jsonl` — tune against this. Read its failures, change the
  prompt or the bank, re-run.
- `cases/heldout.jsonl` — do NOT read its failures while tuning. Run it
  only to report a result. A prompt tuned until the held-out set passes
  has memorised it, and the number stops meaning "works on sentences we
  did not write the prompt around".

`llm_probe`'s 110 cases are a third, older set. Several of them were later
copied into the system prompt's examples, so they now measure recall of
the prompt as much as generalisation — useful as a regression check, not
as the headline number.

One case per line:

    {"group": "taglish", "text": "pa-check naman ng battery",
     "intent": "device.status", "slots": {"status_field": "battery"}}

`slots` lists only what must be right; extra keys the model returns are
tolerated, and strings compare case-insensitively — the same rules as
`llm_probe`. Blank lines and lines starting with `//` are ignored.

Run from the repo root (works on a Mac; needs Ollama with `config.NLU_MODEL`
pulled, and downloads the embedding model on first use):

    python -m indepensense.intents.tests.manual.pipeline_probe            # dev set
    python -m indepensense.intents.tests.manual.pipeline_probe --heldout  # report only
    python -m indepensense.intents.tests.manual.pipeline_probe --check-overlap

    # try a candidate prompt or bank without touching the real one
    python -m indepensense.intents.tests.manual.pipeline_probe \\
        --prompt /tmp/nlu_system_v2.md --bank /tmp/nlu_examples_v2.md

    # 4B the way config.NLU_LARGE_MODEL would run it
    python -m indepensense.intents.tests.manual.pipeline_probe \\
        --model qwen3:4b --compact-prefill

    # one stage only
    python -m indepensense.intents.tests.manual.pipeline_probe --llm-only
    python -m indepensense.intents.tests.manual.pipeline_probe --no-llm

Accuracy on a Mac carries over to the Pi (same weights, temperature 0);
latency does not. Run Ollama with its default settings when measuring —
a quantised KV cache was seen to flip a case relative to the Pi.
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

from indepensense.config import (
    NLU_COMPACT_PREFILL,
    NLU_EMBEDDING_BANK_PATH,
    NLU_EMBEDDING_MARGIN_THRESHOLD,
    NLU_EMBEDDING_MODEL_DIR,
    NLU_EMBEDDING_SCORE_THRESHOLD,
    NLU_MODEL,
    NLU_PROMPT_PATH,
    NLU_TIMEOUT_S,
    NLU_WARMUP_TIMEOUT_S,
    OLLAMA_URL,
)

CASES_DIR = Path(__file__).parent / "cases"
DEV_PATH = CASES_DIR / "dev.jsonl"
HELDOUT_PATH = CASES_DIR / "heldout.jsonl"

# Intents where a wrong answer costs the user something real, reported on
# their own line so they cannot hide inside an overall percentage. A false
# emergency texts every guardian; a missed one is the failure this device
# exists to prevent; a false shutdown leaves a blind user with a dead cane.
SAFETY_INTENTS = {"emergency.trigger", "system.shutdown"}


def load_cases(path: Path) -> list[dict]:
    cases = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.exit(f"{path.name}:{number}: not valid JSON ({exc})")
        for key in ("group", "text", "intent"):
            if key not in case:
                sys.exit(f"{path.name}:{number}: missing {key!r}")
        case.setdefault("slots", {})
        case["line"] = number
        cases.append(case)
    return cases


def normalise(text: str) -> str:
    """Lower-case, punctuation-free form, for overlap checks only."""
    return re.sub(r"[^\w\s]", "", text.lower()).strip()


def known_utterances(bank_path: Path, prompt_path: Path) -> dict[str, str]:
    """Every utterance already written into the bank, the prompt or llm_probe.

    A case identical to one of these measures recall, not generalisation.
    """
    from indepensense.intents.embeddings import parse_bank
    from indepensense.intents.tests.manual import llm_probe

    known: dict[str, str] = {}
    for entry in parse_bank(bank_path):
        known[normalise(entry.text)] = "example bank"
    for quoted in re.findall(r'"([^"]+)"', prompt_path.read_text()):
        known.setdefault(normalise(quoted), "system prompt")
    for _group, text, _intent, _slots in llm_probe.TEST_CASES:
        known.setdefault(normalise(text), "llm_probe")
    return known


# Above this similarity a case is a near-copy of a bank row or prompt
# example: "Itigil mo" against "Itigil mo na", "What day is it" against
# "What day is it today". An exact-match check passes those, and they
# measure recall just as surely as a verbatim copy does.
NEAR_DUPLICATE_RATIO = 0.85


def check_overlap(paths: list[Path], bank_path: Path, prompt_path: Path) -> int:
    from difflib import SequenceMatcher

    known = known_utterances(bank_path, prompt_path)
    seen: dict[str, str] = {}
    problems = 0
    near: list[str] = []
    for path in paths:
        for case in load_cases(path):
            key = normalise(case["text"])
            if key in known:
                print(f"  {path.name}:{case['line']} {case['text']!r} is in the {known[key]}")
                problems += 1
            else:
                for other, where in known.items():
                    if SequenceMatcher(None, key, other).ratio() >= NEAR_DUPLICATE_RATIO:
                        near.append(f"  {path.name}:{case['line']} {case['text']!r} "
                                    f"~ {other!r} ({where})")
                        break
            if key in seen:
                print(f"  {path.name}:{case['line']} {case['text']!r} duplicates {seen[key]}")
                problems += 1
            seen[key] = f"{path.name}:{case['line']}"
    if not problems:
        print("  No exact overlap. Both case files are disjoint from the bank, "
              "the prompt, llm_probe and each other.")
    if near:
        # Warnings, not errors: short commands ("saan ako" / "nasaan ako")
        # and noisy variants of standard ones are bound to look alike. What
        # matters is a warning that APPEARS after a prompt or bank edit —
        # that edit copied a test case in.
        print(f"\n  {len(near)} near-copies (warnings; compare before and after an edit):")
        print("\n".join(near))
    return problems


def _fold(text: str) -> str:
    """Case- and article-insensitive form of a slot value.

    A leading "the" does not change which place the geocoder finds, and
    the executor passes the value through untouched, so "the clinic" and
    "clinic" are the same answer. Anything else — "klinika ko" versus
    "the clinic" — is a real difference and still fails.
    """
    text = text.strip().lower()
    return text[4:] if text.startswith("the ") else text


def slots_match(expected: dict, got: dict) -> bool:
    for key, want in expected.items():
        if key not in got:
            return False
        have = got[key]
        if isinstance(want, str) and isinstance(have, str):
            if _fold(want) != _fold(have):
                return False
        elif have != want:
            return False
    return True


def build_parser(args):
    from indepensense.intents.embeddings import build_matcher
    from indepensense.intents.parser import OllamaIntentParser
    from indepensense.intents.tiered import TieredIntentParser

    matcher = None
    if not args.llm_only:
        matcher = build_matcher(
            model_path=NLU_EMBEDDING_MODEL_DIR,
            bank_path=Path(args.bank),
            score_threshold=args.score,
            margin_threshold=args.margin,
        )
        if matcher is None:
            sys.exit("The embedding matcher could not be built — see the error above.")

    if args.no_llm:
        return matcher, None

    llm = OllamaIntentParser(
        model=args.model,
        ollama_url=OLLAMA_URL,
        prompt_path=Path(args.prompt),
        timeout_s=NLU_TIMEOUT_S,
        warmup=True,
        warmup_timeout_s=NLU_WARMUP_TIMEOUT_S,
        compact_prefill=args.compact_prefill,
    )
    return matcher, TieredIntentParser(matcher=matcher, llm=llm)


def run(cases: list[dict], matcher, parser, show_correct: bool) -> list[dict]:
    results = []
    for case in cases:
        start = time.perf_counter()
        if parser is not None:
            result = parser.parse(case["text"])
            intent = result.intent.value
            params = dict(result.parameters)
            source = result.source
            failure = result.failure
        else:
            match = matcher.match(case["text"])
            if match is None:
                intent, params, source, failure = None, {}, "escalated", None
            else:
                intent, params = match.intent.value, dict(match.parameters)
                source, failure = "embedding", None
        elapsed = time.perf_counter() - start

        if intent is None:      # --no-llm and the fast path declined
            ok = None
        else:
            ok = intent == case["intent"] and slots_match(case["slots"], params)
        row = {**case, "got_intent": intent, "got_slots": params,
               "source": source, "failure": failure, "ok": ok, "seconds": elapsed}
        results.append(row)

        if ok is False or (show_correct and ok):
            mark = "ok " if ok else "BAD"
            print(f"  {mark} [{case['group']}/{source}] {case['text']!r}")
            if not ok:
                print(f"        expected {case['intent']} {case['slots'] or ''}")
                print(f"        got      {intent} {params or ''}"
                      + (f"  (failure={failure})" if failure else ""))
    return results


def report(results: list[dict]) -> None:
    by_group = defaultdict(list)
    for row in results:
        by_group[row["group"]].append(row)

    print(f"\n  {'group':<14}{'cases':>6}{'correct':>9}{'accuracy':>10}"
          f"{'fast path':>11}{'fast wrong':>12}")
    print("  " + "-" * 62)
    for group in sorted(by_group) + ["OVERALL"]:
        rows = results if group == "OVERALL" else by_group[group]
        scored = [r for r in rows if r["ok"] is not None]
        correct = sum(1 for r in scored if r["ok"])
        fast = [r for r in rows if r["source"] == "embedding"]
        fast_wrong = sum(1 for r in fast if not r["ok"])
        accuracy = f"{100 * correct / len(scored):.1f}%" if scored else "-"
        if group == "OVERALL":
            print("  " + "-" * 62)
        print(f"  {group:<14}{len(rows):>6}{correct:>9}{accuracy:>10}"
              f"{len(fast):>11}{fast_wrong:>12}")

    safety = [r for r in results
              if r["intent"] in SAFETY_INTENTS or r["got_intent"] in SAFETY_INTENTS]
    false_pos = [r for r in safety
                 if r["got_intent"] in SAFETY_INTENTS and r["got_intent"] != r["intent"]]
    missed = [r for r in safety
              if r["intent"] in SAFETY_INTENTS and r["got_intent"] != r["intent"]]
    print(f"\n  safety intents: {len(false_pos)} false trigger(s), "
          f"{len(missed)} missed — {', '.join(sorted(SAFETY_INTENTS))}")
    for row in false_pos + missed:
        print(f"    {row['text']!r}: expected {row['intent']}, got {row['got_intent']}")

    failures = [r for r in results if r["failure"]]
    if failures:
        print(f"\n  {len(failures)} transport/malformed failure(s) — not a prompt "
              f"problem; check Ollama.")

    llm_times = [r["seconds"] for r in results if r["source"] == "llm"]
    if llm_times:
        print(f"\n  mean LLM latency {sum(llm_times) / len(llm_times):.2f}s on this "
              f"host — not representative of the Pi.")


def main():
    ap = argparse.ArgumentParser(
        description="Score the embedding + LLM pipeline against labelled transcripts.",
    )
    ap.add_argument("cases", nargs="?", help="a .jsonl case file (default: dev set)")
    ap.add_argument("--heldout", action="store_true", help="score the held-out set")
    ap.add_argument("--prompt", default=str(NLU_PROMPT_PATH))
    ap.add_argument("--bank", default=str(NLU_EMBEDDING_BANK_PATH))
    ap.add_argument("--model", default=NLU_MODEL)
    ap.add_argument(
        "--compact-prefill", action=argparse.BooleanOptionalAction,
        default=NLU_COMPACT_PREFILL,
        help="request style; defaults to what config.NLU_LARGE_MODEL selects",
    )
    ap.add_argument("--score", type=float, default=NLU_EMBEDDING_SCORE_THRESHOLD)
    ap.add_argument("--margin", type=float, default=NLU_EMBEDDING_MARGIN_THRESHOLD)
    ap.add_argument("--llm-only", action="store_true", help="skip the fast path")
    ap.add_argument("--no-llm", action="store_true",
                    help="fast path only; escalations are reported, not scored")
    ap.add_argument("--group", help="only cases in this group")
    ap.add_argument("--show-correct", action="store_true")
    ap.add_argument("--json", metavar="PATH", help="also write every result here")
    ap.add_argument("--check-overlap", action="store_true",
                    help="check both case files against the bank, prompt and llm_probe")
    args = ap.parse_args()

    if args.check_overlap:
        sys.exit(1 if check_overlap([DEV_PATH, HELDOUT_PATH],
                                    Path(args.bank), Path(args.prompt)) else 0)

    path = Path(args.cases) if args.cases else (HELDOUT_PATH if args.heldout else DEV_PATH)
    cases = load_cases(path)
    if args.group:
        cases = [c for c in cases if c["group"] == args.group]

    print(f"\nCases:  {path} ({len(cases)})")
    print(f"Prompt: {args.prompt}")
    print(f"Bank:   {args.bank}" + ("  (fast path skipped)" if args.llm_only else ""))
    style = "compact-JSON prefill" if args.compact_prefill else "JSON mode"
    print(f"Model:  {args.model} ({style})" + ("  (LLM skipped)" if args.no_llm else ""))
    print()

    matcher, parser = build_parser(args)
    results = run(cases, matcher, parser, args.show_correct)
    report(results)

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=1, ensure_ascii=False))
        print(f"\n  wrote {args.json}")


if __name__ == "__main__":
    main()
