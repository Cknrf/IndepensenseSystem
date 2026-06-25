"""Manual test: geocode -> route end-to-end against the Pi's services.

Assumes Photon (port 2322) and GraphHopper (port 8989) are running. From a
Mac, set GRAPHHOPPER_URL / PHOTON_URL in `indepensense.config` to point at
the Pi's IP (e.g. http://192.168.1.42:8989).

Run from repo root with:
    python -m indepensense.routing.tests.manual.end_to_end_test
"""
from indepensense.config import GRAPHHOPPER_URL, PHOTON_URL
from indepensense.routing.graphhopper import GraphHopperRouter
from indepensense.routing.photon import PhotonGeocoder

START_QUERY = "Rizal Park, Manila"
DESTINATION_QUERY = "Manila City Hall"


def main():
    geocoder = PhotonGeocoder(PHOTON_URL)
    router = GraphHopperRouter(GRAPHHOPPER_URL)

    print(f"Geocoding '{START_QUERY}'...")
    start_hits = geocoder.geocode(START_QUERY, limit=1)
    if not start_hits:
        print(f"No geocoding result for '{START_QUERY}'.")
        return
    start = start_hits[0]
    print(f"  -> {start.name} ({start.coordinate.lat:.5f}, {start.coordinate.lon:.5f})")

    print(f"Geocoding '{DESTINATION_QUERY}'...")
    dest_hits = geocoder.geocode(DESTINATION_QUERY, limit=1)
    if not dest_hits:
        print(f"No geocoding result for '{DESTINATION_QUERY}'.")
        return
    dest = dest_hits[0]
    print(f"  -> {dest.name} ({dest.coordinate.lat:.5f}, {dest.coordinate.lon:.5f})")

    print("Routing on foot...")
    route = router.route(start.coordinate, dest.coordinate, profile="foot")
    print(f"  distance: {route.distance_m:.0f} m")
    print(f"  duration: {route.duration_s:.0f} s")
    print(f"  steps:")
    for i, step in enumerate(route.instructions):
        street = f" on {step.street_name}" if step.street_name else ""
        print(f"    {i + 1:2d}. {step.text}{street} ({step.distance_m:.0f} m)")


if __name__ == "__main__":
    main()
