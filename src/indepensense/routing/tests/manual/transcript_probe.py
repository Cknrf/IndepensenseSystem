"""Empirical probe: does a destination survive being misheard?

The NLU never knows what places exist, and that is deliberate — it
extracts the destination *span* and copies it through verbatim
(`prompts/nlu_system.md`, rule 3: "Never translate, tidy, or reword a
location"). A 1.7B model inventing a correction to a Batangas street
name would be unverifiable and inconsistent, so spelling knowledge lives
where the ground truth is: Photon's index.

That pushes the whole question downstream. Whisper hands over its best
guess at a proper noun, and the chain that has to absorb the error is
`geocode -> rank_candidates -> confirm`. This probe measures how much of
it survives.

Two numbers, never one
----------------------

**Retrieval** — is the right place anywhere in Photon's candidate list?
**Ranking** — did `rank_candidates` put it first?

They fail for different reasons and have different fixes, so a blended
"accuracy" would hide which one to work on. The same separation
`embedding_probe` makes between coverage and precision, and for the same
reason.

Every variant lands in exactly one of four outcomes, and each one names
its own fix:

    ok          rank 1 after ranking — the user is walked to the right door
    misranked   in the candidate window, but not first. Ranking's problem.
                `name_match_score` is an exact token-set intersection, so
                one misheard token scores 0.00, every candidate ties, and
                the sort collapses to pure distance. The report prints
                that score for each miss — a column of 0.00 is the case
                for fuzzy token scoring, and anything else is the case
                against it.
    window      absent from the first `GEOCODE_CANDIDATE_LIMIT`
                candidates but present in a wider list. The limit is the
                constraint, not the ranking — the executor never sees it.
    absent      not there at either limit. Photon's own fuzziness did not
                stretch that far; no local change reaches this, only the
                query or the index.

Ground truth
------------

A case names a place by its canonical spelling, and the probe geocodes
*that* to establish where the right answer is. Truth is therefore "where
the correct spelling lands", which is exactly the baseline a misheard
variant should be compared against — and it costs no hand-entered
coordinates, which is what would have kept the corpus small.

The canonical spelling is also scored, as the **control**. The gap
between the control row and the misheard rows is the measurement; the
control row on its own says whether the index has the place at all.

Resolved truth is printed for every case so it can be eyeballed once. If
one lands somewhere wrong, pin it with an explicit `"truth": "lat,lon"`
in the case rather than letting a bad baseline score everything beneath
it. A case whose control cannot be resolved is reported as **unusable**
and left out of the totals — an unscored case is honest, a case scored
against nothing is not.

Matching is by distance, not by name: a place is "found" when a
candidate falls within `--radius` of truth. Scoring a spelling probe by
string comparison would be circular, and OSM routinely carries the same
place as a node and a building a few tens of metres apart.

For `category` cases truth is the *nearest* instance, so a miss there
means "walked to a farther hospital", not "walked somewhere that is not
a hospital". Read that group accordingly — it is a control tier, and
ranking ignores the name entirely when `nearest` is true.

The corpus is seeded by hand
----------------------------

`cases/destinations.jsonl` ships with plausible mishearings, only one of
which is observed fact. Real transcripts are the right input and the
file is built to take them — see the header comment there. Until it has
them, this probe measures what the chain does to *invented* errors, and
the report says so on every run rather than letting a number travel
without its caveat.

Usage
-----

Run from the repo root. Needs Photon (`systemctl status photon`), no
other service and no hardware — origins come from the case file, so this
is reproducible from a desk.

    python -m indepensense.routing.tests.manual.transcript_probe

    # one tier at a time while working on it
    python -m indepensense.routing.tests.manual.transcript_probe --only street

    # is the candidate limit the constraint?
    python -m indepensense.routing.tests.manual.transcript_probe --wide 100

    # against a Pi over the network, from a Mac
    python -m indepensense.routing.tests.manual.transcript_probe \\
        --url http://100.113.232.110:2322

To diagnose a *single* transcript rather than score a corpus, use
`geocode_probe` — it prints every candidate with its distance and match
score, which is the detail this probe aggregates away.
"""
import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from indepensense.config import GEOCODE_CANDIDATE_LIMIT, PHOTON_URL
from indepensense.routing.base import Coordinate, GeocodingResult, haversine_m
from indepensense.routing.ranking import name_match_score, rank_candidates

CASES_PATH = Path(__file__).parent / "cases" / "destinations.jsonl"

# Tiers, ordered by how much of the name Whisper's vocabulary already
# contains — which is the axis that decides how badly a transcript can
# degrade. A decoder has no character-level fallback: a word it does not
# know is emitted as whatever in-vocabulary tokens best fit the audio,
# so "Bulacnin" arrives as "Bull Acnin" rather than as a near-miss
# spelling. Chains and common nouns sit at one end of that, Tagalog
# toponyms at the other, and a blended score would average the two.
GROUPS = ("chain", "local", "street", "barangay", "category")

