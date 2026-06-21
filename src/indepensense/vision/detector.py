"""YOLOv8 object detector using the ultralytics library.

`ultralytics` pulls in PyTorch as a transitive dependency (~700 MB on first
install). It is listed in `requirements-pi.txt` because, for now, detection
only runs on the Pi.
"""
from pathlib import Path

from indepensense.vision.base import Detection, Frame


class YOLOv8Detector:
    def __init__(self, model_path: Path, confidence_threshold: float = 0.5):
        from ultralytics import YOLO  # lazy: heavy import

        # On first run ultralytics downloads the weights to this path
        # (~6 MB for yolov8n). Subsequent runs load from disk.
        model_path.parent.mkdir(parents=True, exist_ok=True)
        self._model = YOLO(str(model_path))
        self._threshold = confidence_threshold

    def detect(self, frame: Frame) -> list[Detection]:
        results = self._model(frame.image, verbose=False)
        detections: list[Detection] = []
        for result in results:
            for box in result.boxes:
                confidence = float(box.conf[0])
                if confidence < self._threshold:
                    continue
                class_id = int(box.cls[0])
                class_name = self._model.names[class_id]
                xyxy = box.xyxy[0].tolist()
                bbox = (int(xyxy[0]), int(xyxy[1]), int(xyxy[2]), int(xyxy[3]))
                detections.append(
                    Detection(class_name=class_name, confidence=confidence, bbox=bbox)
                )
        return detections
