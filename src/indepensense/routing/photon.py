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
        street=properties.get("street"),
        district=properties.get("district"),
        state=properties.get("state"),
    )


def parse_photon_response(payload: dict[str, Any]) -> list[GeocodingResult]:
    return [_parse_feature(feature) for feature in payload.get("features", [])]


class PhotonGeocoder:
    def __init__(self, base_url: str, timeout_s: float = _DEFAULT_TIMEOUT_S):
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def geocode(
        self,
        query: str,
        limit: int = 5,
        near: Coordinate | None = None,
    ) -> list[GeocodingResult]:
        import requests  # lazy

        params: dict[str, Any] = {"q": query, "limit": limit}
        if near is not None:
            # Photon's `location_bias_scale` runs 0.0-1.0. Default (~0.2)
            # is a very soft nudge — a 965 km Jollibee can still outrank
            # a local one if it happens to have marginally better text
            # match. On a wearable, "take me to Jollibee" almost always
            # means the nearest one, so we use 1.0 to make proximity
            # dominant. Named/unambiguous places (e.g. "SM Manila")
            # still win via text-match relevance.
            params["lat"] = near.lat
            params["lon"] = near.lon
            params["location_bias_scale"] = 1.0

        response = requests.get(
            f"{self._base_url}/api",
            params=params,
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
