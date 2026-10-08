"""Open Images V7 door + stairs subset (annotations CC BY 4.0, images listed CC BY 2.0).

Streams the train bbox CSV (2.2 GB) rather than storing it, keeps images with
a Door or Stairs box, downloads each from the public S3 bucket and stores it
downscaled to max 1024 px (disk on the training box is tight). Labels are
written in YOLO format with our class indices.
"""
import csv, io, pathlib, random, sys, time, urllib.request, collections, concurrent.futures as cf
from PIL import Image
from classes import IDX

MIDS = {"/m/02dgv": IDX["door"], "/m/01lynh": IDX["stairs"]}
PER_CLASS = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
OUT = pathlib.Path("data/oiv7")
random.seed(0)

# Verify the MIDs against the official class list rather than trusting memory.
desc = urllib.request.urlopen("https://storage.googleapis.com/openimages/v7/oidv7-class-descriptions-boxable.csv").read().decode()
names = dict(row for row in csv.reader(io.StringIO(desc)))
assert names["/m/02dgv"] == "Door" and names["/m/01lynh"] == "Stairs", (names.get("/m/02dgv"), names.get("/m/01lynh"))

boxes = collections.defaultdict(list)
src = urllib.request.urlopen("https://storage.googleapis.com/openimages/v6/oidv6-train-annotations-bbox.csv")
reader = csv.reader(io.TextIOWrapper(src, encoding="utf-8"))
header = next(reader)
col = {h: i for i, h in enumerate(header)}
for row in reader:
    mid = row[col["LabelName"]]
    if mid in MIDS:
        x1, x2, y1, y2 = (float(row[col[k]]) for k in ("XMin", "XMax", "YMin", "YMax"))
        boxes[row[col["ImageID"]]].append((MIDS[mid], (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1))
print("images with door/stairs:", len(boxes), flush=True)

chosen = set()
for cls in MIDS.values():
    ids = [i for i, b in boxes.items() if any(c == cls for c, *_ in b)]
    chosen.update(random.sample(ids, min(PER_CLASS, len(ids))))
chosen = sorted(chosen)
val = set(random.sample(chosen, len(chosen) // 10))


def fetch(image_id):
    split = "val" if image_id in val else "train"
    img_path = OUT / "images" / split / f"{image_id}.jpg"
    if not img_path.exists():
        for attempt in range(6):
            try:
                data = urllib.request.urlopen(f"https://open-images-dataset.s3.amazonaws.com/train/{image_id}.jpg", timeout=60).read()
                break
            except Exception:
                time.sleep(2 ** attempt)
        else:
            return
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((1024, 1024))
        im.save(img_path, quality=90)
    rows = [f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}" for c, cx, cy, w, h in boxes[image_id]]
    (OUT / "labels" / split / f"{image_id}.txt").write_text("\n".join(rows) + "\n")


for split in ("train", "val"):
    (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
with cf.ThreadPoolExecutor(16) as ex:
    list(ex.map(fetch, chosen))
print("done", len(chosen))
