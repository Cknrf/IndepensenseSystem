"""Per-class precision and recall of an NCNN detector on a labelled image set.

Measures the detector the wearable actually runs (`NCNNDetector`), not a
training-framework re-implementation of it, at the threshold the wearable
actually uses — which is what decides what the user hears. mAP from
`model.val()` summarises the whole precision-recall curve; this reports the
one operating point that ships, plus a sweep to choose it.

Input is a YOLO-format dataset described by an ultralytics data YAML
(`path`, `names`, and a key per split pointing at an images directory with
a sibling `labels` directory).

Matching: greedy by confidence, IoU >= 0.5, same class. Every class the
dataset labels is scored, including ones the model cannot name — a stock
COCO model gets recall 0 on `jeepney`, and the confusion column shows what
it said instead, which is the comparison a baseline exists for. A detection
of a class the dataset does not label is ignored rather than counted as a
false positive. Class names are compared lowercased with spaces as
underscores ("Traffic light" == "traffic_light"), so the previous Open
Images model can be scored on the same set.

Reported per class, at `--conf`:
  P, R            box level, with Wilson 95% intervals — small classes get
                  wide intervals and the table says so instead of hiding it
  spoken P, R     image level: did the class's name appear in what would be
                  said, when the class was / was not in the image
  confused as     for missed ground-truth boxes, the class of the best
                  overlapping detection of a *different* class — e.g. what
                  a COCO model calls a jeepney

Run from repo root (needs the `ncnn` wheel; runs on a Mac too):
    python -m indepensense.vision.tests.manual.detector_eval DATA.yaml --split test
    python -m indepensense.vision.tests.manual.detector_eval DATA.yaml --model models/yolo26n_ncnn_model --sweep
"""
import argparse
import collections
import math
import time
from pathlib import Path

import numpy as np

from indepensense.config import YOLO_CONFIDENCE_THRESHOLD, YOLO_MODEL_DIR
from indepensense.vision.base import Frame
from indepensense.vision.ncnn_detector import NCNNDetector

