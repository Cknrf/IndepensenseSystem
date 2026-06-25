"""HTTP client for a local Photon geocoding service.

See `docs/photon.md` for the service setup. This module assumes a server
listening on `PHOTON_URL`.
"""
from typing import Any

from indepensense.routing.base import Coordinate, GeocodingResult

_DEFAULT_TIMEOUT_S = 5.0


def _parse_feature(feature: dict[str, Any]) -> GeocodingResult:
    """Parse one Photon GeoJSON Feature into a GeocodingResult."""
    lon, lat = feature["geometry"]["coordinates"]
    properties = feature.get("properties", {})
    return GeocodingResult(
        name=properties.get("name") or "",
        coordinate=Coordinate(lat=lat, lon=lon),
        country=properties.get("country"),
        city=properties.get("city"),
        feature_type=properties.get("osm_value") or properties.get("type"),
    )


def parse_photon_response(payload: dict[str, Any]) -> list[GeocodingResult]:
    return [_parse_feature(feature) for feature in payload.get("features", [])]


class PhotonGeocoder:
    def __init__(self, base_url: str, timeout_s: float = _DEFAULT_TIMEOUT_S):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def geocode(self, query: str, limit: int = 5) -> list[GeocodingResult]:
        import requests  # lazy

        response = requests.get(
            f"{self._base_url}/api",
            params={"q": query, "limit": limit},
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        return parse_photon_response(response.json())

    def reverse(self, coordinate: Coordinate) -> GeocodingResult | None:
        import requests  # lazy

        response = requests.get(
            f"{self._base_url}/reverse",
            params={"lat": coordinate.lat, "lon": coordinate.lon},
            timeout=self._timeout_s,
        )
        response.raise_for_status()
        results = parse_photon_response(response.json())
        return results[0] if results else None