# How close a candidate must be to count as the same place. OSM carries
# the same POI as a node and as a building outline, and a mall's node can
# sit a good distance from the entrance the geocoder returns, so an exact
# coordinate test would report correct answers as misses.
_DEFAULT_RADIUS_M = 75.0

OUTCOMES = ("ok", "misranked", "window", "absent")


@dataclass
class Probe:
    """One transcript put through geocode + rank, and what became of it."""
    group: str
    place: str
    heard: str
    is_control: bool
    outcome: str
    rank: int | None = None          # 1-based, where the true place landed
    chosen: str = ""                 # what the wearable would route to
    truth_score: float = 0.0         # name_match_score(heard, true place)
    chosen_score: float = 0.0        # name_match_score(heard, chosen)
    error_m: float = 0.0             # how far the wrong choice is from truth


def load_cases(path: Path) -> list[dict]:
    """Read the JSONL corpus. Blank lines and `//` comments are skipped.

    Same conventions as the intents case files, so there is one format to
    learn rather than two.
    """
    cases = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            sys.exit(f"{path.name}:{number}: not valid JSON ({exc})")
        for key in ("group", "place", "origin"):
            if key not in case:
                sys.exit(f"{path.name}:{number}: missing {key!r}")
        if case["group"] not in GROUPS:
            sys.exit(f"{path.name}:{number}: unknown group {case['group']!r} "
                     f"(expected one of {', '.join(GROUPS)})")
        case.setdefault("heard", [])
        case.setdefault("nearest", False)

        # The canonical spelling is scored automatically as the control,
        # so a copy of it inside `heard` is counted twice — once as the
        # ceiling and once as the cost of missing that ceiling, which
        # moves the headline number in the flattering direction. Loudly,
        # because it is invisible in a percentage and was in this file
        # three times on the day it was written.
        seen = {case["place"]}
        for heard in case["heard"]:
            if heard in seen:
                sys.exit(f"{path.name}:{number}: {heard!r} is listed twice "
                         f"(the canonical spelling is already scored as the "
                         f"control — `heard` holds misheard forms only)")
            seen.add(heard)

        case["line"] = number
        cases.append(case)
    return cases


def parse_coordinate(text: str) -> Coordinate:
    """`"13.937387,121.118698"` -> Coordinate. Raises with the bad input named."""
    try:
        lat_text, _, lon_text = text.partition(",")
        return Coordinate(lat=float(lat_text), lon=float(lon_text))
    except ValueError:
        raise ValueError(f"expected lat,lon — got {text!r}") from None


def find_within(
    hits: list[GeocodingResult], truth: Coordinate, radius_m: float,
) -> int | None:
    """Index of the first candidate within `radius_m` of truth, or None."""
    for index, hit in enumerate(hits):
        if haversine_m(truth, hit.coordinate) <= radius_m:
            return index
    return None


def establish_truth(
    geocoder, case: dict, origin: Coordinate, limit: int,
) -> tuple[Coordinate | None, str]:
    """Where the *correct* spelling lands. Returns (coordinate, name).

    An explicit `truth` in the case wins — that is the escape hatch for a
    canonical spelling the geocoder itself resolves badly, which would
    otherwise score every variant beneath it against the wrong place.
    """
    if "truth" in case:
        return parse_coordinate(case["truth"]), f"{case['place']} (pinned)"

    hits = geocoder.geocode(case["place"], limit=limit, near=origin)
    if not hits:
        return None, ""
    ranked = rank_candidates(
        hits, origin=origin, query=case["place"],
        prefer_nearest=bool(case["nearest"]),
    )
    return ranked[0].coordinate, ranked[0].name