_IOU_MATCH = 0.5
_SWEEP = (0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6)


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion; (0, 1) when n is 0."""
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def load_split(data_yaml: Path, split: str):
    import yaml  # lazy: a transformers dependency on the Pi

    meta = yaml.safe_load(data_yaml.read_text())
    names = meta["names"]
    names = names if isinstance(names, list) else [names[i] for i in sorted(names)]
    root = Path(meta.get("path", data_yaml.parent))
    image_dir = root / meta[split]
    label_dir = Path(str(image_dir).replace("images", "labels"))
    return [_norm(n) for n in names], sorted(p for p in image_dir.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")), label_dir


def _norm(name: str) -> str:
    return name.replace(" ", "_").lower()


def ground_truth(label_file: Path, names: list[str], width: int, height: int):
    boxes = []
    if label_file.exists():
        for line in label_file.read_text().splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            c, cx, cy, w, h = int(parts[0]), *map(float, parts[1:])
            boxes.append((names[c], ((cx - w / 2) * width, (cy - h / 2) * height, (cx + w / 2) * width, (cy + h / 2) * height)))
    return boxes


def score(records, labelled: set[str], conf: float):
    """Box- and image-level counts per class at one threshold.

    `labelled` is every class the dataset annotates; detections outside it
    are dropped before matching, except as candidates for the confusion
    column.
    """
    box = collections.defaultdict(lambda: [0, 0, 0])      # tp, fp, fn
    image = collections.defaultdict(lambda: [0, 0, 0])    # tp, fp, fn
    confused = collections.defaultdict(collections.Counter)
    for truth, dets in records:
        above = [d for d in dets if d[1] >= conf]
        dets = sorted((d for d in above if d[0] in labelled), key=lambda d: -d[1])
        used = set()
        for name, _, bbox in dets:
            best, best_iou = None, _IOU_MATCH
            for j, (t_name, t_box) in enumerate(truth):
                if j not in used and t_name == name:
                    overlap = iou(bbox, t_box)
                    if overlap >= best_iou:
                        best, best_iou = j, overlap
            if best is None:
                box[name][1] += 1
            else:
                used.add(best)
                box[name][0] += 1
        for j, (t_name, t_box) in enumerate(truth):
            if j in used:
                continue
            box[t_name][2] += 1
            others = [(iou(b, t_box), n) for n, _, b in above if n != t_name]
            overlap, other = max(others, default=(0.0, None))
            confused[t_name][other if overlap >= _IOU_MATCH else "(nothing)"] += 1
        said, present = {d[0] for d in dets}, {t[0] for t in truth}
        for name in said | present:
            image[name][0 if (name in said and name in present) else 1 if name in said else 2] += 1
    return box, image, confused


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("data", type=Path, help="ultralytics data YAML")
    parser.add_argument("--split", default="val", help="key in the YAML naming the image directory")
    parser.add_argument("--model", type=Path, default=YOLO_MODEL_DIR, help="NCNN model directory")
    parser.add_argument("--conf", type=float, default=YOLO_CONFIDENCE_THRESHOLD)
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--limit", type=int, default=None, help="evaluate only the first N images")
    parser.add_argument("--sweep", action="store_true", help="also report micro P/R/F1 across thresholds")
    args = parser.parse_args()

    from PIL import Image  # lazy: pillow arrives with the vision stack

    names, images, label_dir = load_split(args.data, args.split)
    images = images[: args.limit]
    floor = min(_SWEEP) if args.sweep else args.conf
    detector = NCNNDetector(args.model, confidence_threshold=floor, num_threads=args.threads)
    model_names = {_norm(n) for n in detector.names}
    labelled = set(names)
    unknown = sorted(labelled - model_names)
    print(f"{len(images)} images, conf {args.conf}; dataset classes the model cannot name: {', '.join(unknown) or 'none'}")

    records, latencies = [], []
    for path in images:
        bgr = np.ascontiguousarray(np.array(Image.open(path).convert("RGB"))[:, :, ::-1])
        h, w = bgr.shape[:2]
        start = time.perf_counter()
        dets = detector.detect(Frame(image=bgr, timestamp=0.0, width=w, height=h))
        latencies.append((time.perf_counter() - start) * 1000)
        truth = [t for t in ground_truth(label_dir / f"{path.stem}.txt", names, w, h) if t[0] in labelled]
        records.append((truth, [(_norm(d.class_name), d.confidence, d.bbox) for d in dets]))

    box, image, confused = score(records, labelled, args.conf)
    print(f"\nmedian latency {np.median(latencies):.1f} ms (frames at source resolution)\n")
    print(f"{'class':15s} {'gt':>5s} {'P':>5s} {'P 95% CI':>13s} {'R':>5s} {'R 95% CI':>13s} {'spokenP':>8s} {'spokenR':>8s}  missed boxes confused as")
    for name in sorted(labelled, key=lambda n: -(box[n][0] + box[n][2])):
        tp, fp, fn = box[name]
        if tp + fp + fn == 0:
            continue
        p_lo, p_hi = wilson(tp, tp + fp)
        r_lo, r_hi = wilson(tp, tp + fn)
        itp, ifp, ifn = image[name]
        sp = itp / (itp + ifp) if itp + ifp else float("nan")
        sr = itp / (itp + ifn) if itp + ifn else float("nan")
        top = ", ".join(f"{k} {v}" for k, v in confused[name].most_common(3))
        print(f"{name:15s} {tp + fn:5d} {tp / max(1, tp + fp):5.2f} [{p_lo:.2f}, {p_hi:.2f}] "
              f"{tp / max(1, tp + fn):5.2f} [{r_lo:.2f}, {r_hi:.2f}] {sp:8.2f} {sr:8.2f}  {top}")

    if args.sweep:
        print(f"\n{'conf':>5s} {'P':>6s} {'R':>6s} {'F1':>6s}   (micro over all shared classes, box level)")
        for conf in _SWEEP:
            b, _, _ = score(records, labelled, conf)
            tp, fp, fn = (sum(v[i] for v in b.values()) for i in range(3))
            p, r = tp / max(1, tp + fp), tp / max(1, tp + fn)
            print(f"{conf:5.2f} {p:6.3f} {r:6.3f} {2 * p * r / max(1e-9, p + r):6.3f}")


if __name__ == "__main__":
    main()
