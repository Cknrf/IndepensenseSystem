"""Assemble the unified training set, deduplicate, and fill missing labels with teachers.

Why teachers: each source labels only its own classes. A vehicle dataset
leaves every pedestrian unlabelled, which would teach the student that a
person is background. A large COCO model adds the COCO classes a source does
not cover, and YOLOE adds door/stairs everywhere except Open Images (which
labels them). Teacher boxes use a high confidence bar — a missed teacher box
costs less than a wrong one.

Splits
  train  every source's train split (+ COCO/OIV7 train)
  val    PH sources' valid splits + OIV7 val + 1,500 COCO val images — model selection
  test   PH sources' test splits + held-out pedicab/pushcart groups — in-domain test, never seen
  coco_reg  the remaining COCO val images — the forgetting regression set
"""
import collections, json, os, pathlib, random, re, sys
import yaml
from PIL import Image
import imagehash
from concurrent.futures import ProcessPoolExecutor
from classes import CLASSES, IDX, COCO_TO_OURS, SOURCE_MAPS

random.seed(0)
RAW, DATA, OUT = pathlib.Path("raw"), pathlib.Path("data"), pathlib.Path("data/unified")
COCO_KEPT = set(COCO_TO_OURS.values())
# Per teacher: YOLOE scores doors lower than the COCO model scores its classes;
# a spot check on 200 COCO images found its boxes precise at 0.3 and very sparse at 0.5.
TEACHER_CONF = {"coco": 0.5, "door": 0.3}


def roboflow_group(stem):
    """Roboflow names augmented copies `<orig>_jpg.rf.<hash>`; the prefix identifies the original."""
    return re.sub(r"\.rf\.[0-9a-f]+$", "", stem)


def source_items(name):
    d = RAW / name
    names = yaml.safe_load((d / "data.yaml").read_text())["names"]
    names = names if isinstance(names, list) else [names[i] for i in sorted(names)]
    mapping = SOURCE_MAPS[name]
    for split, ours in (("train", "train"), ("valid", "val"), ("val", "val"), ("test", "test")):
        for lab_dir in (d / split / "labels", d / "labels" / split):
            if not lab_dir.exists():
                continue
            img_dir = pathlib.Path(str(lab_dir).replace("labels", "images"))
            by_stem = {f.stem: f for f in img_dir.iterdir()}
            for lab in lab_dir.glob("*.txt"):
                img = by_stem.get(lab.stem)
                if img is None:
                    continue
                rows = []
                for line in lab.read_text().splitlines():
                    p = line.split()
                    if len(p) != 5:  # polygons / malformed rows are skipped
                        continue
                    key = mapping[names[int(p[0])]]
                    if key is not None:
                        rows.append(f"{IDX[key]} " + " ".join(p[1:]))
                yield {"src": name, "split": ours, "img": str(img.resolve()), "rows": rows,
                       "group": f"{name}:{roboflow_group(lab.stem)}"}


def local_items(name):
    for split in ("train", "val"):
        for lab in (DATA / name / "labels" / split).glob("*.txt"):
            img = DATA / name / "images" / split / f"{lab.stem}.jpg"
            if img.exists():
                yield {"src": name, "split": split, "img": str(img.resolve()),
                       "rows": lab.read_text().split("\n")[:-1], "group": f"{name}:{lab.stem}"}


def phash(path):
    try:
        return str(imagehash.phash(Image.open(path)))
    except Exception:
        return None


items = []
for name in SOURCE_MAPS:
    items += list(source_items(name))
items += list(local_items("coco")) + list(local_items("oiv7"))
print("raw items", collections.Counter((i["src"], i["split"]) for i in items), flush=True)

# One copy per original from Roboflow's pre-augmented triples; ultralytics augments on its own.
seen_groups, deduped = set(), []
for it in items:
    if it["group"] in seen_groups:
        continue
    seen_groups.add(it["group"])
    deduped.append(it)
items = deduped

