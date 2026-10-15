"""Unit tests for correcting a misheard destination before routing.

The geocoder here answers per query, so each test can say what Photon
returns for the transcript as heard and for the corrected name, and
assert which of the two the executor walked the user to.
"""
import time

from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor
from indepensense.routing.base import Coordinate, GeocodingResult
from indepensense.routing.gazetteer import Gazetteer
from indepensense.routing.mock import MockRouter
from indepensense.sensors.base import GPSFix


class _StaticGPS:
    def read(self) -> GPSFix:
        return GPSFix(
            lat=13.7565, lon=121.0583, altitude_m=15.0, speed_knots=0.0,
            course_deg=None, satellites=8, hdop=1.2, fix_quality=1,
            utc_time=None, timestamp=time.time(),
        )

    def close(self) -> None:
        pass


class _ScriptedGeocoder:
    """Returns candidates per query; records every query it was asked."""

    def __init__(self, answers: dict[str, list[GeocodingResult]]):
        self._answers = answers
        self.queries: list[str] = []

    def geocode(self, query, limit=5, near=None):
        self.queries.append(query)
        return list(self._answers.get(query, []))

    def reverse(self, coordinate):
        return None


def _place(name: str, lat: float = 13.76, lon: float = 121.06) -> GeocodingResult:
    return GeocodingResult(
        name=name, coordinate=Coordinate(lat=lat, lon=lon),
        country="Philippines", city=None, feature_type="village",
    )


SAMBAT = _place("Sambat")
UNRELATED = _place("Sambal Elementary School", lat=13.9, lon=121.2)


def _executor(geocoder, gazetteer=True):
    confirmed: list[str] = []
    executor = IntentExecutor(
        router=MockRouter(),
        geocoder=geocoder,
        gps=_StaticGPS(),
        gazetteer=Gazetteer(["Sambat", "Sabang", "Bauan"], min_score=85) if gazetteer else None,
        confirmer=lambda question: confirmed.append(question) or True,
    )
    return executor, confirmed


def _navigate(executor, location, nearest=False):
    return executor.execute(IntentResult(
        Intent.NAVIGATION_START, {"location": location, "nearest": nearest},
    ))


def test_a_transcript_photon_matches_is_not_corrected():
    geocoder = _ScriptedGeocoder({"Bauan": [_place("Bauan")]})
    executor, _ = _executor(geocoder)

    _navigate(executor, "Bauan")

    assert geocoder.queries == ["Bauan"]


def test_a_misheard_name_photon_cannot_find_is_corrected():
    geocoder = _ScriptedGeocoder({"Sambat": [SAMBAT]})
    executor, confirmed = _executor(geocoder)

    response = _navigate(executor, "Sambaht")

    assert geocoder.queries == ["Sambaht", "Sambat"]
    assert "Sambat" in confirmed[0]
    assert "Sambat" in response


def test_a_misheard_name_photon_matched_to_something_else_is_corrected():
    """Photon found *a* place, but not one containing what was said."""
    geocoder = _ScriptedGeocoder({"Sambaht": [UNRELATED], "Sambat": [SAMBAT]})
    executor, confirmed = _executor(geocoder)

    _navigate(executor, "Sambaht")

    assert "Sambat" in confirmed[0]
    assert "Sambal" not in confirmed[0]


def test_nearest_queries_are_never_corrected():
    """'hospital' missing from every result's name is normal for a category."""
    geocoder = _ScriptedGeocoder({"sabang": [_place("Batangas Medical Center")]})
    executor, confirmed = _executor(geocoder)

    _navigate(executor, "sabang", nearest=True)

    assert geocoder.queries == ["sabang"]
    assert "Batangas Medical Center" in confirmed[0]


def test_with_nothing_close_the_transcript_result_is_kept():
    geocoder = _ScriptedGeocoder({"Kumusta Ka": [UNRELATED]})
    executor, confirmed = _executor(geocoder)

    _navigate(executor, "Kumusta Ka")

    assert geocoder.queries == ["Kumusta Ka"]
    assert "Sambal" in confirmed[0]


def test_a_correction_photon_cannot_find_falls_back_to_the_transcript_result():
    geocoder = _ScriptedGeocoder({"Sambaht": [UNRELATED]})
    executor, confirmed = _executor(geocoder)

    _navigate(executor, "Sambaht")

    assert geocoder.queries == ["Sambaht", "Sambat"]
    assert "Sambal" in confirmed[0]


def test_a_name_already_on_the_list_is_not_geocoded_twice():
    """Photon missing an exact list name is not a mishearing to correct."""
    geocoder = _ScriptedGeocoder({"sambat": [UNRELATED]})
    executor, _ = _executor(geocoder)

    _navigate(executor, "sambat")

    assert geocoder.queries == ["sambat"]


def test_nothing_found_either_way_says_the_place_was_not_found():
    geocoder = _ScriptedGeocoder({})
    executor, confirmed = _executor(geocoder)

    response = _navigate(executor, "Sambaht")

    assert confirmed == []
    assert "Sambaht" in response


def test_without_a_gazetteer_the_transcript_is_geocoded_as_heard():
    geocoder = _ScriptedGeocoder({"Sambat": [SAMBAT]})
    executor, confirmed = _executor(geocoder, gazetteer=False)

    _navigate(executor, "Sambaht")

    assert geocoder.queries == ["Sambaht"]
    assert confirmed == []
