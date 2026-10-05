"""Manual test: see exactly why the wearable chose the destination it did.

Field report: "take me to the nearest Jollibee" from Lipa announced
17 km. The NLU was innocent — the log shows `nearest: True` parsed
correctly — and so is `rank_candidates`, which for a nearest query is a
pure distance sort and cannot pick a far candidate over a near one.

Run against the coordinates from that day, this probe cleared the
geocoder too: Photon returns the 1.3 km Lipa branch at rank 1, at every
limit tried. So the chain *geocode -> rank* was working, and the
explanation lies outside it. Two candidates remain, and `--route` tells
them apart:

  * **The walk really is that long.** The announced number is the ROUTE
    distance, not the straight line, and a foot profile will not take a
    pedestrian along a tollway. The device was at a railroad crossing on
    the Southern Tagalog Arterial Road; 1.3 km across it can be many
    kilometres around it. That is the router being right and the
    wearable being honest.
  * **The origin was not where the user was.** `GPSCache.latest_fix()`
    has no expiry: a fix from before a modem disconnect is served
    indefinitely, and ranking would faithfully sort by distance from
    somewhere the user has since left. The modem on this unit drops
    often enough for that to be routine.

What it still distinguishes, for the next query that goes wrong:

  * **Nearby candidates absent at any limit** — the Photon index does
    not have them, or they are not named what the user said. No amount
    of ranking fixes that; the index or the query does.
  * **Nearby candidates only at a higher `--limit`** — Photon returns
    its top N by *relevance*, and `config.GEOCODE_CANDIDATE_LIMIT` is
    10. One at rank 14 is invisible to the executor, and sorting the ten
    it did see is just picking the closest of the wrong set.
  * **Nearby candidates present and ranked first** — as happened here.
    Look past the geocoder: `--route`, then the origin.

Usage
-----

    # the failing case, from the fix the device had that day
    python -m indepensense.routing.tests.manual.geocode_probe \\
        "Jollibee" --from 13.937387,121.118698 --nearest

    # does a bigger candidate list contain a closer branch?
    python -m indepensense.routing.tests.manual.geocode_probe \\
        "Jollibee" --from 13.937387,121.118698 --nearest --limit 50

    # is the WALK as long as the device said? (needs GraphHopper too)
    python -m indepensense.routing.tests.manual.geocode_probe \\
        "Jollibee" --from 13.937387,121.118698 --nearest --route

    # what the raw geocoder does with no location bias at all
    python -m indepensense.routing.tests.manual.geocode_probe \\
        "Jollibee" --from 13.937387,121.118698 --no-bias

Needs Photon running (`systemctl status photon`). Does not need the
wearable, GPS, or any other hardware — `--from` supplies the position,
so this is reproducible from a desk and from a log line.
"""
import argparse
import sys

from indepensense.config import GEOCODE_CANDIDATE_LIMIT, PHOTON_URL
from indepensense.routing.base import Coordinate, haversine_m
from indepensense.routing.ranking import name_match_score, rank_candidates


def _parse_origin(text: str) -> Coordinate:
    """`"13.937387,121.118698"` -> Coordinate. Raises with the bad input named."""
    try:
        lat_text, _, lon_text = text.partition(",")
        return Coordinate(lat=float(lat_text), lon=float(lon_text))
    except ValueError:
        raise ValueError(f"expected lat,lon — got {text!r}") from None


def _show(label: str, hits, origin: Coordinate, query: str) -> None:
    print(f"\n{label}")
    print(f"  {'#':>2}  {'straight':>9}  {'match':>6}  {'coordinate':>21}  name / city")
    print("  " + "-" * 78)
    for index, hit in enumerate(hits, 1):
        metres = haversine_m(origin, hit.coordinate)
        distance = f"{metres/1000:.1f} km" if metres >= 1000 else f"{metres:.0f} m"
        city = hit.city or ""
        where = f"{hit.coordinate.lat:.5f},{hit.coordinate.lon:.5f}"
        print(f"  {index:>2}  {distance:>9}  {name_match_score(query, hit.name):>6.2f}  "
              f"{where:>21}  {hit.name}{f'  ({city})' if city else ''}")


