"""Unit tests for LanguageState — validation and reboot persistence."""
import pytest

from indepensense.language import LanguageState

SUPPORTED = ("en", "tl")


def _state(tmp_path, default="tl", **kwargs):
    return LanguageState(
        default=default,
        supported=SUPPORTED,
        state_path=tmp_path / "language",
        **kwargs,
    )


# --- construction ------------------------------------------------------------

def test_starts_at_the_default():
    assert LanguageState("tl", SUPPORTED).current == "tl"


def test_default_must_be_supported():
    """A typo here would leave the wearable with no usable voice, so fail
    loudly at construction rather than at the first spoken response."""
    with pytest.raises(ValueError):
        LanguageState("de", SUPPORTED)


def test_works_without_a_state_path():
    """Used by unit tests and by the executor's own fallback."""
    state = LanguageState("en", SUPPORTED)
    assert state.set("tl") is True
    assert state.current == "tl"


# --- switching ---------------------------------------------------------------

def test_switch_changes_current(tmp_path):
    state = _state(tmp_path)
    assert state.set("en") is True
    assert state.current == "en"


def test_switching_to_the_same_language_reports_no_change(tmp_path):
    """The executor uses this to say "I am already speaking English"
    instead of confirming a switch that did nothing."""
    state = _state(tmp_path, default="en")
    assert state.set("en") is False
    assert state.current == "en"


def test_unsupported_language_is_rejected(tmp_path):
    state = _state(tmp_path)
    assert state.set("de") is False
    assert state.current == "tl"


def test_is_supported(tmp_path):
    state = _state(tmp_path)
    assert state.is_supported("en") is True
    assert state.is_supported("de") is False


# --- persistence -------------------------------------------------------------

def test_choice_survives_a_restart(tmp_path):
    """A user who switched to English must not be greeted in Tagalog
    after a power cycle."""
    _state(tmp_path).set("en")
    assert _state(tmp_path).current == "en"


def test_unchanged_language_is_not_persisted(tmp_path):
    state = _state(tmp_path, default="tl")
    state.set("tl")
    assert not (tmp_path / "language").exists()


def test_stored_value_survives_surrounding_whitespace(tmp_path):
    (tmp_path / "language").write_text("  en \n")
    assert _state(tmp_path).current == "en"


def test_unsupported_stored_value_falls_back(tmp_path):
    """A stale file from before a language was removed, or a hand-edit
    typo. Falling back beats refusing to start."""
    (tmp_path / "language").write_text("de\n")
    assert _state(tmp_path, default="tl").current == "tl"


def test_unreadable_state_path_falls_back(tmp_path):
    """The path exists but is a directory — read raises OSError."""
    (tmp_path / "language").mkdir()
    assert _state(tmp_path, default="tl").current == "tl"


def test_unwritable_path_still_switches_for_this_session(tmp_path):
    """Persistence is best-effort. Losing the switch on reboot is
    acceptable; refusing to switch at all is not."""
    blocked = tmp_path / "blocked"
    blocked.write_text("i am a file, not a directory")
    state = LanguageState("tl", SUPPORTED, state_path=blocked / "language")
    assert state.set("en") is True
    assert state.current == "en"
