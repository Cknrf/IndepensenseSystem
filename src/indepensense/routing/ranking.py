"""Pick which geocoder candidate the user actually meant.

A geocoder answers "what best matches this text, nudged toward here". It
cannot answer "which of these is nearest to me" — that is not a query
Photon exposes, and its relevance score blends text match with a location
bias we can neither inspect nor control (see the note in
`routing/photon.py` about `location_bias_scale`). Asking for one result
and trusting it is what sends a user in Lipa to a Jollibee in Tacloban.

So the executor asks for several candidates and decides here, with
arithmetic that can be unit-tested against fixed coordinates.

Two signals, and which one dominates depends on what the user said:

  - **The user named something specific** ("St. Luke's Medical Center").
    Name match decides. Keep only the best-matching tier, then break
    ties by distance. Without the name tier, a "St. Luke's Chapel" 200 m
    away outranks the actual hospital 3 km away — the user said which
    one they meant and we ignored it.

  - **The user asked for whatever is closest** ("the nearest Jollibee",
    "pinakamalapit na ospital"). Distance decides, name match is not
    consulted at all. This is deliberate: for a category query like
    "hospital", Photon matches on the OSM feature type as well as the
    name, so the correct answers frequently do not contain the queried
    word anywhere in their name. Filtering those out by name would
    discard exactly the results the user wanted.

That distinction is what the NLU's `nearest` parameter is for. Hardcoding
it to true would be the same bug in the other direction — it discards the
name signal on queries where the name is the whole point.
"""
import re

from indepensense.routing.base import Coordinate, GeocodingResult, haversine_m

# Apostrophes are intra-word — "Luke's" must fold to "lukes", not
# "luke s", or the token overlap against "St. Luke's" silently drops a
# token and scores a perfect match as a partial one.
_APOSTROPHES = "'’ʼ`"

# Float slack when grouping candidates into the best-scoring tier. Scores
# are small rational fractions, so this only absorbs representation error,
# not genuinely different scores.
_TIER_EPSILON = 1e-6


def normalise_name(text: str) -> str:
    """Fold a place name to lowercase alphanumeric words separated by spaces.

    Apostrophes vanish; every other non-alphanumeric character becomes a
    separator, so "St. Luke's Medical Center" and "st lukes medical center"
    compare equal and "7-Eleven" becomes "7 eleven".
    """
    lowered = text.lower()
    for mark in _APOSTROPHES:
        lowered = lowered.replace(mark, "")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", lowered).split())


def name_match_score(query: str, name: str) -> float:
    """How well `name` covers what the user asked for, from 0.0 to 1.0.

    The fraction of the query's words that appear in the candidate's name.
    Extra words in the candidate are NOT penalised, because a branch's OSM
    name routinely carries its location ("Jollibee Lipa City") and
    penalising that would demote the specific branch below the generic
    entry — the opposite of what the user wants.

    Asymmetric on purpose:

        query "jollibee"  vs "Jollibee Lipa City"   -> 1.0  (all of it is there)
        query "jollibee lipa" vs "Jollibee"         -> 0.5  (half of it is missing)

    An empty query scores 0.0 for everything, which leaves ranking to
    distance alone — the safe degenerate behaviour.
    """
    query_tokens = set(normalise_name(query).split())
    if not query_tokens:
        return 0.0
    name_tokens = set(normalise_name(name).split())
    return len(query_tokens & name_tokens) / len(query_tokens)


def rank_candidates(
    candidates: list[GeocodingResult],
    origin: Coordinate,
    query: str,
    prefer_nearest: bool = False,
) -> list[GeocodingResult]:
    """Order geocoder candidates best-first for a user standing at `origin`.

    `prefer_nearest` mirrors the NLU's `nearest` parameter — true when the
    user said "nearest", "closest", "pinakamalapit". See the module
    docstring for why the two modes differ rather than one being a tweak
    of the other.

    Returns a new list; the input is not mutated. An empty input returns
    an empty list.
    """
    if not candidates:
        return []

    if prefer_nearest:
        return sorted(candidates, key=lambda c: haversine_m(origin, c.coordinate))

    scored = [(name_match_score(query, c.name), c) for c in candidates]
    best_score = max(score for score, _ in scored)
    # Keep only the joint-best matches, then let distance settle it. When
    # nothing matches by name at all every candidate ties at 0.0 and this
    # degrades to a pure distance sort, which is the right fallback.
    finalists = [c for score, c in scored if score >= best_score - _TIER_EPSILON]
    return sorted(finalists, key=lambda c: haversine_m(origin, c.coordinate))
