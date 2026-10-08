"""YOLO object detector running an NCNN export directly — no ultralytics, no torch.

Why NCNN, and why without ultralytics
-------------------------------------
NCNN is the fastest CPU backend for nano YOLO models on the Pi 5 in both
Ultralytics' published benchmark (YOLO26n: 67 ms NCNN vs 299 ms PyTorch at
640) and our own measurements. Every ultralytics backend imports torch and
ultralytics' own stack even for an NCNN model, which measured +216 MB peak
RSS against +60 MB when the `ncnn` package is called directly. The price is
the ~60 lines below: letterboxing, decoding and NMS that ultralytics would
otherwise do. See docs/object-detection-research.md.

The model contract
------------------
A model directory as written by `YOLO(...).export(format="ncnn")`:

    model.ncnn.param   graph
    model.ncnn.bin     weights
    metadata.yaml      class names and input size

Input blob `in0` is RGB, float 0-1, `imgsz`×`imgsz`, letterboxed with grey
114 padding — the same preprocessing the model was trained with. Output blob
`out0` is (4 + num_classes, N): rows 0-3 are box centre x, centre y, width,
height in letterboxed input pixels; the remaining rows are per-class scores,
already passed through a sigmoid by the exported head. There is no
objectness row (YOLOv8 onwards) and no NMS in the graph — the default NCNN
export emits the raw head even for YOLO26, so NMS happens here.

Class names in `metadata.yaml` are the keys `intents/messages.py` speaks;
the model is trained with them, not mapped afterwards.
"""
from pathlib import Path

import numpy as np

from indepensense.vision.base import Detection, Frame

# Ultralytics' letterbox fill. A different grey shifts every padded pixel's
# activation away from what the model saw in training.
_PAD_VALUE = 114.0

# Matches ultralytics' default `iou=0.7`, so detections here match what
# `model.val()` scored during training.
_NMS_IOU = 0.7


def letterbox_geometry(width: int, height: int, size: int) -> tuple[float, int, int, int, int]:
    """Scale and padding that fit a `width`×`height` frame into a `size` square.

    Returns (scale, resized_w, resized_h, pad_left, pad_top). The ±0.1 split
    of an odd padding is ultralytics' own, so a box lands on the same pixel
    as in their pipeline.
    """
    scale = min(size / width, size / height)
    resized_w, resized_h = round(width * scale), round(height * scale)
    pad_left = round((size - resized_w) / 2 - 0.1)
    pad_top = round((size - resized_h) / 2 - 0.1)
    return scale, resized_w, resized_h, pad_left, pad_top


def decode(
    output: np.ndarray,
    threshold: float,
    scale: float,
    pad_left: int,
    pad_top: int,
    width: int,
    height: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Turn the raw (4 + C, N) head into boxes in source-frame pixels.

    Returns (boxes as x1 y1 x2 y2, scores, class ids), keeping only
    candidates whose best class score reaches `threshold`.
    """
    scores_all = output[4:]
    class_ids = scores_all.argmax(axis=0)
    scores = scores_all[class_ids, np.arange(scores_all.shape[1])]
    keep = scores >= threshold
    cx, cy, w, h = output[:4, keep]
    boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
    boxes -= (pad_left, pad_top, pad_left, pad_top)
    boxes /= scale
    boxes.clip(0, (width, height, width, height), out=boxes)
    return boxes, scores[keep], class_ids[keep]


def nms(boxes: np.ndarray, scores: np.ndarray, class_ids: np.ndarray, iou: float = _NMS_IOU) -> list[int]:
    """Class-aware greedy non-maximum suppression; returns kept indices, best first.

    Boxes of different classes never suppress each other: each class is
    shifted into its own region of the plane, which is the standard trick
    and the one ultralytics uses (`agnostic=False`).
    """
    if len(boxes) == 0:
        return []
    shifted = boxes + (class_ids * 10_000.0)[:, None]
    x1, y1, x2, y2 = shifted.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    kept = []
    while order.size:
        best, rest = order[0], order[1:]
        kept.append(int(best))
        ix1 = np.maximum(x1[best], x1[rest])
        iy1 = np.maximum(y1[best], y1[rest])
        ix2 = np.minimum(x2[best], x2[rest])
        iy2 = np.minimum(y2[best], y2[rest])
        inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
        overlap = inter / (areas[best] + areas[rest] - inter + 1e-9)
        order = rest[overlap <= iou]
    return kept


def read_metadata(model_dir: Path) -> tuple[list[str], int]:
    """Class names in index order, and the square input size, from the export."""
    import yaml  # lazy: a transformers dependency on the Pi, not needed to import this module

    meta = yaml.safe_load((model_dir / "metadata.yaml").read_text())
    names = meta["names"]
    return [names[i] for i in range(len(names))], int(meta["imgsz"][0])


class NCNNDetector:
    def __init__(self, model_dir: Path, confidence_threshold: float, num_threads: int):
        import ncnn  # lazy: only resolvable where the ncnn wheel is installed

        self._ncnn = ncnn
        self.names, self.imgsz = read_metadata(model_dir)
        self._threshold = confidence_threshold
        self._net = ncnn.Net()
        self._net.opt.num_threads = num_threads
        # ncnn's worker threads spin for 20 ms after each layer waiting for
        # more work. Inference here is one-shot, so that spinning buys
        # nothing and steals CPU from the 100 Hz main loop.
        self._net.opt.openmp_blocktime = 0
        self._net.load_param(str(model_dir / "model.ncnn.param"))
        self._net.load_model(str(model_dir / "model.ncnn.bin"))
        # First inference allocates every intermediate blob; pay that at
        # startup rather than on the user's first question.
        self._infer(np.zeros((self.imgsz, self.imgsz, 3), dtype=np.uint8))

    def _infer(self, bgr: np.ndarray) -> np.ndarray:
        """Letterbox a BGR frame into the input square and run the network."""
        ncnn = self._ncnn
        height, width = bgr.shape[:2]
        _, resized_w, resized_h, pad_left, pad_top = letterbox_geometry(width, height, self.imgsz)
        mat = ncnn.Mat.from_pixels_resize(
            np.ascontiguousarray(bgr), ncnn.Mat.PixelType.PIXEL_BGR2RGB,
            width, height, resized_w, resized_h,
        )
        mat = ncnn.copy_make_border(
            mat, pad_top, self.imgsz - resized_h - pad_top,
            pad_left, self.imgsz - resized_w - pad_left,
            ncnn.BorderType.BORDER_CONSTANT, _PAD_VALUE,
        )
        mat.substract_mean_normalize([], [1 / 255.0] * 3)
        extractor = self._net.create_extractor()
        extractor.input("in0", mat)
        _, out = extractor.extract("out0")
        return np.array(out)

    def detect(self, frame: Frame) -> list[Detection]:
        height, width = frame.image.shape[:2]
        output = self._infer(frame.image)
        scale, _, _, pad_left, pad_top = letterbox_geometry(width, height, self.imgsz)
        boxes, scores, class_ids = decode(output, self._threshold, scale, pad_left, pad_top, width, height)
        return [
            Detection(
                class_name=self.names[class_ids[i]],
                confidence=float(scores[i]),
                bbox=tuple(int(v) for v in boxes[i]),
            )
            for i in nms(boxes, scores, class_ids)
        ]
