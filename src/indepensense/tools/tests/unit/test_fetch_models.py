"""Unit tests for the one-time model fetcher.

The downloads themselves need the Pi and the network, so what is tested
is everything around them: that the configuration is turned into the
right set of directories, that a directory already holding files is left
alone unless `--force`, and that `--dry-run` never reaches a fetch.
"""
import pytest

from indepensense.tools import fetch_models


@pytest.fixture
def configured(tmp_path, monkeypatch):
    """Point every config value the tool reads at a temp tree."""
    monkeypatch.setattr(fetch_models, "WHISPER_MODEL_DIR", tmp_path / "whisper")
    monkeypatch.setattr(fetch_models, "WHISPER_MODELS", {"en": "tiny", "tl": "small"})
    monkeypatch.setattr(fetch_models, "NLU_EMBEDDING_MODEL", "org/e5")
    monkeypatch.setattr(fetch_models, "NLU_EMBEDDING_MODEL_DIR", tmp_path / "embeddings" / "e5")
    monkeypatch.setattr(fetch_models, "MMS_VOICE_REPOS", {"tl": "org/mms-tgl"})
    monkeypatch.setattr(fetch_models, "MMS_VOICES", {"tl": tmp_path / "voices" / "mms-tgl"})
    return tmp_path


@pytest.fixture
def fetched(monkeypatch):
    """Replace both download paths with a recorder that creates a file."""
    calls = []

    def fake(label):
        def factory(*args):
            destination = args[-1]

            def fetch():
                calls.append(label)
                destination.mkdir(parents=True, exist_ok=True)
                (destination / "weights").write_text("x")
            return fetch
        return factory

    monkeypatch.setattr(fetch_models, "_whisper", fake("whisper"))
    monkeypatch.setattr(fetch_models, "_snapshot", fake("snapshot"))
    return calls


def test_every_configured_model_becomes_a_directory_under_models(configured):
    destinations = {t.label: t.destination for t in fetch_models.targets()}

    assert destinations["Whisper tiny"] == configured / "whisper" / "tiny"
    assert destinations["Whisper small"] == configured / "whisper" / "small"
    assert destinations["embedding model org/e5"] == configured / "embeddings" / "e5"
    assert destinations["MMS voice org/mms-tgl"] == configured / "voices" / "mms-tgl"


def test_two_languages_sharing_a_whisper_size_fetch_it_once(configured, monkeypatch):
    monkeypatch.setattr(fetch_models, "WHISPER_MODELS", {"en": "small", "tl": "small"})

    labels = [t.label for t in fetch_models.targets()]

    assert labels.count("Whisper small") == 1


def test_dry_run_fetches_nothing(configured, fetched):
    assert fetch_models.main(["--dry-run"]) == 0
    assert fetched == []


def test_everything_missing_is_fetched(configured, fetched):
    assert fetch_models.main([]) == 0

    assert sorted(fetched) == ["snapshot", "snapshot", "whisper", "whisper"]
    assert (configured / "whisper" / "small" / "weights").exists()


def test_a_directory_with_files_is_skipped_unless_forced(configured, fetched):
    present = configured / "whisper" / "tiny"
    present.mkdir(parents=True)
    (present / "model.bin").write_text("already here")

    fetch_models.main([])
    assert fetched.count("whisper") == 1, "the present model was fetched again"

    fetched.clear()
    fetch_models.main(["--force"])
    assert fetched.count("whisper") == 2


def test_an_empty_directory_counts_as_missing(configured, fetched):
    (configured / "whisper" / "tiny").mkdir(parents=True)

    fetch_models.main([])

    assert fetched.count("whisper") == 2


def test_one_failure_does_not_stop_the_rest(configured, fetched, monkeypatch):
    def broken(*args):
        def fetch():
            raise OSError("hub unreachable")
        return fetch
    monkeypatch.setattr(fetch_models, "_whisper", broken)

    assert fetch_models.main([]) == 1
    assert fetched == ["snapshot", "snapshot"]
