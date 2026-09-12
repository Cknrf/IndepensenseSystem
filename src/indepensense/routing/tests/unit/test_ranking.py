"""Unit tests for geocoder candidate ranking.

Fixed coordinates, no network, no Photon. The whole point of moving this
decision out of the geocoder is that it becomes testable arithmetic, so
these cover the two real-world failures that motivated it:

  - a chain query resolving to a branch hundreds of kilometres away
  - a specific named place losing to a closer near-miss on the name
"""
import pytest

from indepensense.routing.base import Coordinate, GeocodingResult, haversine_m
from indepensense.routing.ranking import (
    name_match_score,
    normalise_name,
    rank_candidates,
)

# The user is standing in Lipa City, Batangas.
LIPA = Coordinate(lat=13.9411, lon=121.1622)


def _place(name: str, lat: float, lon: float) -> GeocodingResult:
    return GeocodingResult(
        name=name,
        coordinate=Coordinate(lat=lat, lon=lon),
        country="Philippines",
        city=None,
        feature_type="restaurant",
    )


# --- haversine (moved here from navigation.monitor) --------------------------

def test_haversine_matches_a_known_degree_of_latitude():
    """One degree of latitude is ~111.2 km anywhere on the globe."""
    d = haversine_m(Coordinate(0.0, 0.0), Coordinate(1.0, 0.0))
    assert d == pytest.approx(111_195, rel=0.001)


def test_haversine_is_zero_for_identical_points():
    assert haversine_m(LIPA, LIPA) == pytest.approx(0.0, abs=1e-6)


# --- name normalisation ------------------------------------------------------

def test_normalise_folds_case_and_punctuation():
    assert normalise_name("St. Luke's Medical Center") == "st lukes medical center"


def test_normalise_keeps_apostrophised_words_whole():
    """"Luke's" must become one token. Splitting it into "luke" and "s"
    would drop a token from the overlap and score a perfect name match as
    a partial one."""
    assert normalise_name("Luke's") == "lukes"


def test_normalise_splits_on_hyphens_and_collapses_space():
    assert normalise_name("  7-Eleven   Lipa  ") == "7 eleven lipa"


# --- name match score --------------------------------------------------------

def test_identical_names_score_one():
    assert name_match_score("Jollibee", "Jollibee") == 1.0


def test_extra_words_in_the_candidate_are_not_penalised():
    """A branch's OSM name routinely carries its location. Penalising
    that would rank the generic entry above the actual branch."""
    assert name_match_score("Jollibee", "Jollibee Lipa City") == 1.0


def test_missing_query_words_lower_the_score():
    assert name_match_score("Jollibee Lipa", "Jollibee") == pytest.approx(0.5)


def test_scoring_ignores_punctuation_differences():
    assert name_match_score("st lukes medical center", "St. Luke's Medical Center") == 1.0


def test_a_near_miss_scores_below_the_real_match():
    query = "St. Luke's Medical Center"
    assert name_match_score(query, "St. Luke's Chapel") < name_match_score(query, query)


def test_an_empty_query_scores_zero():
    """Leaves ranking to distance alone rather than crashing on a
    zero-length token set."""
    assert name_match_score("", "Jollibee") == 0.0


# --- ranking -----------------------------------------------------------------

def test_no_candidates_returns_empty():
    assert rank_candidates([], origin=LIPA, query="Jollibee") == []


def test_the_regression_a_chain_resolves_to_the_local_branch():
    """The bug this module exists for: Photon returned the Tacloban
    Jollibee (~450 km away) ahead of the one down the road."""
    tacloban = _place("Jollibee", 11.2444, 125.0048)
    lipa = _place("Jollibee Lipa City", 13.9430, 121.1640)

    ranked = rank_candidates([tacloban, lipa], origin=LIPA, query="Jollibee")

    assert ranked[0] is lipa


def test_name_match_outranks_proximity_for_a_specific_place():
    """"Take me to St. Luke's Medical Center" must not land on a chapel
    200 m away just because it is closer. The user said which one."""
    chapel = _place("St. Luke's Chapel", 13.9420, 121.1630)          # very close
    hospital = _place("St. Luke's Medical Center", 14.0500, 121.3000)  # far

    ranked = rank_candidates(
        [chapel, hospital], origin=LIPA, query="St. Luke's Medical Center",
    )

    assert ranked[0] is hospital


def test_nearest_ignores_name_match_entirely():
    """"The nearest hospital" is a category query — Photon matches on OSM
    feature type, so correct answers often do not contain the word
    "hospital" at all. Filtering by name would discard them."""
    far_named = _place("Lipa Hospital", 14.0500, 121.3000)
    near_unnamed = _place("Mary Mediatrix Medical Center", 13.9420, 121.1630)

    ranked = rank_candidates(
        [far_named, near_unnamed], origin=LIPA, query="hospital", prefer_nearest=True,
    )

    assert ranked[0] is near_unnamed


def test_distance_settles_ties_within_the_best_name_tier():
    near = _place("Jollibee Lipa City", 13.9420, 121.1630)
    mid = _place("Jollibee Tambo", 13.9600, 121.1800)
    far = _place("Jollibee Batangas City", 13.7565, 121.0583)

    ranked = rank_candidates([far, mid, near], origin=LIPA, query="Jollibee")

    assert [c.name for c in ranked] == [near.name, mid.name, far.name]


def test_candidates_that_match_nothing_by_name_fall_back_to_distance():
    """Every candidate ties at zero, so the tier filter keeps them all and
    distance decides — the right degenerate behaviour, not an empty list."""
    near = _place("Mercury Drug", 13.9420, 121.1630)
    far = _place("Watsons", 14.0500, 121.3000)

    ranked = rank_candidates([far, near], origin=LIPA, query="pharmacy")

    assert ranked[0] is near
    assert len(ranked) == 2


def test_nearest_keeps_every_candidate():
    """Distance-only mode reorders but must never discard — the caller may
    want to offer the runner-up if the user rejects the first."""
    a = _place("Jollibee", 13.9420, 121.1630)
    b = _place("Chowking", 14.0500, 121.3000)

    assert len(rank_candidates([a, b], LIPA, "food", prefer_nearest=True)) == 2


def test_the_input_list_is_not_mutated():
    a = _place("Jollibee Far", 14.0500, 121.3000)
    b = _place("Jollibee Near", 13.9420, 121.1630)
    candidates = [a, b]

    rank_candidates(candidates, origin=LIPA, query="Jollibee")

    assert candidates == [a, b]
