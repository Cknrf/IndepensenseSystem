"""Unit tests for the guardian directory and number normalisation.

No network: `_fetch` is exercised by monkeypatching `requests.get`, the
same way `test_heartbeat.py` handles the internet probe.
"""
import json

import pytest
import requests

from indepensense.conftest import TEST_BACKEND_URL, make_credential
from indepensense.telemetry.guardians import (
    GuardianContact,
    GuardianDirectory,
    normalise_number,
)


# --- number normalisation ----------------------------------------------------

@pytest.mark.parametrize(
    "raw,expected",
    [
        # Already correct.
        ("+639171234567", "+639171234567"),
        # Local trunk-code form — what a Filipino guardian actually types.
        ("09171234567", "+639171234567"),
        # Human formatting from a web form.
        ("0917 123 4567", "+639171234567"),
        ("(0917) 123-4567", "+639171234567"),
        ("+63 917-123-4567", "+639171234567"),
        # National number with no trunk code and no plus.
        ("639171234567", "+639171234567"),
    ],
)
def test_normalise_accepts_real_world_formats(raw, expected):
    assert normalise_number(raw, "63") == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",             # empty column
        "   ",          # whitespace only
        "n/a",          # no digits at all
        "123",          # far too short to be a mobile number
        "0917123456789012345",   # too long for E.164
    ],
)
def test_normalise_rejects_unusable_values(raw):
    """A malformed row must be dropped here, not become a failed send
    during an emergency."""
    assert normalise_number(raw, "63") is None


# --- directory: cache behaviour ----------------------------------------------

def _payload(*numbers: str) -> dict:
    return {
        "guardians": [
            {"name": f"Guardian {i}", "contactNumber": n, "role": "parent"}
            for i, n in enumerate(numbers)
        ]
    }


def _directory(tmp_path, **kwargs) -> GuardianDirectory:
    return GuardianDirectory(
        base_url=TEST_BACKEND_URL,
        credential=make_credential(),
        cache_path=tmp_path / "guardians.json",
        **kwargs,
    )


def test_starts_empty_with_no_cache(tmp_path):
    assert _directory(tmp_path).contacts() == []


def test_refresh_populates_and_writes_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requests, "get", _fake_get(200, _payload("09171234567")),
    )
    directory = _directory(tmp_path)

    assert directory.refresh() is True
    assert directory.sms_numbers() == ["+639171234567"]

    written = json.loads((tmp_path / "guardians.json").read_text())
    assert written["guardians"][0]["contactNumber"] == "09171234567"


def test_cache_is_loaded_on_construction(tmp_path, monkeypatch):
    """The whole point of the cache: a device that boots with no network
    still knows who to text."""
    monkeypatch.setattr(requests, "get", _fake_get(200, _payload("09171234567")))
    _directory(tmp_path).refresh()

    # A fresh directory, network now dead.
    monkeypatch.setattr(requests, "get", _raising_get)
    revived = _directory(tmp_path)
    assert revived.sms_numbers() == ["+639171234567"]
    assert revived.refresh() is False
    # Failed refresh must not wipe what we had.
    assert revived.sms_numbers() == ["+639171234567"]


def test_failed_refresh_keeps_previous_list(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get(200, _payload("09171234567")))
    directory = _directory(tmp_path)
    directory.refresh()

    monkeypatch.setattr(requests, "get", _fake_get(500, {"error": "boom"}))
    assert directory.refresh() is False
    assert directory.sms_numbers() == ["+639171234567"]


def test_corrupt_cache_is_ignored_not_fatal(tmp_path):
    """A bad cache file degrades SMS until the next refresh; it must never
    stop the device from booting."""
    cache = tmp_path / "guardians.json"
    cache.write_text("{not json at all")
    assert _directory(tmp_path).contacts() == []


# --- directory: parsing ------------------------------------------------------

def test_rows_without_a_number_are_dropped(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requests,
        "get",
        _fake_get(200, {"guardians": [
            {"name": "No Phone", "contactNumber": "", "role": "sibling"},
            {"name": "Has Phone", "contactNumber": "09171234567", "role": "parent"},
        ]}),
    )
    directory = _directory(tmp_path)
    directory.refresh()
    assert [c.name for c in directory.contacts()] == ["Has Phone"]


def test_duplicate_numbers_are_sent_once(tmp_path, monkeypatch):
    """Two guardians can share a phone. Texting it twice is a cost with no
    benefit, and looks like a bug to whoever receives it."""
    monkeypatch.setattr(
        requests, "get", _fake_get(200, _payload("09171234567", "0917 123 4567")),
    )
    directory = _directory(tmp_path)
    directory.refresh()
    assert directory.sms_numbers() == ["+639171234567"]


def test_unusable_number_does_not_hide_the_good_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(
        requests, "get", _fake_get(200, _payload("n/a", "09171234567")),
    )
    directory = _directory(tmp_path)
    directory.refresh()
    assert directory.sms_numbers() == ["+639171234567"]


def test_malformed_response_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(requests, "get", _fake_get(200, {"unexpected": "shape"}))
    directory = _directory(tmp_path)
    assert directory.refresh() is False


def test_contacts_are_a_copy(tmp_path, monkeypatch):
    """Callers must not be able to mutate the directory's own list."""
    monkeypatch.setattr(requests, "get", _fake_get(200, _payload("09171234567")))
    directory = _directory(tmp_path)
    directory.refresh()

    contacts = directory.contacts()
    contacts.append(GuardianContact("Intruder", "+639000000000"))
    assert len(directory.contacts()) == 1


# --- helpers -----------------------------------------------------------------

def _fake_get(status_code: int, payload: dict):
    def _get(url, **kwargs):
        response = requests.Response()
        response.status_code = status_code
        response._content = json.dumps(payload).encode()
        response.headers["Content-Type"] = "application/json"
        return response

    return _get


def _raising_get(url, **kwargs):
    raise requests.ConnectionError("simulated dead network")
