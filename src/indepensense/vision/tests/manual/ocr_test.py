"""Manual hardware test: capture a frame and read printed text with Tesseract.

Run on a Raspberry Pi 5 with the camera connected to CAM/DISP 0 and
`tesseract-ocr` installed. See `vision/ocr.py` for the install commands —
in particular the Tagalog pack, which Debian Trixie does not ship and has
to be downloaded from upstream.

Point the camera at printed text — a door sign, a bus route board, a
receipt — and hold it roughly parallel to the page. Tesseract is sensitive
to skew and to low contrast, far more so than YOLO is.

Run from repo root with:
    python -m indepensense.vision.tests.manual.ocr_test
    python -m indepensense.vision.tests.manual.ocr_test --language tl
    python -m indepensense.vision.tests.manual.ocr_test --repeat 5 --interval 3

`--repeat` re-reads on an interval so the camera can be aimed while
watching the output — the quickest way to find the distance and angle that
actually work for a given sign.
"""
import argparse
import time

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    DEFAULT_LANGUAGE,
    OCR_LANGUAGES,
    OCR_MAX_CHARS,
)
from indepensense.vision.ocr import TesseractOCR
from indepensense.vision.picamera import PiCamera


def check_language_packs(language: str) -> None:
    """Report which Tesseract packs are installed before capturing anything.

    A missing pack raises only at `read_text`, and the runtime swallows that
    into a spoken "I couldn't read the text" — so on the device it looks
    identical to a blurry photo. Checking up front tells the two apart.
    """
    import pytesseract  # lazy: only resolvable on the Pi

    installed = set(pytesseract.get_languages(config=""))
    print(f"Tesseract packs installed: {', '.join(sorted(installed))}")
    for app_code, tess_code in sorted(OCR_LANGUAGES.items()):
        mark = "ok " if tess_code in installed else "MISSING"
        print(f"  {app_code} -> {tess_code}: {mark}")

    wanted = OCR_LANGUAGES.get(language, "eng")
    if wanted not in installed:
        print(
            f"\n  Pack '{wanted}' is not installed — reads will fail.\n"
            f"  See the install notes in src/indepensense/vision/ocr.py.\n"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--language", default=DEFAULT_LANGUAGE, choices=sorted(OCR_LANGUAGES),
        help="app-facing language code; mapped to a Tesseract pack by the driver",
    )
    parser.add_argument("--repeat", type=int, default=1, help="number of reads")
    parser.add_argument(
        "--interval", type=float, default=2.0, help="seconds between reads",
    )
    args = parser.parse_args()

    check_language_packs(args.language)

    ocr = TesseractOCR(language_map=OCR_LANGUAGES)
    camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)
    print(
        f"\nReading in '{args.language}' at {CAMERA_WIDTH}x{CAMERA_HEIGHT}, "
        f"{args.repeat} time(s). Point the camera at printed text."
    )
    try:
        for i in range(args.repeat):
            if i:
                time.sleep(args.interval)
            frame = camera.capture()
            t0 = time.time()
            try:
                text = ocr.read_text(frame, language=args.language)
            except Exception as exc:
                # Mirrors what the executor catches — most often a missing
                # language pack or a tesseract binary that isn't on PATH.
                print(f"read {i:2d}: FAILED — {type(exc).__name__}: {exc}")
                continue
            elapsed_ms = (time.time() - t0) * 1000

            if not text.strip():
                print(f"read {i:2d} ({elapsed_ms:5.0f} ms): no text found")
                continue

            over = " (would be truncated when spoken)" if len(text) > OCR_MAX_CHARS else ""
            print(f"read {i:2d} ({elapsed_ms:5.0f} ms): {len(text)} chars{over}")
            # Printed raw, line breaks and all — that layout is what the
            # executor's cleaner has to flatten before Piper reads it.
            for line in text.splitlines():
                print(f"    | {line}")
    finally:
        camera.close()
        ocr.close()
    print("Done.")


if __name__ == "__main__":
    main()
