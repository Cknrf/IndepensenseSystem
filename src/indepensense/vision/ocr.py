"""Tesseract-based OCR driver.

Wraps `pytesseract` (a thin Python binding around the tesseract-ocr
system binary). Chosen over EasyOCR / PaddleOCR because:

- Fast on Pi 5 (~1-2 s per sign-sized region)
- Zero heavy dependencies (~50 MB via apt, no PyTorch)
- Battle-tested for accessibility applications
- Offline — matches the rest of the wearable's on-device stack

Language support
----------------

Tesseract uses ISO-639 language codes (`eng`, `tgl`, ...) that don't
match our app-facing codes (`en`, `tl`). The driver takes a mapping
dict so the executor can pass its friendly code and get the right
Tesseract language pack under the hood.

The tesseract binary AND the required language packs must be
installed via apt:

    sudo apt install -y tesseract-ocr             # includes English
    sudo apt install -y tesseract-ocr-tgl         # Tagalog

If a mapped language pack is missing, `read_text` will raise a
`pytesseract.TesseractError`. Callers catch this and return a
graceful "I couldn't read the text" message.
"""
from indepensense.vision.base import Frame


class TesseractOCR:
    def __init__(self, language_map: dict[str, str]):
        """`language_map` is app_code → tesseract_code, e.g.
        `{"en": "eng", "tl": "tgl"}`. Callers pass their SYSTEM_LANGUAGE
        (or per-command language once we support runtime switching)
        and the driver picks the right Tesseract pack.
        """
        self._language_map = dict(language_map)

    def read_text(self, frame: Frame, language: str = "en") -> str:
        import pytesseract  # lazy: not on Mac by default

        tess_lang = self._language_map.get(language, "eng")
        # pytesseract accepts numpy arrays directly — it converts via
        # PIL under the hood. We pass frame.image straight in.
        text = pytesseract.image_to_string(frame.image, lang=tess_lang)
        return text.strip()

    def close(self) -> None:
        # Tesseract is stateless from our side. Nothing to release.
        pass


class MockOCR:
    """OCR mock for off-device development and unit tests.

    Configure with either a fixed `text` return value or a callable
    that produces one, so tests can simulate different scenarios
    (empty text, long paragraphs, non-ASCII, etc.).
    """

    def __init__(self, text: str = "sample text"):
        self._text = text
        self.calls: list[tuple[Frame, str]] = []

    def read_text(self, frame: Frame, language: str = "en") -> str:
        self.calls.append((frame, language))
        return self._text

    def close(self) -> None:
        pass