def probe_one(
    geocoder,
    case: dict,
    heard: str,
    is_control: bool,
    origin: Coordinate,
    truth: Coordinate,
    limit: int,
    wide_limit: int,
    radius_m: float,
) -> Probe:
    """Put one transcript through exactly what the executor does to it.

    `_handle_navigation_start` asks for `GEOCODE_CANDIDATE_LIMIT`
    candidates and ranks them locally, so that is what gets replicated
    here. The wider query runs only on a miss, and only to tell "the
    limit hid it" apart from "it was never there" — two findings with
    different fixes that look identical from inside the executor.
    """
    nearest = bool(case["nearest"])
    hits = geocoder.geocode(heard, limit=limit, near=origin)
    ranked = rank_candidates(hits, origin=origin, query=heard,
                             prefer_nearest=nearest) if hits else []

    found = find_within(ranked, truth, radius_m)
    record = Probe(
        group=case["group"], place=case["place"], heard=heard,
        is_control=is_control, outcome="absent",
        chosen=ranked[0].name if ranked else "",
    )

    if found == 0:
        record.outcome = "ok"
        record.rank = 1
        return record

    if found is not None:
        # In the window but beaten. Record both name scores: this is the
        # evidence that decides whether fuzzy token matching would help,
        # and a guess about it is worth less than the column.
        true_hit = ranked[found]
        winner = ranked[0]
        record.outcome = "misranked"
        record.rank = found + 1
        record.truth_score = name_match_score(heard, true_hit.name)
        record.chosen_score = name_match_score(heard, winner.name)
        record.error_m = haversine_m(truth, winner.coordinate)
        return record

    wide = geocoder.geocode(heard, limit=wide_limit, near=origin)
    wide_found = find_within(wide, truth, radius_m)
    if wide_found is not None:
        record.outcome = "window"
        record.rank = wide_found + 1      # Photon's own order, not ranked
    if ranked:
        record.error_m = haversine_m(truth, ranked[0].coordinate)
    return record


def _describe_error(record: Probe) -> str:
    """One line saying what the user would experience, not what the code did."""
    if record.outcome == "ok":
        return "routed correctly"
    where = f"{record.error_m / 1000:.1f} km away" if record.error_m else "nowhere"
    if not record.chosen:
        return "no candidates at all — the wearable says it cannot find the place"
    return f"would route to {record.chosen!r}, {where} from the right place"


def report(records: list[Probe], unusable: list[tuple[str, str]],
           limit: int, wide_limit: int, radius_m: float) -> None:
    """Print the scored result, split the ways that drive different fixes."""
    total = len(records)
    if not total:
        print("\nNothing scored.")
        return

    def tally(subset: list[Probe]) -> dict[str, int]:
        return {outcome: sum(1 for r in subset if r.outcome == outcome)
                for outcome in OUTCOMES}

    def line(label: str, subset: list[Probe]) -> None:
        if not subset:
            return
        counts = tally(subset)
        n = len(subset)
        found = counts["ok"] + counts["misranked"]
        print(f"  {label:12s} n={n:3d}   "
              f"ok {counts['ok']:3d} ({100 * counts['ok'] / n:5.1f}%)   "
              f"retrieved {found:3d} ({100 * found / n:5.1f}%)   "
              f"misranked {counts['misranked']:3d}   "
              f"window {counts['window']:3d}   absent {counts['absent']:3d}")

    print("\n" + "=" * 78)
    print("RESULT")
    print("=" * 78)
    print(f"  candidate limit : {limit} (config.GEOCODE_CANDIDATE_LIMIT)")
    print(f"  wide limit      : {wide_limit}")
    print(f"  match radius    : {radius_m:.0f} m")
    print()
    print("  'retrieved' = the right place was in the candidate window at all.")
    print("  'ok'        = it was also ranked first, which is what the user gets.")
    print()

    controls = [r for r in records if r.is_control]
    misheard = [r for r in records if not r.is_control]
    line("ALL", records)
    line("control", controls)
    line("misheard", misheard)

    print("\nBy tier (misheard transcripts only):")
    for group in GROUPS:
        line(group, [r for r in misheard if r.group == group])

    # The cost of mishearing, stated as one number rather than left for
    # the reader to subtract. Control is the ceiling this chain could
    # reach if transcription were perfect.
    if controls and misheard:
        control_ok = 100 * sum(r.outcome == "ok" for r in controls) / len(controls)
        misheard_ok = 100 * sum(r.outcome == "ok" for r in misheard) / len(misheard)
        print(f"\n  Cost of mishearing: {control_ok:.1f}% -> {misheard_ok:.1f}% "
              f"({misheard_ok - control_ok:+.1f} points)")

    failures = [r for r in records if r.outcome != "ok"]
    if failures:
        print(f"\nFailures ({len(failures)}):")
        for r in failures:
            tag = "control" if r.is_control else "heard"
            print(f"  [{r.group}/{tag}] {r.place!r} heard as {r.heard!r} "
                  f"-> {r.outcome}"
                  + (f" at rank {r.rank}" if r.rank else ""))
            print(f"      {_describe_error(r)}")
            if r.outcome == "misranked":
                print(f"      name score: true place {r.truth_score:.2f}, "
                      f"chosen {r.chosen_score:.2f}")

    if unusable:
        print(f"\nUnusable cases ({len(unusable)}) — NOT counted above:")
        for place, why in unusable:
            print(f"  {place!r}: {why}")
        print("  Pin these with an explicit \"truth\": \"lat,lon\" in the case, "
              "or drop them —\n  they are not in this Photon extract.")

    _interpret(records)


