"""Unit tests for building the gazetteer from a Photon dump.

The dump is fed as in-memory JSONL lines in the shape Photon 1.x
writes; no file is downloaded.
"""
import io
import json

from indepensense.tools import build_gazetteer
from indepensense.tools.build_gazetteer import place_names, render


def _place(name: str | None, state: str | None) -> str:
    place: dict = {"osm_key": "place", "osm_value": "village"}
    if name is not None:
        place["name"] = {"name": name, "alt_name": f"{name} alt"}
    if state is not None:
        place["address"] = {"state": state, "city": "Somewhere"}
    return json.dumps({"type": "Place", "content": [place]})


HEADER = json.dumps({
    "type": "NominatimDumpFile",
    "content": {"data_timestamp": "2026-10-10T22:59:51.000+00:00"},
})
COUNTRY = json.dumps({"type": "CountryInfo", "content": [{"country_code": "ph"}]})


def test_only_places_in_the_province_are_kept():
    names, _ = place_names(
        [HEADER, COUNTRY, _place("Sambat", "Batangas"), _place("Sariaya", "Quezon")],
        "Batangas",
    )

    assert names == {"Sambat"}


def test_nameless_and_addressless_places_are_skipped():
    names, _ = place_names(
        [_place(None, "Batangas"), _place("Floating", None), _place("  ", "Batangas")],
        "Batangas",
    )

    assert names == set()


def test_only_the_primary_name_is_taken():
    names, _ = place_names([_place("Sambat", "Batangas")], "Batangas")

    assert "Sambat alt" not in names


def test_the_dump_timestamp_is_reported():
    _, timestamp = place_names([HEADER], "Batangas")

    assert timestamp == "2026-10-10T22:59:51.000+00:00"


def test_render_writes_a_header_then_sorted_names():
    text = render({"Sabang", "Bauan"}, "Batangas", "2026-10-10")
    lines = text.splitlines()

    assert all(line.startswith("# ") for line in lines[:3])
    assert "2026-10-10" in lines[1]
    assert lines[3:] == ["Bauan", "Sabang"]


def test_main_writes_the_list(tmp_path, monkeypatch):
    out = tmp_path / "gazetteer" / "batangas.txt"
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("\n".join([HEADER, _place("Sambat", "Batangas")]) + "\n"),
    )

    assert build_gazetteer.main(["--province", "Batangas", "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8").splitlines()[-1] == "Sambat"


def test_main_refuses_to_write_an_empty_list(tmp_path, monkeypatch):
    """A misspelt province would otherwise load cleanly and correct nothing."""
    out = tmp_path / "batangas.txt"
    monkeypatch.setattr("sys.stdin", io.StringIO(_place("Sambat", "Batangas") + "\n"))

    assert build_gazetteer.main(["--province", "Batanggas", "--out", str(out)]) == 1
    assert not out.exists()
