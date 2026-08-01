"""Live camera + YOLO preview with bounding boxes.

Opens a window on the Pi's monitor showing the camera feed with
real-time detection boxes drawn on top. Great for testing detection
quality visually — you can move objects around and immediately see
what YOLO recognizes.

Run this DIRECTLY ON THE PI (not over SSH unless you use `ssh -X`
for X11 forwarding). The Pi's graphical desktop session must be
active — cv2.imshow needs a display server.

Prerequisites:
    pip install opencv-python           # the GUI variant, not the -headless one
    # (ultralytics often installs opencv-python-headless, which has no GUI —
    #  if you get a NULL/GUI error, install opencv-python explicitly)

Run from repo root:
    python -m indepensense.vision.tests.manual.live_detect_test

Controls:
    q — quit
"""
import time

from indepensense.config import (
    CAMERA_FPS,
    CAMERA_HEIGHT,
    CAMERA_WIDTH,
    YOLO_CONFIDENCE_THRESHOLD,
    YOLO_MODEL_PATH,
)
from indepensense.vision.detector import YOLOv8Detector
from indepensense.vision.picamera import PiCamera


# Box + text colors (BGR order for OpenCV).
_BOX_COLOR = (0, 255, 0)         # bright green
_LABEL_TEXT_COLOR = (0, 0, 0)    # black text on the label background
_STATS_COLOR = (0, 255, 255)     # yellow overlay in the corner


def main():
    import cv2   # opencv-python (with GUI). Lazy import so tests still parse on machines without it.

    print(f"Loading YOLOv8 model from {YOLO_MODEL_PATH}...")
    detector = YOLOv8Detector(
        model_path=YOLO_MODEL_PATH,
        confidence_threshold=YOLO_CONFIDENCE_THRESHOLD,
    )

    print(f"Opening camera at {CAMERA_WIDTH}x{CAMERA_HEIGHT}...")
    camera = PiCamera(width=CAMERA_WIDTH, height=CAMERA_HEIGHT, fps=CAMERA_FPS)

    print("Live detection running. Press 'q' in the window to quit.")

    window_name = "IndepenSense - YOLO Live Detection"
    cv2.namedWindow(window_name, cv2.WINDOW_AUTOSIZE)

    frame_count = 0
    total_inference_s = 0.0

    try:
        while True:
            frame = camera.capture()

            # Run detection on the raw frame.
            t0 = time.time()
            detections = detector.detect(frame)
            inference_ms = (time.time() - t0) * 1000
            frame_count += 1
            total_inference_s += inference_ms / 1000.0

            # Copy so we don't mutate the source array.
            display = frame.image.copy()

            # Draw each detection: box + filled label background + text.
            for det in detections:
                x1, y1, x2, y2 = det.bbox

                # Bounding box.
                cv2.rectangle(display, (x1, y1), (x2, y2), _BOX_COLOR, 2)

                # Label: "class_name 0.87" — filled background for legibility.
                label = f"{det.class_name} {det.confidence:.2f}"
                (text_w, text_h), _baseline = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1,
                )
                cv2.rectangle(
                    display,
                    (x1, y1 - text_h - 4),
                    (x1 + text_w + 2, y1),
                    _BOX_COLOR,
                    thickness=-1,   # filled
                )
                cv2.putText(
                    display, label,
                    (x1 + 1, y1 - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    _LABEL_TEXT_COLOR, 1,
                )

            # Corner overlay: object count + inference time + rolling FPS.
            avg_ms = (total_inference_s / frame_count) * 1000 if frame_count else 0
            stats_line1 = f"{len(detections)} objects  |  {inference_ms:.0f} ms"
            stats_line2 = f"avg {avg_ms:.0f} ms  |  ~{1000 / avg_ms:.1f} FPS" if avg_ms else "warming up..."
            cv2.putText(display, stats_line1, (10, 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, _STATS_COLOR, 2)
            cv2.putText(display, stats_line2, (10, 44),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, _STATS_COLOR, 2)

            cv2.imshow(window_name, display)

            # cv2.waitKey returns the pressed key code, or -1 if nothing.
            # Mask with 0xFF because on some systems the key code has upper bits set.
            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    finally:
        camera.close()
        cv2.destroyAllWindows()

    print(f"Stopped. Ran {frame_count} frames, avg inference {avg_ms:.0f} ms.")


if __name__ == "__main__":
    main()