def _route_to(origin: Coordinate, chosen) -> None:
    """Walk-route to the chosen candidate and compare with the straight line.

    This closes the loop the field report left open. A log showed
    "Navigating to Jollibee. Total distance 17 kilometers" while the
    nearest branch is 1.3 km away in a straight line — and the number the
    wearable speaks is the ROUTE distance, not the straight one. The two
    can legitimately differ by an order of magnitude: the device was at a
    railroad crossing on the Southern Tagalog Arterial Road, and a foot
    profile will not take a pedestrian along a tollway, so the walk can
    be a long way round. That is the router being right, and a wearable
    telling its blind user the truth about a 17 km walk.

    If the ratio is small, the stale-origin explanation survives instead:
    `GPSCache.latest_fix()` has no expiry, so a fix from before a modem
    disconnect is served indefinitely and ranking would faithfully sort
    by distance from somewhere the user no longer is.
    """
    from indepensense.config import GRAPHHOPPER_URL
    from indepensense.routing.graphhopper import GraphHopperRouter

    straight = haversine_m(origin, chosen.coordinate)
    try:
        route = GraphHopperRouter(base_url=GRAPHHOPPER_URL).route(
            origin, chosen.coordinate, profile="foot",
        )
    except Exception as exc:
        print(f"\nrouting failed: {exc}", file=sys.stderr)
        print("Is GraphHopper up? `systemctl status graphhopper`", file=sys.stderr)
        return

    print(f"\nOn foot      : {route.distance_m/1000:.1f} km, "
          f"{route.duration_s/60:.0f} min")
    print(f"Straight line: {straight/1000:.1f} km")
    _report_snapping(origin, chosen)
    if straight > 0:
        ratio = route.distance_m / straight
        print(f"Detour factor: {ratio:.1f}x", end="  ")
        if ratio >= 3.0:
            print("<- the walk really is that long. Expect a barrier "
                  "(tollway, river, railway) between here and there.")
        else:
            print("<- normal. If the device announced far more than this, "
                  "it was routing from a different origin.")


