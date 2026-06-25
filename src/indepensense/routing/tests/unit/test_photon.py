from indepensense.routing.base import Coordinate
from indepensense.routing.photon import parse_photon_response


_SAMPLE_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "geometry": {"type": "Point", "coordinates": [120.9842, 14.5995]},
            "properties": {
                "name": "Manila",
                "country": "Philippines",
                "city": "Manila",
                "osm_value": "city",
            },
        },
        {
            "geometry": {"type": "Point", "coordinates": [121.1622, 13.9411]},
            "properties": {
                "name": "Lipa City",
                "country": "Philippines",
                "osm_value": "city",
            },
        },
    ],
}


def test_parses_each_feature():
    results = parse_photon_response(_SAMPLE_RESPONSE)
    assert len(results) == 2


def test_flips_geojson_lon_lat_to_lat_lon():
    results = parse_photon_response(_SAMPLE_RESPONSE)
    assert results[0].coordinate == Coordinate(lat=14.5995, lon=120.9842)


def test_propagates_properties():
    results = parse_photon_response(_SAMPLE_RESPONSE)
    assert results[0].name == "Manila"
    assert results[0].country == "Philippines"
    assert results[0].city == "Manila"
    assert results[0].feature_type == "city"


def test_missing_city_becomes_none():
    results = parse_photon_response(_SAMPLE_RESPONSE)
    assert results[1].city is None


def test_empty_feature_collection_returns_empty_list():
    assert parse_photon_response({"features": []}) == []
    assert parse_photon_response({}) == []
