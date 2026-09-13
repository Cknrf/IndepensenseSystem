"""Unit tests for the saved-places store.

Real files in `tmp_path` — the persistence is the point, and mocking the
filesystem would test nothing. No network: a saved place never touches
the geocoder, which is much of why the feature exists.
"""
import json

import pytest

from indepensense.routing.base import Coordinate
from indepensense.routing.places import SavedPlaces

LIPA = Coordinate(lat=13.9411, lon=121.1622)
MANILA = Coordinate(lat=14.5995, lon=120.9842)


@pytest.fixture
def places(tmp_path):
    return SavedPlaces(tmp_path / "places.json")


# --- saving and finding ------------------------------------------------------

def test_a_saved_place_can_be_found_again(places):
    places.save("home", LIPA)

    found = places.find("home")
    assert found is not None
    assert found.coordinate == LIPA


def test_a_missing_place_is_none(places):
    assert places.find("home") is None


def test_lookup_ignores_case_and_punctuation(places):
    """Whisper's capitalisation and apostrophes vary run to run. A place
    the user cannot reach because of a transcription detail is the same as
    one that was never saved."""
    places.save("Mom's House", LIPA)

    assert places.find("moms house") is not None
    assert places.find("MOM'S HOUSE") is not None


def test_the_spoken_label_is_preserved(places):
    """Matching folds the label; speaking it back must not. "moms house"
    read aloud is not what the user said."""
    places.save("My Sister's House", LIPA)

    assert places.find("my sisters house").label == "My Sister's House"


def test_saving_a_new_label_reports_no_replacement(places):
    assert places.save("home", LIPA) is False


def test_saving_an_existing_label_replaces_and_says_so(places):
    """People move house. The return value is the only signal the user
    gets that they overwrote something."""
    places.save("home", LIPA)

    assert places.save("home", MANILA) is True
    assert places.find("home").coordinate == MANILA


def test_an_empty_label_is_rejected(places):
    assert places.save("", LIPA) is False
    assert len(places) == 0


def test_a_label_of_only_punctuation_is_rejected(places):
    """Normalises to nothing, so it could never be looked up again."""
    assert places.save("!!!", LIPA) is False
    assert len(places) == 0


def test_finding_with_an_empty_label_is_none(places):
    places.save("home", LIPA)
    assert places.find("") is None


# --- deleting ----------------------------------------------------------------

def test_a_place_can_be_forgotten(places):
    """A user who saved "home" at the wrong corner has no file to edit and
    no screen to tap. Without this, the mistake is permanent."""
    places.save("home", LIPA)

    assert places.delete("home") is True
    assert places.find("home") is None


def test_forgetting_something_unsaved_reports_false(places):
    assert places.delete("home") is False


def test_deleting_ignores_case_and_punctuation(places):
    places.save("Mom's House", LIPA)
    assert places.delete("moms house") is True


# --- persistence -------------------------------------------------------------

def test_places_survive_a_restart(tmp_path):
    """The whole point — a list that vanished on reboot would be worse
    than none, because the user would trust it."""
    path = tmp_path / "places.json"
    SavedPlaces(path).save("home", LIPA)

    reopened = SavedPlaces(path)

    assert reopened.find("home").coordinate == LIPA


def test_deletions_survive_a_restart(tmp_path):
    path = tmp_path / "places.json"
    first = SavedPlaces(path)
    first.save("home", LIPA)
    first.delete("home")

    assert SavedPlaces(path).find("home") is None


def test_no_file_yet_is_not_an_error(tmp_path):
    """First boot."""
    assert len(SavedPlaces(tmp_path / "nothing-here.json")) == 0


def test_the_file_is_written_atomically(tmp_path):
    """This device loses power without warning. A half-written file would
    take every saved place with it, so the write lands via a temp file and
    a rename — no `.tmp` should survive a successful save."""
    path = tmp_path / "places.json"
    SavedPlaces(path).save("home", LIPA)

    assert path.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_the_file_is_readable_json(tmp_path):
    """Not a private format: someone debugging on the Pi should be able to
    read it, and the thesis may need to show it."""
    path = tmp_path / "places.json"
    SavedPlaces(path).save("home", LIPA)

    payload = json.loads(path.read_text())
    assert payload["home"]["lat"] == LIPA.lat
    assert payload["home"]["label"] == "home"
    assert payload["home"]["saved_at"]


def test_a_corrupt_file_degrades_to_empty(tmp_path):
    """Refusing to start would take down navigation, fall detection and
    everything else over a list of shortcuts."""
    path = tmp_path / "places.json"
    path.write_text("{ this is not json")

    assert len(SavedPlaces(path)) == 0


def test_a_file_that_is_not_an_object_degrades_to_empty(tmp_path):
    path = tmp_path / "places.json"
    path.write_text('["home"]')

    assert len(SavedPlaces(path)) == 0


def test_one_malformed_entry_does_not_discard_the_others(tmp_path):
    """The good ones are still somewhere the user needs to get to."""
    path = tmp_path / "places.json"
    path.write_text(json.dumps({
        "home": {"label": "home", "lat": 13.9411, "lon": 121.1622},
        "broken": {"label": "broken"},              # no coordinates
    }))

    places = SavedPlaces(path)

    assert places.find("home") is not None
    assert places.find("broken") is None


def test_labels_lists_what_was_saved(tmp_path):
    places = SavedPlaces(tmp_path / "places.json")
    places.save("work", LIPA)
    places.save("home", MANILA)

    assert places.labels() == ["home", "work"]
