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

    # your own destinations
    python -m indepensense.routing.tests.manual.model_compare \\
        --from 13.937387,121.118698 --to "SM Lipa" --to "hospital"

Needs Photon and GraphHopper running.
"""
import argparse
import sys

from indepensense.config import GRAPHHOPPER_URL, PHOTON_URL
from indepensense.routing.base import Coordinate, haversine_m
from indepensense.routing.ranking import rank_candidates

# GraphHopper's bundled foot model, as shipped in graphhopper-web-11.0.jar
# at com/graphhopper/custom_models/foot.json. The Germany-specific
# bridleway rule is dropped — it cannot fire here and only adds noise.
STOCK_MODEL = {
    "priority": [
        {"if": "!foot_access || hike_rating >= 2", "multiply_by": "0"},
        {"else": "", "multiply_by": "foot_priority"},
        {"if": "mtb_rating > 3", "multiply_by": "0.7"},
        {"if": "foot_road_access == PRIVATE", "multiply_by": "0.1"},
    ],
    "speed": [{"if": "true", "limit_to": "foot_average_speed"}],
}

# The candidate. Two deliberate differences from stock, both measured:
#
#   `foot_priority` removed. It rates how pleasant a way is to walk on,
#   and scores `trunk` low. Philippine national highways are trunk, so
#   every metre of the corridor the user actually walks cost several
#   times a metre of anything beside it — and the router left the
#   corridor entirely once the alternatives were also penalised
#   (3.13 km / 25 instructions with it, 1.44 / 5 without).
#
#   `service` penalised. Short frontage-road stubs run parallel to the
#   highway and connect at every junction. With distance-only cost the
#   router took whichever was a few metres shorter between each pair of
#   junctions, weaving across the highway eight times in 1.6 km. Each
#   weave is a road crossing announced to someone who cannot see it.
CANDIDATE_MODEL = {
    "priority": [
        {"if": "!foot_access || hike_rating >= 2", "multiply_by": "0"},
        {"if": "foot_road_access == PRIVATE", "multiply_by": "0.1"},
        {"if": "road_class == SERVICE", "multiply_by": "0.6"},
    ],
    "speed": [{"if": "true", "limit_to": "foot_average_speed"}],
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
                        help="destination to test (repeatable; defaults to a "
                             "spread of Lipa landmarks)")
    args = parser.parse_args(argv)

    try:
        origin = _parse_origin(args.origin)
    except ValueError as exc:
        print(f"bad --from: {exc}", file=sys.stderr)
        return 2

    from indepensense.routing.photon import PhotonGeocoder

    geocoder = PhotonGeocoder(base_url=PHOTON_URL)
    queries = args.destinations or list(DEFAULT_DESTINATIONS)

    print(f"origin: {origin.lat:.6f}, {origin.lon:.6f}")
    print(f"{'destination':24}  {'stock':>14}  {'candidate':>14}   verdict")
    print("-" * 78)

    deltas: list[tuple[str, float, int]] = []
    for query in queries:
        hits = geocoder.geocode(query, limit=10, near=origin)
        if not hits:
            print(f"{query[:24]:24}  {'(not found)':>14}")
            continue
        target = rank_candidates(hits, origin=origin, query=query,
                                 prefer_nearest=True)[0]

        stock = _route(origin, target.coordinate, STOCK_MODEL)
        candidate = _route(origin, target.coordinate, CANDIDATE_MODEL)
        if stock is None or candidate is None:
            continue

        km_delta = candidate[0] - stock[0]
        instr_delta = candidate[1] - stock[1]
        deltas.append((query, km_delta, instr_delta))

        # Longer is only acceptable if it buys a real drop in how much
        # the wearable has to say. 10% is the line: past that the user is
        # walking meaningfully further to hear fewer turns.
        if km_delta > stock[0] * 0.10:
            verdict = "WORSE — much longer"
        elif instr_delta <= -3:
            verdict = "better"
        elif instr_delta >= 3:
            verdict = "WORSE — more turns"
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
