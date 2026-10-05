"""Manual test: see exactly why the wearable chose the destination it did.

Field report: "take me to the nearest Jollibee" from Lipa routed 17 km.
The NLU was innocent — the log shows `nearest: True` parsed correctly —
and so is `rank_candidates`, which for a nearest query is a pure distance
sort and cannot pick a far candidate over a near one. That leaves only
one place for the bug: **a nearer branch was never in the candidate list
Photon returned.**

This prints that list, with distances, exactly as the executor sees it,
then shows how ranking orders it. Three things it distinguishes:

  * **Nearby branches absent at any limit** — the Photon index does not
    have them, or they are not named what the user said. No amount of
    ranking fixes that; the index or the query does.
  * **Nearby branches appear only at a higher `--limit`** — Photon
    returns its top N by *relevance*, and `config.GEOCODE_CANDIDATE_LIMIT`
    is 10. If the near one sits at rank 14, the executor never sees it
    and sorting the ten it did see by distance is just picking the
    closest of the wrong set.
  * **Nearby branches present and ranked first** — then the fault is
    somewhere else entirely, most likely a bad GPS fix at the time, and
    `--from` lets you re-run against the coordinates the device actually
    had.

Usage
-----

    # the failing case, from the fix the device had that day
    python -m indepensense.routing.tests.manual.geocode_probe \\
        "Jollibee" --from 13.937387,121.118698 --nearest

    # does a bigger candidate list contain a closer branch?
    python -m indepensense.routing.tests.manual.geocode_probe \\
        "Jollibee" --from 13.937387,121.118698 --nearest --limit 50

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
    print(f"  {'#':>2}  {'distance':>9}  {'name match':>10}  name / city")
    print("  " + "-" * 72)
    for index, hit in enumerate(hits, 1):
        metres = haversine_m(origin, hit.coordinate)
        distance = f"{metres/1000:.1f} km" if metres >= 1000 else f"{metres:.0f} m"
        city = hit.city or ""
        print(f"  {index:>2}  {distance:>9}  {name_match_score(query, hit.name):>10.2f}  "
              f"{hit.name}{f'  ({city})' if city else ''}")


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
