from indepensense.routing.graphhopper import parse_graphhopper_response


_SAMPLE_RESPONSE = {
    "paths": [
        {
            "distance": 134.5,
            "time": 96000,
            "instructions": [
                {"text": "Head east on Rizal Park Rd", "distance": 50.0, "street_name": "Rizal Park Rd"},
                {"text": "Turn left onto Roxas Blvd", "distance": 80.0, "street_name": "Roxas Blvd"},
                {"text": "Arrive at destination", "distance": 0.0, "street_name": ""},
            ],
            "points": {
                "coordinates": [
                    [120.9842, 14.5995],
                    [120.9850, 14.6000],
                    [120.9860, 14.6010],
                ],
            },
        }
    ]
}


def test_parses_distance_and_duration():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    assert route.distance_m == 134.5
    assert route.duration_s == 96.0   # 96000 ms -> 96 s


def test_parses_all_instructions():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    assert len(route.instructions) == 3
    assert route.instructions[0].text == "Head east on Rizal Park Rd"
    assert route.instructions[0].street_name == "Rizal Park Rd"


def test_treats_empty_street_name_as_none():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    assert route.instructions[-1].street_name is None


def test_flips_geojson_lon_lat_to_lat_lon():
    route = parse_graphhopper_response(_SAMPLE_RESPONSE)
    # GeoJSON input was [120.9842, 14.5995]; we should expose (lat=14.5995, lon=120.9842)
    assert route.points[0].lat == 14.5995
    assert route.points[0].lon == 120.9842
