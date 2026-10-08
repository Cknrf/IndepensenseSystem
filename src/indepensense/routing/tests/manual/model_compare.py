"""Manual test: does a routing weighting change help everywhere, or just once?

A candidate custom model was found by tuning against a single journey —
origin to the nearest Jollibee — where it cut 1.57 km / 17 instructions
down to 1.44 km / 5, matching Google and OSRM. One route is not evidence
for a weighting change. Tuning until one example looks right is how you
ship a model that is worse on average and better on the case you stared
at.

So this runs both models over many destinations and prints them side by
side. Two numbers per route, and the instruction count matters as much
as the distance: this wearable *speaks* every instruction, and a route
that is 100 m shorter but says eighteen things is worse for a user who
cannot see, not better.

What to look for
----------------

  * **Instructions down, distance about the same** — the candidate is
    removing pointless weaving. Adopt it.
  * **Distance up more than a few percent on some routes** — it is
    buying straightness with real walking. Look at those routes
    individually before adopting.
  * **Any route that gets dramatically worse** — the candidate has a
    failure mode the tuned example did not show. That is the whole
    reason this script exists.

Nothing here changes the server. Both models are sent per-request with
`ch.disable=true`, so this compares weightings on the live graph without
a rebuild — which is what makes it cheap enough to run before adopting
rather than after.

Usage
-----

    python -m indepensense.routing.tests.manual.model_compare \\
        --from 13.937387,121.118698

    # your own destinations — a place name, or a fixed lat,lon
    python -m indepensense.routing.tests.manual.model_compare \\
        --from 13.937387,121.118698 --to "SM Lipa" --to 13.956494,121.166000

    # a different delta, without editing CANDIDATE_MODEL
    python -m indepensense.routing.tests.manual.model_compare \\
        --from 13.937387,121.118698 \\
        --candidate '{"priority": [{"if": "road_class == TRUNK", "multiply_by": "4"}]}'

A place name resolves to the *nearest* match, so every default
destination is a short walk. Long walks along a corridor — where a
weighting that saturates at 2 km may stop saturating — need a fixed
`lat,lon`.

Needs Photon and GraphHopper running.
"""
import argparse
import json
import sys

from indepensense.config import GRAPHHOPPER_URL, PHOTON_URL
from indepensense.routing.base import Coordinate, haversine_m
from indepensense.routing.ranking import rank_candidates

# **A request custom model is MERGED with the profile's own model, not
# substituted for it.** Everything sent here is multiplied on top of the
# jar's foot.json, which `config.yml` already loads.
#
# That cost an hour of wrong conclusions. Sending a copy of the stock
# model as a "baseline" applied `foot_priority` twice and reported the
# baseline as 3.16 km / 29 instructions on a route the device really
# walks in 1.57 / 17 — making every candidate look better than it was.
# Worse, an early test that *removed* `foot_priority` appeared to change
# nothing, because the profile's copy was still applied regardless; that
# null result sent the investigation off in the wrong direction twice.
#
# So the baseline is an empty model — the profile exactly as the device
# runs it — and the candidate is only the delta.
BASELINE_MODEL: dict = {"priority": [], "speed": []}

# The delta currently under test, layered on whatever the profile
# already has. Update this when evaluating a new change; the baseline
# above always means "the device as it runs today".
#
# **Round 2: trunk x 1.5.** Round 1's service penalty stopped the router
# weaving across the highway between short frontage stubs, but it did
# not stop it abandoning the corridor altogether. Going 2 km east the
# router took 174 m of highway, detoured 1334 m through side roads, and
# came back — 3.85 km and 21 instructions where OSRM walks 2.5 km in 5.
#
# Cause is the same `foot_priority` that makes trunk expensive per
# metre. Once the alternative is a *network* of ordinary roads rather
# than short stubs, the long way round wins. Multiplying trunk back up
# cancels that.
#
# 1.5 is the smallest value that works: 1.5, 2.0 and 3.0 all produce the
# identical route on both test journeys, so the effect saturates and a
# larger number would only risk over-attracting to highways somewhere
# untested.
#
#   trunk x1.0 (control)  1.45 km  6i   |  3.85 km  21i
#   trunk x1.5            1.44 km  5i   |  2.52 km   5i
#   OSRM, same points     1.4 km  ~4i   |  2.5 km    5
CANDIDATE_MODEL = {
    "priority": [
        {"if": "road_class == TRUNK", "multiply_by": "1.5"},
    ],
}

# Destinations around Lipa, chosen to exercise different surroundings
# rather than to flatter the candidate: a highway corridor, a city
# centre, a campus, a hospital, a market. If a weighting only behaves on
# one kind of place, that shows up here.
DEFAULT_DESTINATIONS = (
    "Jollibee",
    "SM City Lipa",
    "Lipa City Hall",
    "hospital",
    "public market",
    "church",
    "school",
    "pharmacy",
    "gasoline station",
    "Robinsons",
)