# Pedicab and pushcart only exist in G17's train split: hold out 15% of their groups as test.
for key in ("pedicab", "pushcart"):
    holders = [it for it in items if it["split"] == "train" and any(r.split()[0] == str(IDX[key]) for r in it["rows"])]
    for it in random.sample(holders, len(holders) * 15 // 100):
        it["split"] = "test"

# COCO val: 1,500 for model selection, the rest is the regression set.
coco_val = [it for it in items if it["src"] == "coco" and it["split"] == "val"]
for it in coco_val[1500:]:
    it["split"] = "coco_reg"

# Perceptual-hash dedup: a train image identical to any val/test image is dropped
# (several Roboflow PH projects re-upload each other's photos).
with ProcessPoolExecutor(40) as ex:
    hashes = list(ex.map(phash, [it["img"] for it in items], chunksize=256))
held_out = {h for h, it in zip(hashes, items) if h and it["split"] != "train"}
before = len(items)
items = [it for h, it in zip(hashes, items) if not (it["split"] == "train" and h in held_out)]
print(f"phash dedup removed {before - len(items)} train images", flush=True)

# --- teachers -------------------------------------------------------------
from ultralytics import YOLO

def covered(src):
    """Classes a source labels itself; the teacher must not add these."""
    if src == "coco":
        return COCO_KEPT
    if src == "oiv7":
        return {IDX["door"], IDX["stairs"]}
    return {IDX[v] for v in SOURCE_MAPS[src].values() if v}


def to_rows(result, allowed, conf_min):
    rows = []
    for c, conf, xywhn in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist(), result.boxes.xywhn.tolist()):
        if conf < conf_min or c not in allowed:
            continue
        rows.append(f"{allowed[c]} " + " ".join(f"{v:.6f}" for v in xywhn))
    return rows


coco_teacher = YOLO("yolo26x.pt")
coco_allowed = {ci: oi for ci, oi in COCO_TO_OURS.items()}
door_teacher = YOLO("yoloe-26x-seg.pt")
door_teacher.set_classes(["door", "stairs"])
door_allowed = {0: IDX["door"], 1: IDX["stairs"]}

added = collections.Counter()
for teacher, allowed_all, label in ((coco_teacher, coco_allowed, "coco"), (door_teacher, door_allowed, "door")):
    # Each teacher's boxes are cached per image: the GPU is shared, and an
    # out-of-memory crash in the second teacher must not cost the first one's run.
    cache_path = OUT.parent / f"teacher_{label}.json"
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    targets = [it for it in items if ((label == "coco" and it["src"] != "coco") or (label == "door" and it["src"] != "oiv7"))
               and it["img"] not in cache]
    # predict() ignores `batch=` for a list of paths and runs the whole list
    # as one batch, so the list itself is the batch.
    batch_size = 64 if label == "coco" else 16
    for start in range(0, len(targets), batch_size):
        batch = targets[start:start + batch_size]
        # half=False for YOLOE: its mask head fails on fp16 in ultralytics 8.4.72
        results = teacher.predict([it["img"] for it in batch], imgsz=640, conf=TEACHER_CONF[label], verbose=False,
                                  batch=batch_size, half=(label == "coco"))
        for it, res in zip(batch, results):
            allowed = {c: o for c, o in allowed_all.items() if o not in covered(it["src"])}
            cache[it["img"]] = to_rows(res, allowed, TEACHER_CONF[label])
        if start % (batch_size * 160) == 0:
            print(label, start, len(targets), flush=True)
            cache_path.write_text(json.dumps(cache))
    cache_path.write_text(json.dumps(cache))
    for it in items:
        new = cache.get(it["img"], [])
        if (label == "coco" and it["src"] != "coco") or (label == "door" and it["src"] != "oiv7"):
            it["rows"] += new
            for r in new:
                added[CLASSES[int(r.split()[0])]] += 1
    del teacher
print("teacher boxes added", dict(added), flush=True)

# --- write ----------------------------------------------------------------
for it in items:
    split = it["split"]
    (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
    stem = f'{it["src"]}__{pathlib.Path(it["img"]).stem}'[:200]
    link = OUT / "images" / split / (stem + pathlib.Path(it["img"]).suffix)
    if not link.exists():
        os.symlink(it["img"], link)
    (OUT / "labels" / split / f"{stem}.txt").write_text("\n".join(it["rows"]) + ("\n" if it["rows"] else ""))

stats = collections.defaultdict(collections.Counter)
for it in items:
    for r in it["rows"]:
        stats[it["split"]][CLASSES[int(r.split()[0])]] += 1
json.dump({"images": collections.Counter(it["split"] for it in items), "instances": stats},
          open(OUT / "stats.json", "w"), indent=1)
for split in ("val", "test", "coco_reg"):
    yaml.safe_dump({"path": str(OUT.resolve()), "train": "images/train", "val": f"images/{split}",
                    "names": dict(enumerate(CLASSES))}, open(OUT / f"{split}.yaml", "w"), sort_keys=False)
print("done", collections.Counter(it["split"] for it in items))
