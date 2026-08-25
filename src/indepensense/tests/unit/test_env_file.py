"""Unit tests for the `.env` secrets loader.

Worth testing carefully because its failures are silent: a mangled key
does not raise, it produces a 401 hours later, or the cloud fallback
quietly reporting itself unconfigured.
"""
import os

import pytest

from indepensense.config import _load_env_file


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Never let a test leak a variable into the real process env."""
    for key in ("PROBE_KEY", "OTHER_KEY", "ALREADY_SET"):
        monkeypatch.delenv(key, raising=False)


def _write(tmp_path, text):
    path = tmp_path / ".env"
    path.write_text(text)
    return path


# --- the happy path ----------------------------------------------------------

def test_a_key_is_loaded(tmp_path):
    _load_env_file(_write(tmp_path, "PROBE_KEY=abc123\n"))
    assert os.environ["PROBE_KEY"] == "abc123"


def test_several_keys_are_loaded(tmp_path):
    _load_env_file(_write(tmp_path, "PROBE_KEY=one\nOTHER_KEY=two\n"))
    assert os.environ["PROBE_KEY"] == "one"
    assert os.environ["OTHER_KEY"] == "two"


def test_surrounding_whitespace_is_stripped(tmp_path):
    """A key pasted from a browser often arrives with stray spaces, and a
    trailing space in a bearer token produces a 401 that looks like a
    wrong key."""
    _load_env_file(_write(tmp_path, "  PROBE_KEY  =  abc123  \n"))
    assert os.environ["PROBE_KEY"] == "abc123"


@pytest.mark.parametrize("line", [
    'PROBE_KEY="abc123"',
    "PROBE_KEY='abc123'",
])
def test_quotes_are_stripped(tmp_path, line):
    _load_env_file(_write(tmp_path, line + "\n"))
    assert os.environ["PROBE_KEY"] == "abc123"


def test_a_value_containing_equals_is_kept_whole(tmp_path):
    """Base64 and JWT-ish secrets contain `=` padding. Splitting on the
    last separator instead of the first would truncate them."""
    _load_env_file(_write(tmp_path, "PROBE_KEY=abc==def=\n"))
    assert os.environ["PROBE_KEY"] == "abc==def="


# --- precedence --------------------------------------------------------------

def test_the_real_environment_wins(tmp_path, monkeypatch):
    """So `KEY=x python -m ...` still overrides for a single run without
    editing the file."""
    monkeypatch.setenv("PROBE_KEY", "from-environment")
    _load_env_file(_write(tmp_path, "PROBE_KEY=from-file\n"))
    assert os.environ["PROBE_KEY"] == "from-environment"


def test_other_keys_still_load_when_one_is_overridden(tmp_path, monkeypatch):
    monkeypatch.setenv("PROBE_KEY", "from-environment")
    _load_env_file(_write(tmp_path, "PROBE_KEY=from-file\nOTHER_KEY=from-file\n"))
    assert os.environ["PROBE_KEY"] == "from-environment"
    assert os.environ["OTHER_KEY"] == "from-file"


# --- ignored lines -----------------------------------------------------------

def test_comments_and_blank_lines_are_ignored(tmp_path):
    _load_env_file(_write(tmp_path, """
# a comment
   # an indented comment

PROBE_KEY=abc123

"""))
    assert os.environ["PROBE_KEY"] == "abc123"


def test_an_empty_value_is_loaded_as_empty(tmp_path):
    """`.env.example` ships `INDEPENSENSE_CLOUD_API_KEY=` with no value.
    That must read as "no key" rather than crashing — the runtime already
    treats empty as unconfigured and says so at startup."""
    _load_env_file(_write(tmp_path, "PROBE_KEY=\n"))
    assert os.environ["PROBE_KEY"] == ""


# --- degradation -------------------------------------------------------------

def test_a_missing_file_is_not_an_error(tmp_path):
    """Running without a cloud key is a supported configuration."""
    _load_env_file(tmp_path / "does-not-exist")


def test_an_unreadable_path_is_not_an_error(tmp_path):
    """A directory where the file should be — read raises OSError. A
    secrets problem must not stop a safety device from booting."""
    path = tmp_path / ".env"
    path.mkdir()
    _load_env_file(path)


def test_a_malformed_line_is_skipped_not_fatal(tmp_path):
    """A line with no `=` is a typo. Skip it and keep the good keys, so
    one bad line does not cost you the whole file."""
    _load_env_file(_write(tmp_path, "this line has no equals\nPROBE_KEY=abc123\n"))
    assert os.environ["PROBE_KEY"] == "abc123"


def test_a_line_with_no_key_is_skipped(tmp_path):
    _load_env_file(_write(tmp_path, "=orphan-value\nPROBE_KEY=abc123\n"))
    assert os.environ["PROBE_KEY"] == "abc123"
    assert "" not in os.environ
