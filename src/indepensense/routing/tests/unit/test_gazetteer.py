"""Unit tests for correcting misheard destinations against known names.

Small hand-made lists rather than the committed Batangas file, so each
test shows exactly which neighbours a correction had to beat.
"""
import pytest

from indepensense.routing.gazetteer import Gazetteer

NAMES = ["Sambat", "Sabang", "Bauan", "Lipa City", "SM City Lipa", "Tanauan", "Tanagan"]


@pytest.fixture
def gazetteer():
    return Gazetteer(NAMES, min_score=85)


# --- correcting --------------------------------------------------------------

def test_a_name_spelled_by_sound_is_corrected(gazetteer):
    correction = gazetteer.correct("Sambaht")

    assert correction is not None
    assert correction.name == "Sambat"
    assert correction.score >= 85


def test_a_name_split_into_two_words_is_corrected(gazetteer):
    """Whisper hears syllables, so it often breaks a name it does not know."""
    assert gazetteer.correct("Sam bat").name == "Sambat"


def test_a_multi_word_name_is_corrected(gazetteer):
    assert gazetteer.correct("SM City Leepa").name == "SM City Lipa"


def test_a_correct_name_returns_itself(gazetteer):
    """The caller tells "already right" from "corrected", not the gazetteer."""
    correction = gazetteer.correct("bauan")

    assert correction.name == "Bauan"
    assert correction.score == 100


def test_nothing_close_is_not_corrected(gazetteer):
    """The nearest name is only the least bad; below the cutoff it is no answer."""
    assert gazetteer.correct("kumusta ka") is None


def test_a_tie_between_two_names_is_not_corrected(gazetteer):
    """'tanawan' is equally far from Tanauan and Tanagan — that is a coin toss."""
    assert gazetteer.correct("tanawan") is None


def test_an_empty_or_punctuation_only_query_is_not_corrected(gazetteer):
    assert gazetteer.correct("") is None
    assert gazetteer.correct("?!") is None


def test_the_cutoff_is_honoured():
    strict = Gazetteer(["Lemery"], min_score=85)
    lenient = Gazetteer(["Lemery"], min_score=80)

    assert strict.correct("lemeri") is None          # scores 83
    assert lenient.correct("lemeri").name == "Lemery"


# --- loading -----------------------------------------------------------------

def test_names_differing_only_in_case_or_punctuation_count_once():
    gazetteer = Gazetteer(["JOLLIBEE", "Jollibee", "jollibee!"], min_score=85)

    assert len(gazetteer) == 1


def test_load_skips_the_header_but_keeps_a_name_starting_with_a_hash(tmp_path):
    path = tmp_path / "names.txt"
    path.write_text(
        "# Place names for the gazetteer.\n"
        "# Province: Batangas.\n"
        "#42\n"
        "Sambat\n"
        "\n",
        encoding="utf-8",
    )

    gazetteer = Gazetteer.load(path, min_score=85)

    assert len(gazetteer) == 2
    assert gazetteer.correct("42").name == "#42"


def test_load_raises_when_the_list_was_never_built(tmp_path):
    """The factory in `app.py` decides this is degraded, not fatal."""
    with pytest.raises(FileNotFoundError):
        Gazetteer.load(tmp_path / "missing.txt", min_score=85)
