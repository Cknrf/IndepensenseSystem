"""Unit tests for the `vision.read` path: text cleaning and truncation.

Tesseract's raw output is laid out for the eye, not the ear — it carries
the source image's line breaks. Everything here is about what the user
actually *hears*, so the assertions are on the shape of the spoken string
(no stray newlines, paragraph pauses, a bounded length), not on wording,
which lives in `messages.py`.

The OCR engine itself is mocked. What Tesseract extracts can only be
judged on real hardware pointed at a real sign — that is
`vision/tests/manual/ocr_test.py`.
"""
import pytest

from indepensense.intents import messages
from indepensense.intents.base import Intent, IntentResult
from indepensense.intents.executor import IntentExecutor, _clean_ocr_text
from indepensense.language import LanguageState
from indepensense.routing.mock import MockGeocoder, MockRouter
from indepensense.vision.base import Frame
from indepensense.vision.mock import MockCamera, MockOCR

SUPPORTED = ("en", "tl")


def _executor(text: str = "sample text", language: str = "en", **kwargs):
    """An executor whose OCR returns `text` in every language."""
    return IntentExecutor(
        router=MockRouter(),
        geocoder=MockGeocoder(),
        language=LanguageState(language, SUPPORTED),
        camera=kwargs.pop("camera", MockCamera()),
        ocr=kwargs.pop("ocr", MockOCR({code: text for code in SUPPORTED})),
        **kwargs,
    )


def _read(executor) -> str:
    return executor.execute(IntentResult(Intent.VISION_READ))


class _RaisingCamera:
    def capture(self) -> Frame:
        raise RuntimeError("camera busy")

    def close(self) -> None:
        pass


class _RaisingOCR:
    """Stands in for `pytesseract.TesseractError` — raised for real when a
    language pack is missing, which is the documented Tagalog failure mode."""

    def read_text(self, frame: Frame, language: str = "en") -> str:
        raise RuntimeError("Failed loading language 'tgl'")

    def close(self) -> None:
        pass


# --- cleaning ----------------------------------------------------------------

def test_line_breaks_inside_a_paragraph_become_spaces():
    """A wrapped sign is one sentence to the ear. Left as newlines, Piper
    pauses mid-phrase as if each line were its own thought."""
    assert _clean_ocr_text("EMERGENCY\nEXIT\nKEEP CLEAR") == "EMERGENCY EXIT KEEP CLEAR"


def test_blank_line_becomes_a_full_stop():
    """A blank line is a real paragraph break in the source, so it earns a
    sentence boundary — that is the one pause worth keeping."""
    assert _clean_ocr_text("Platform 2\n\nTrains to Manila") == "Platform 2. Trains to Manila"


def test_runs_of_whitespace_collapse():
    """Tesseract pads columns with spaces and tabs to preserve layout."""
    assert _clean_ocr_text("Ticket    office\tupstairs") == "Ticket office upstairs"


def test_empty_paragraphs_are_dropped():
    """Three or more newlines must not produce an empty sentence — ". ."
    reads as a stutter."""
    assert _clean_ocr_text("Open\n\n\n\n9am") == "Open. 9am"


def test_surrounding_whitespace_is_stripped():
    assert _clean_ocr_text("\n\n  Closed  \n\n") == "Closed"


def test_empty_input_stays_empty():
    assert _clean_ocr_text("") == ""
    assert _clean_ocr_text("\n \n") == ""


def test_cleaning_is_applied_to_the_spoken_response():
    """The handler must run the cleaner — not just the helper being correct
    in isolation."""
    response = _read(_executor("BUS\nSTOP\n\nRoute 12"))
    assert response == "BUS STOP. Route 12"
    assert "\n" not in response


# --- truncation --------------------------------------------------------------

def test_long_text_is_truncated_with_a_spoken_marker():
    """A receipt or menu would otherwise be a minutes-long monologue the
    user cannot skip except by pressing repeat."""
    response = _read(_executor("x" * 900, ocr_max_chars=100))

    assert response.endswith(messages.get("vision.truncated_suffix", "en"))
    assert response.startswith("x" * 100)


def test_truncated_body_never_exceeds_the_limit():
    """The cap applies to the extracted text; the marker is added on top and
    is not counted against it."""
    suffix = messages.get("vision.truncated_suffix", "en")
    response = _read(_executor("word " * 200, ocr_max_chars=50))

    assert len(response.removesuffix(suffix)) <= 50


def test_text_at_the_limit_is_not_truncated():
    """Boundary: the check is `>`, so exactly the limit is spoken whole."""
    response = _read(_executor("y" * 40, ocr_max_chars=40))

    assert response == "y" * 40
    assert not response.endswith(messages.get("vision.truncated_suffix", "en"))


def test_truncation_marker_follows_the_active_language():
    """The marker is a spoken sentence like any other, so it is subject to
    the language switch — not pinned to the language at construction."""
    executor = _executor("z" * 300, language="tl", ocr_max_chars=20)

    assert _read(executor).endswith(messages.get("vision.truncated_suffix", "tl"))

    executor.execute(IntentResult(Intent.SYSTEM_LANGUAGE, {"language": "en"}))
    assert _read(executor).endswith(messages.get("vision.truncated_suffix", "en"))


def test_truncation_measures_the_cleaned_text():
    """Cleaning runs first, so the budget is spent on speech, not on the
    layout whitespace that gets thrown away."""
    raw = "a" * 30 + " \t     \n  " + "b" * 30      # 70 raw chars, 61 cleaned
    response = _read(_executor(raw, ocr_max_chars=61))

    assert response == "a" * 30 + " " + "b" * 30


# --- failure paths -----------------------------------------------------------

@pytest.mark.parametrize("missing", ["camera", "ocr"])
def test_missing_hardware_is_reported_not_crashed(missing):
    """Running on a Mac, or on a Pi where Tesseract failed to open, must
    still answer the user. `_try_open_ocr` is allowed to return None."""
    executor = _executor(**{missing: None})
    assert _read(executor) == messages.get("vision.camera_unavailable", "en")


def test_capture_failure_is_reported():
    assert _read(_executor(camera=_RaisingCamera())) == messages.get(
        "vision.capture_failed", "en",
    )


def test_ocr_failure_is_reported():
    """A missing Tagalog language pack raises inside pytesseract. The
    wearable says it could not read rather than dying on the user."""
    assert _read(_executor(ocr=_RaisingOCR())) == messages.get(
        "vision.read_failed", "en",
    )


@pytest.mark.parametrize("extracted", ["", "   ", "\n\n", " \t\n "])
def test_blank_extraction_says_there_is_no_text(extracted):
    """Pointing at a blank wall is not an error — it is an answer, and a
    different one from "I couldn't read it"."""
    assert _read(_executor(extracted)) == messages.get("vision.no_text", "en")


def test_reading_takes_a_fresh_frame_every_time():
    """Each read must capture; answering from a stale frame would describe
    whatever the user was pointing at a minute ago."""
    camera = MockCamera()
    executor = _executor("OPEN", camera=camera)

    _read(executor)
    _read(executor)

    assert camera.capture_count == 2
