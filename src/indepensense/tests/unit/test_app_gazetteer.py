"""Unit tests for opening the gazetteer in `app.py`.

Its absence must cost the user corrections, never the device: the
factory runs in `start()`, beside fall detection.
"""
import indepensense.app as app_module
from indepensense.app_mock import MockApp


def test_a_missing_list_degrades_to_no_correction(tmp_path, monkeypatch):
    monkeypatch.setattr(app_module, "GAZETTEER_PATH", tmp_path / "missing.txt")

    assert MockApp()._try_open_gazetteer() is None


def test_a_built_list_is_loaded(tmp_path, monkeypatch):
    path = tmp_path / "batangas.txt"
    path.write_text("# header\nSambat\nBauan\n", encoding="utf-8")
    monkeypatch.setattr(app_module, "GAZETTEER_PATH", path)

    gazetteer = MockApp()._try_open_gazetteer()

    assert gazetteer is not None
    assert len(gazetteer) == 2


def test_the_committed_list_loads():
    """The file the Pi receives through rsync, not a fixture."""
    gazetteer = MockApp()._try_open_gazetteer()

    assert gazetteer is not None
    assert len(gazetteer) > 10_000
