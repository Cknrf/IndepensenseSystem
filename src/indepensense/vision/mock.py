"""Mocks for the camera, object detector and OCR.

Lets `vision.describe` and `vision.read` be exercised on a Mac with no
camera, no YOLO weights and no Tesseract binary installed.

`MockDetector` and `MockOCR` return scripted results and never look at
pixel data, so `MockCamera` does not need to synthesize a real image.
numpy is used when it happens to be installed (it arrives as a
`faster-whisper` dependency) so that any consumer which *does* touch
`frame.image` gets a valid array; otherwise the field is None. Nothing in
the runtime reads it today — the detector and OCR drivers are the only
consumers and both are mocked here.
"""
import time

from indepensense.vision.base import Detection, Frame


def _blank_image(width: int, height: int):
    """A black frame if numpy is available, else None. See module docstring."""
    try:
        import numpy as np  # lazy: optional here, unlike in the real drivers
    except ImportError:
        return None
    return np.zeros((height, width, 3), dtype=np.uint8)


class MockCamera:
    """Camera returning blank frames at a fixed resolution.

    `capture_count` records how many frames were taken, so a test can
    assert that a code path really did reach for the camera.
    """

    def __init__(self, width: int = 1280, height: int = 720):
        self._width = width
        self._height = height
        self.capture_count = 0
        self.closed = False

    def capture(self) -> Frame:
        self.capture_count += 1
        return Frame(
            image=_blank_image(self._width, self._height),
            timestamp=time.time(),
            width=self._width,
            height=self._height,
        )

    def close(self) -> None:
        self.closed = True


class MockDetector:
    """Detector returning a fixed set of detections.

    Defaults to a small scene — one person ahead and a chair to the side —
    chosen so `vision.describe` produces a non-trivial sentence with more
    than one object and can exercise any grouping or ordering logic. Pass
    `detections=[]` to simulate an empty scene.
    """

    def __init__(self, detections: list[Detection] | None = None):
        if detections is None:
            detections = [
                Detection(class_name="person", confidence=0.91, bbox=(520, 180, 760, 700)),
                Detection(class_name="chair", confidence=0.68, bbox=(120, 400, 330, 690)),
            ]
        self._detections = detections
        self.detect_count = 0

    def detect(self, frame: Frame) -> list[Detection]:
        self.detect_count += 1
        return list(self._detections)


class MockOCR:
    """OCR returning canned text, with a per-language default.

    The real Tesseract driver takes an app-facing language code and maps it
    to an engine code, so the mock returns visibly different text per
    language — that way a language-switching bug shows up as the wrong
    string rather than as silence.
    """

    def __init__(self, text_by_language: dict[str, str] | None = None):
        if text_by_language is None:
            text_by_language = {
                "en": "EXIT — Emergency exit, keep clear",
                "tl": "LABASAN — Bawal harangan",
            }
        self._text_by_language = text_by_language
        self.read_count = 0
        self.closed = False

    def read_text(self, frame: Frame, language: str = "en") -> str:
        self.read_count += 1
        return self._text_by_language.get(language, "")

    def close(self) -> None:
        self.closed = True
