"""COCO replay subset: images containing our kept classes, labels remapped.

Fetches individual images from images.cocodataset.org instead of the 18 GB
train zip. Train: a class-balanced sample; val: every val2017 image that has
a kept class (it doubles as the forgetting regression set).
"""
import random, pathlib, collections, concurrent.futures as cf, urllib.request, sys, time
from classes import COCO_TO_OURS

RAW = pathlib.Path("raw/coco/labels")
OUT = pathlib.Path("data/coco")
N_TRAIN = int(sys.argv[1]) if len(sys.argv) > 1 else 14000
random.seed(0)


def remap(path):
    rows = []
    for line in path.read_text().splitlines():
        c, *xywh = line.split()
        if int(c) in COCO_TO_OURS:
            rows.append(" ".join([str(COCO_TO_OURS[int(c)]), *xywh]))
    return rows


def select(split, n):
    items = []
    for p in sorted((RAW / split).glob("*.txt")):
        rows = remap(p)
        if rows:
            items.append((p.stem, rows))
    if n is None or n >= len(items):
        return items
    # Class-balanced: guarantee every class at least its share, then fill randomly.
    by_cls = collections.defaultdict(list)
    for i, (_, rows) in enumerate(items):
        # sorted(): iterating a set of str follows Python's per-process hash
        # seed, which made two runs sample different subsets.
        for c in sorted({r.split()[0] for r in rows}):
            by_cls[c].append(i)
    chosen = set()
    per = n // (2 * len(by_cls))
    for idxs in by_cls.values():
        chosen.update(random.sample(idxs, min(per, len(idxs))))
    rest = [i for i in range(len(items)) if i not in chosen]
    chosen.update(random.sample(rest, n - len(chosen)))
    return [items[i] for i in sorted(chosen)]


def fetch(split, stem, rows):
    img = OUT / "images" / split / f"{stem}.jpg"
    if not img.exists():
        url = f"http://images.cocodataset.org/{split}2017/{stem}.jpg"
        for attempt in range(8):
            try:
                img.write_bytes(urllib.request.urlopen(url, timeout=60).read())
                break
            except Exception:
                time.sleep(2 ** attempt)
        else:
            print("gave up", url, flush=True)
            return
    (OUT / "labels" / split / f"{stem}.txt").write_text("\n".join(rows) + "\n")


for split, n in (("train", N_TRAIN), ("val", None)):
    (OUT / "images" / split).mkdir(parents=True, exist_ok=True)
    (OUT / "labels" / split).mkdir(parents=True, exist_ok=True)
    items = select(f"{split}2017", n)
    print(split, len(items), flush=True)
    with cf.ThreadPoolExecutor(12) as ex:
        list(ex.map(lambda it: fetch(split, *it), items))
print("done")