def _parse_origin(text: str) -> Coordinate:
    try:
        lat_text, _, lon_text = text.partition(",")
        return Coordinate(lat=float(lat_text), lon=float(lon_text))
    except ValueError:
        raise ValueError(f"expected lat,lon — got {text!r}") from None


def _route(origin: Coordinate, destination: Coordinate, model) -> tuple | None:
    """(km, instruction count) under `model`, or None if no route."""
    import requests  # lazy

    try:
        response = requests.post(
            f"{GRAPHHOPPER_URL}/route",
            json={
                "points": [[origin.lon, origin.lat],
                           [destination.lon, destination.lat]],
                "profile": "foot",
                "ch.disable": True,          # required for a per-request model
                "instructions": True,
                "points_encoded": False,
                "custom_model": model,
            },
            timeout=20.0,
        )
        response.raise_for_status()
        path = response.json()["paths"][0]
    except Exception as exc:
        print(f"    routing failed: {exc}", file=sys.stderr)
        return None
    return path["distance"] / 1000.0, len(path["instructions"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare two foot weightings across many destinations.")
    parser.add_argument("--from", dest="origin", required=True, metavar="LAT,LON")
    parser.add_argument("--to", dest="destinations", action="append",
                        metavar="QUERY",
                        help="destination to test: a place name or LAT,LON "
                             "(repeatable; defaults to a spread of Lipa "
                             "landmarks)")
    parser.add_argument("--candidate", metavar="JSON",
                        help="custom-model delta to test instead of "
                             "CANDIDATE_MODEL")
    args = parser.parse_args(argv)

    candidate_model = CANDIDATE_MODEL
    if args.candidate:
        try:
            candidate_model = json.loads(args.candidate)
        except ValueError as exc:
            print(f"bad --candidate: {exc}", file=sys.stderr)
            return 2

    try:
        origin = _parse_origin(args.origin)
    except ValueError as exc:
        print(f"bad --from: {exc}", file=sys.stderr)
        return 2

    from indepensense.routing.photon import PhotonGeocoder

    geocoder = PhotonGeocoder(base_url=PHOTON_URL)
    queries = args.destinations or list(DEFAULT_DESTINATIONS)

    print(f"origin: {origin.lat:.6f}, {origin.lon:.6f}")
    print(f"{'destination':24}  {'profile':>14}  {'candidate':>14}   verdict")
    print("-" * 78)

    deltas: list[tuple[str, float, int]] = []
    for query in queries:
        try:
            destination = _parse_origin(query)
        except ValueError:
            hits = geocoder.geocode(query, limit=10, near=origin)
            if not hits:
                print(f"{query[:24]:24}  {'(not found)':>14}")
                continue
            destination = rank_candidates(hits, origin=origin, query=query,
                                          prefer_nearest=True)[0].coordinate

        stock = _route(origin, destination, BASELINE_MODEL)
        candidate = _route(origin, destination, candidate_model)
        if stock is None or candidate is None:
            continue

        km_delta = candidate[0] - stock[0]
        instr_delta = candidate[1] - stock[1]
        deltas.append((query, km_delta, instr_delta))

        # Longer is only acceptable if it buys a real drop in how much
        # the wearable has to say. 10% is the line: past that the user is
        # walking meaningfully further to hear fewer turns.
        # Turn count alone is not a verdict. A candidate that walks half
        # a kilometre LESS while adding six turns was once flagged
        # "WORSE — more turns", which read as a regression and was the
        # opposite. Distance is checked first, and extra turns only
        # count against a route that is not also shorter.
        if km_delta > stock[0] * 0.10:
            verdict = "WORSE — much longer"
        elif instr_delta >= 3 and km_delta > -0.05:
            verdict = "WORSE — more turns"
        elif instr_delta <= -3 or km_delta < -0.05:
            verdict = "better"
        else:
            verdict = "~same"

        print(f"{query[:24]:24}  "
              f"{stock[0]:6.2f} km {stock[1]:3d}i  "
              f"{candidate[0]:6.2f} km {candidate[1]:3d}i   {verdict}")

    if not deltas:
        print("\nNo routes compared.")
        return 1

    print("-" * 78)
    total_km = sum(d for _, d, _ in deltas)
    total_instr = sum(i for _, _, i in deltas)
    worse = [q for q, d, i in deltas if i >= 3 or d > 0.3]
    print(f"{len(deltas)} routes: distance {total_km:+.2f} km total, "
          f"instructions {total_instr:+d} total")
    if worse:
        print(f"\nRoutes the candidate made worse: {', '.join(worse)}")
        print("Look at those individually before adopting — a weighting that "
              "wins on average can still be dangerous on one route.")
    else:
        print("\nNo route got meaningfully worse.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
