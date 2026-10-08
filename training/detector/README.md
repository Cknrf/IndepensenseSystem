# Object-detector training pipeline

How `models/detector/yolo26n-ph_640_ncnn_model` was built. Runs on a GPU
machine with internet access — never on the Pi, which only runs the NCNN
export through `vision/ncnn_detector.py`. Why this model at all:
`docs/object-detection-research.md`.

## Setup (GPU box)

```bash
python3 -m venv .venv
.venv/bin/pip install "ultralytics==8.4.72" roboflow kaggle ncnn pnnx onnx onnxslim imagehash
```

Credentials are read from files and never printed: a Roboflow API key in
`.roboflow_key` (this directory) and a Kaggle token in `~/.kaggle/access_token`.
Create both with `read -s` so the key stays out of shell history.

## Steps

Run from this directory, in order:

| Step | Script | What it does |
|---|---|---|
| 1 | `fetch_ph.py` | Downloads the Philippine datasets (Kaggle + Roboflow) |
| 2 | `prep_coco.py 14000` | COCO replay subset, class-balanced, images fetched one by one (needs the ultralytics `coco2017labels.zip` unpacked under `raw/`) |
| 3 | `prep_oiv7.py 3000` | Open Images door + stairs, downscaled to 1024 px |
| 4 | `build.py` | Merges sources under our class names, dedups, splits, adds teacher labels |
| 5 | `train.py 80` | Fine-tunes YOLO26n and exports NCNN at 640 and 416 |

`classes.py` is the single source of the class list (index order is the
model's contract) and of every source-label mapping. Each mapping was chosen
by looking at crops of that source class, not from its name — "Electric
Bike" in the DLSU set is an e-trike, and Roboflow's `kariton` includes book
carts.

## Decisions a reader should know

- **Teacher labels.** Each source labels only its own classes, so a vehicle
  dataset leaves every pedestrian unlabelled — training on it as-is teaches
  that a person is background. `yolo26x` adds the COCO classes a source does
  not label (confidence ≥ 0.5) and YOLOE adds door/stairs (≥ 0.3, chosen
  from a 200-image spot check). Teacher outputs are cached per image.
- **One copy per original.** Roboflow exports contain pre-augmented
  triples (`<orig>_jpg.rf.<hash>`); only one is kept, since ultralytics
  augments on its own and triples would leak across splits.
- **Perceptual-hash dedup** drops any train image identical to a val/test
  image — several public PH projects re-upload each other's photos.
- **Held-out pedicab/pushcart.** Both exist only in G17's train split; 15% of
  their image groups are moved to test so they can be scored at all.
- **Training memory.** 8 dataloader workers at batch 64. An earlier run with
  24 workers at batch 128 exhausted the shared machine's RAM and the trainer
  was killed in epoch 1 with its workers left hanging.
- **The v1 COCO subset is the union of two sampling runs** (~18k images
  instead of 14k): an early version of `prep_coco.py` sampled in hash-seed
  order and was accidentally run twice. The committed script is
  deterministic.

## Results (v1, 80 epochs, RTX 6000 Ada, ~4.5 h)

See `docs/object-detection-research.md` § "Measured results".

Dataset sources and their licences: `DATASETS.md`.