def _report_snapping(origin: Coordinate, chosen) -> None:
    """Where GraphHopper actually attached the route to its graph.

    The driver deliberately does not expose this — the runtime has no use
    for it — so this asks the API directly. Diagnostics are the one place
    worth reaching past a driver's interface, and the field failure is
    exactly the kind it answers: GraphHopper snaps each point to the
    nearest *routable* way, and a way the import dropped is not routable.
    `config.yml` excludes `trunk`, which in the Philippines is the tag on
    many ordinary national roads people walk along — so a start beside
    one can snap somewhere else entirely, and the route from there is
    long for a reason that has nothing to do with the destination.

    Also prints the same journey on a public foot router. That is a
    second opinion from different data and a different engine: if the
    reference is short and ours is long, the difference is in our graph,
    not in the terrain.
    """
    import requests  # lazy

    from indepensense.config import GRAPHHOPPER_URL

    try:
        response = requests.get(
            f"{GRAPHHOPPER_URL}/route",
            params={
                "point": [f"{origin.lat},{origin.lon}",
                          f"{chosen.coordinate.lat},{chosen.coordinate.lon}"],
                "profile": "foot",
                "points_encoded": "false",
            },
            timeout=10.0,
        )
        response.raise_for_status()
        snapped = response.json()["paths"][0]["snapped_waypoints"]["coordinates"]
    except Exception as exc:
        print(f"  (could not read snapped waypoints: {exc})")
        return

    # GeoJSON is lon,lat — the opposite order to everything else here.
    for label, (lon, lat), asked in (
        ("start", snapped[0], origin),
        ("end", snapped[-1], chosen.coordinate),
    ):
        off = haversine_m(asked, Coordinate(lat=lat, lon=lon))
        flag = "  <- snapped a long way; the graph has no walkable way nearby" \
            if off > 150 else ""
        print(f"  {label} snapped {off:>6.0f} m from where it was asked{flag}")

    print(
        f"\nCompare on a public foot router (different data, different engine):\n"
        f"  https://www.openstreetmap.org/directions?engine=fossgis_osrm_foot"
        f"&route={origin.lat:.6f}%2C{origin.lon:.6f}%3B"
        f"{chosen.coordinate.lat:.6f}%2C{chosen.coordinate.lon:.6f}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Show Photon's candidates and how ranking orders them.")
    parser.add_argument("query", help="what the user said, e.g. 'Jollibee'")
    parser.add_argument("--from", dest="origin", required=True, metavar="LAT,LON",
                        help="where the user was standing")
    parser.add_argument("--limit", type=int, default=GEOCODE_CANDIDATE_LIMIT,
                        help=f"candidates to request (default {GEOCODE_CANDIDATE_LIMIT}, "
                             f"as config.GEOCODE_CANDIDATE_LIMIT)")
    parser.add_argument("--nearest", action="store_true",
                        help="rank as if the user said 'nearest' / 'pinakamalapit'")
    parser.add_argument("--no-bias", action="store_true",
                        help="omit lat/lon from the Photon query, to see what the "
                             "location bias is actually contributing")
    parser.add_argument("--route", action="store_true",
                        help="also ask GraphHopper to walk to the top choice. A "
                             "short straight line and a long route is a real "
                             "answer, not a bug: a pedestrian cannot cross a "
                             "tollway, and the wearable announces the ROUTE "
                             "distance")
    args = parser.parse_args(argv)

    try:
        origin = _parse_origin(args.origin)
    except ValueError as exc:
        print(f"bad --from: {exc}", file=sys.stderr)
        return 2

    from indepensense.routing.photon import PhotonGeocoder

    geocoder = PhotonGeocoder(base_url=PHOTON_URL)
    print(f"Photon   : {PHOTON_URL}")
    print(f"query    : {args.query!r}")
    print(f"origin   : {origin.lat:.6f}, {origin.lon:.6f}")
    print(f"limit    : {args.limit}")
    print(f"bias     : {'OFF (no lat/lon sent)' if args.no_bias else 'on'}")

    try:
        hits = geocoder.geocode(
            args.query, limit=args.limit,
            near=None if args.no_bias else origin,
        )
    except Exception as exc:
        print(f"\ngeocode failed: {exc}", file=sys.stderr)
        print("Is Photon up? `systemctl status photon`", file=sys.stderr)
        return 1

    if not hits:
        print("\nNo candidates at all. The index does not contain this name — "
              "which is a different problem from choosing badly between branches.")
        return 1

    _show(f"As Photon returned them ({len(hits)} candidates, by its own relevance):",
          hits, origin, args.query)

    ranked = rank_candidates(hits, origin=origin, query=args.query,
                             prefer_nearest=args.nearest)
    _show(f"After rank_candidates(prefer_nearest={args.nearest}):",
          ranked, origin, args.query)

    chosen = ranked[0]
    metres = haversine_m(origin, chosen.coordinate)
    print(f"\nThe wearable would route to: {chosen.name} "
          f"({metres/1000:.1f} km straight line)")

    # The question this test exists to answer. Photon orders by relevance
    # and the executor only ever sees the first `limit`, so a nearer
    # branch sitting outside that window is invisible to a distance sort
    # no matter how correct the sort is.
    if args.route:
        _route_to(origin, chosen)

    closest = min(hits, key=lambda h: haversine_m(origin, h.coordinate))
    if args.limit <= GEOCODE_CANDIDATE_LIMIT:
        print(
            f"\nClosest in THIS window: {closest.name} "
            f"({haversine_m(origin, closest.coordinate)/1000:.1f} km). "
            f"Re-run with --limit 50 — if something nearer appears, the "
            f"candidate limit is the bug, not the ranking."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