def _interpret(records: list[Probe]) -> None:
    """Say which of the three fixes the numbers point at.

    Deliberately counts rather than concludes. The probe's job is to
    replace an argument about what is probably wrong with the evidence
    for it; picking the fix is still a decision to defend.
    """
    misranked = [r for r in records if r.outcome == "misranked"]
    collapsed = [r for r in misranked if r.truth_score == 0.0]
    window = [r for r in records if r.outcome == "window"]
    absent = [r for r in records if r.outcome == "absent"]

    print("\n" + "-" * 78)
    print("WHAT THIS POINTS AT")
    print("-" * 78)
    print(f"  {len(misranked):3d} misranked — ranking saw the right place and "
          f"chose another.")
    print(f"      of those, {len(collapsed)} scored 0.00 against the true place, "
          f"i.e. the name\n      signal vanished and the sort was pure distance. "
          f"Fuzzy token scoring\n      in `ranking.py` addresses exactly these; "
          f"it cannot touch the others.")
    print(f"  {len(window):3d} window-only — present further down Photon's list. "
          f"Raising\n      GEOCODE_CANDIDATE_LIMIT reaches these and nothing else.")
    print(f"  {len(absent):3d} absent — Photon's own fuzziness did not stretch "
          f"this far.\n      No local ranking change reaches these: it is the "
          f"query, the index,\n      or the transcript that has to improve.")
    print("\n  None of the above is fixed by the confirmation prompt, which "
          "catches a\n  wrong choice but then cancels — the user re-speaks the "
          "same words and\n  gets the same answer.")
    print("\n  Caveat, every run: the corpus is seeded by hand. See the header "
          "of\n  cases/destinations.jsonl before quoting a number from this.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Score how often a misheard destination still resolves.")
    parser.add_argument("--cases", type=Path, default=CASES_PATH,
                        help=f"JSONL corpus (default {CASES_PATH.name})")
    parser.add_argument("--url", default=PHOTON_URL,
                        help=f"Photon base URL (default {PHOTON_URL})")
    parser.add_argument("--limit", type=int, default=GEOCODE_CANDIDATE_LIMIT,
                        help=f"candidates the executor sees (default "
                             f"{GEOCODE_CANDIDATE_LIMIT}, as "
                             f"config.GEOCODE_CANDIDATE_LIMIT)")
    parser.add_argument("--wide", type=int, default=50,
                        help="wider limit, used only to tell 'the window hid "
                             "it' from 'it was never there' (default 50)")
    parser.add_argument("--radius", type=float, default=_DEFAULT_RADIUS_M,
                        help=f"metres within which a candidate counts as the "
                             f"same place (default {_DEFAULT_RADIUS_M:.0f})")
    parser.add_argument("--only", choices=GROUPS,
                        help="score one tier only")
    args = parser.parse_args(argv)

    if not args.cases.is_file():
        print(f"no case file at {args.cases}", file=sys.stderr)
        return 2

    cases = load_cases(args.cases)
    if args.only:
        cases = [c for c in cases if c["group"] == args.only]
    if not cases:
        print("no cases to run", file=sys.stderr)
        return 2

    from indepensense.routing.photon import PhotonGeocoder

    geocoder = PhotonGeocoder(base_url=args.url)

    print(f"Photon : {args.url}")
    print(f"cases  : {args.cases} ({len(cases)} places)")
    print(f"limit  : {args.limit}   wide: {args.wide}   "
          f"radius: {args.radius:.0f} m")
    print("\nResolving ground truth from each canonical spelling "
          "(check these once):")

    records: list[Probe] = []
    unusable: list[tuple[str, str]] = []

    for case in cases:
        try:
            origin = parse_coordinate(case["origin"])
        except ValueError as exc:
            unusable.append((case["place"], f"bad origin on line {case['line']}: {exc}"))
            continue

        try:
            truth, truth_name = establish_truth(geocoder, case, origin, args.limit)
        except Exception as exc:
            print(f"\ngeocode failed: {exc}", file=sys.stderr)
            print("Is Photon up? `systemctl status photon`", file=sys.stderr)
            return 1

        if truth is None:
            unusable.append((case["place"],
                             "the canonical spelling itself returns nothing"))
            print(f"  {case['place']:28s} -> NOT FOUND (case skipped)")
            continue

        print(f"  {case['place']:28s} -> {truth_name or '(unnamed)'} "
              f"@ {truth.lat:.5f},{truth.lon:.5f} "
              f"[{haversine_m(origin, truth) / 1000:.1f} km]")

        # Control first, so the per-case output reads as "here is the
        # ceiling, here is what mishearing costs against it".
        for heard, is_control in [(case["place"], True)] + [
            (h, False) for h in case["heard"]
        ]:
            records.append(probe_one(
                geocoder, case, heard, is_control, origin, truth,
                args.limit, args.wide, args.radius,
            ))

    report(records, unusable, args.limit, args.wide, args.radius)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
