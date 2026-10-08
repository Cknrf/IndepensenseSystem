# Object detection for Philippine streets — model research and recommendation

Status: written 2026-10-07 as research; **the recommendation (§5) was implemented on 2026-10-08** — results in § Measured results at the end. Note: the class list grew to 33 during implementation (§5 sketched ~30).

Every number in this document has one of four origins, tagged throughout:

| Tag | Meaning |
|---|---|
| **[Pi-measured]** | Measured on the actual device (`cknrf`, Pi 5 8 GB, Trixie) on 2026-10-07. A passive snapshot only; nothing was installed or run on the Pi. |
| **[Mac-measured]** | Measured on an Apple M4 Mac, with torch, ncnn and ONNX Runtime held to 4 threads to mirror the Pi's 4 cores. Absolute latency does **not** transfer to the Pi. RSS and *ratios* between models broadly do, because both are arm64. |
| **[Published]** | From an official benchmark, paper or vendor page, linked. |
| **[Extrapolated]** | A Pi estimate computed from a Mac measurement × a Pi/Mac ratio taken from a published Pi number. Treat it as ±50 % until re-measured on the Pi. |

---

## 0. What the system actually runs today

The brief assumed a COCO YOLOv8 model. The code says otherwise:

- `config.YOLO_MODEL_PATH` is **`yolov8m-oiv7.pt`**: YOLOv8 *medium* trained on Open Images V7 (601 classes), run through PyTorch at the default `imgsz=640`, letterboxed from the 1280×720 camera frame.
- The model is **loaded at startup and kept resident** (`App._try_open_detector`, `app.py:3666`).
- `vision/detector.py`'s docstring still describes yolov8n (~6 MB), which is stale.

Two defects in the current setup bear directly on model choice:

1. **OIV7 class names are capitalised** (`"Person"`, `"Door"`, `"Stairs"`; checked against Ultralytics' [`open-images-v7.yaml`](https://raw.githubusercontent.com/ultralytics/ultralytics/main/ultralytics/cfg/datasets/open-images-v7.yaml)). `messages._TL_LABELS` uses lowercase COCO keys, so in Tagalog **every lookup misses** and the device says "isang Person". In English, `english_plural("Person", 2)` misses `_IRREGULAR_PLURALS` too and produces "2 Persons". Found by reading the code; not yet confirmed on the device.
2. **OIV7 is hierarchical, so one object yields several labels.** In the probe (§3), yolov8m-oiv7 reported `Wheel` in 8 of 9 jeepney photos, plus `Tire`, `Footwear`, `Clothing` and `Man` alongside `Person`. For a spoken scene description that capped at 5 items, these part labels push out the useful ones. COCO's flat label set does not have this problem.

## 1. Memory headroom on the Pi [Pi-measured]

Snapshot from 2026-10-07, 2 h uptime, `app.py` running (one commit behind `main`), no route being computed:

| | RSS |
|---|---|
| Ollama `llama-server` (Qwen 3 1.7B, pinned with `keep_alive: -1`) | 1,863 MB |
| `python3 app.py` (torch, transformers, faster-whisper, Piper + MMS, e5-small, **yolov8m-oiv7**) | 1,735 MB (peak 1,864 MB) |
| GraphHopper (`-Xmx2g`) | 501 MB |
| Photon (`-Xmx2g`) | 309 MB |
| Desktop session (labwc, wayvnc ×2, panel, pcmanfm …) | ~450 MB |
| **System:** used / available / total | **4,844 / 3,217 / 8,062 MB**; swap 2 GB, 0 used |
| SoC temperature / throttle flags | 57.1 °C / `0x0` (never throttled) |

There is ~3.2 GB available while idle, but **that figure is optimistic**. Each JVM may grow its heap to 2 GB under routing and geocoding load, which can consume up to ~3 GB more. The real worst-case headroom therefore lies somewhere between ~0.2 and 3.2 GB. Measuring it needs a `system_performance --csv` run *during* navigation.

Detection should therefore be judged on **marginal RSS**: torch is already imported by transformers, MMS-TTS and e5, so torch costs nothing extra.

Marginal cost of the detector itself [Mac-measured, fresh process, torch already imported]:

| Detector path | RSS after load | Peak RSS after inference |
|---|---|---|
| yolov8m-oiv7, PyTorch (current) | +252 MB | **+377 MB** |
| YOLO26n NCNN via Ultralytics | +141 MB | +216 MB |
| YOLO26n NCNN via the `ncnn` package directly (no Ultralytics) | +12 MB | **+60 MB** |
| YOLOE-26s (fixed vocabulary) NCNN, `ncnn` directly | +48 MB | +142 MB |

Moving from the current model to YOLO26n NCNN frees roughly 160–320 MB. That is the measured Mac difference; confirm it on the Pi.

**Load time is negligible** [Mac-measured]: 6–20 ms from a warm page cache for every candidate (yolov8m-oiv7.pt 20 ms; YOLO26n NCNN raw 6 ms). From a cold SD card it will be longer but still well under the STT→LLM chain. So "resident vs on-demand" is purely a RAM question. For a nano model at ~60 MB, **keeping it resident** is the simpler choice, and it is what the code already does.

## 2. Speed

### 2.1 Published Pi 5 CPU numbers [Published]

Source: Ultralytics Raspberry Pi guide ([current](https://docs.ultralytics.com/guides/raspberry-pi/); YOLO11 from [tag v8.3.200](https://github.com/ultralytics/ultralytics/blob/v8.3.200/docs/en/guides/raspberry-pi.md); YOLOv8 from [tag v8.2.50](https://github.com/ultralytics/ultralytics/blob/v8.2.50/docs/en/guides/raspberry-pi.md)). FP32, imgsz 640, inference only (pre- and post-processing excluded), ms per image:

| Model | PyTorch | ONNX | OpenVINO | MNN | **NCNN** | COCO mAP50-95 |
|---|---|---|---|---|---|---|
| YOLOv8n | 508.6 | 198.7 | 704.7 | – | **94.3** | 37.3 |
| YOLO11n | 387.6 | 191.1 | 84.8 | 115.0 | **94.0** | 39.5 |
| YOLO26n | 299.1 | 126.0 | 104.6 | 91.9 | **67.0** | 40.9 |
| YOLO26s | 848.7 | 355.7 | 281.8 | 237.2 | **172.9** | 48.6 |
| YOLO11m / YOLO26m (ONNX) | – | 997.5 / 993.8 | – | – | – | 51.5 / (see model page) |

Caveats:
- The mAP in the Pi tables themselves comes from coco128/coco8. Cite COCO val2017 from the model pages ([YOLOv8](https://docs.ultralytics.com/models/yolov8/), [YOLO11](https://docs.ultralytics.com/models/yolo11/), [YOLO26](https://docs.ultralytics.com/models/yolo26/)).
- Format rankings change between Ultralytics versions (OpenVINO was slow for YOLOv8 and fastest for YOLO11), so always cite the version.
- A third-party measurement of YOLO11n NCNN (292 ms, [LearnOpenCV](https://learnopencv.com/yolo11-on-raspberry-pi/)) contradicts the official 94 ms. This is another reason to measure on our own device.

On OIV7 accuracy [Published, [YOLOv8 page](https://docs.ultralytics.com/models/yolov8/)], measured as OIV7 mAP50-95: yolov8n-oiv7 18.4, yolov8s-oiv7 27.7, yolov8m-oiv7 33.6.

### 2.2 Our own comparison [Mac-measured] with Pi extrapolation

All rows use one 1280×720 frame, `conf=0.3`, 3 warm-up runs, median of 20 runs, end to end (resize, inference and, for Ultralytics rows, post-processing). The "Pi est." column is [Extrapolated] from the ratio of the published Pi value to our Mac value for the same backend:
- NCNN and ONNX: 67.0 / 12.4 ≈ 5.4×
- PyTorch: 299.1 / 19.0 ≈ 15.7×

| Model | Format | imgsz | Mac median | **Pi est.** | Peak RSS (fresh process) |
|---|---|---|---|---|---|
| **yolov8m-oiv7 (current)** | PyTorch | 640 | 78.8 ms | **~1.2 s** | 589 MB |
| yolov8n (COCO) | PyTorch | 640 | 19.2 ms | ~300 ms | 422 MB |
| yolov8n (COCO) | NCNN (Ultralytics) | 640 | 12.8 ms | ~70 ms | 434 MB |
| yolo11n | NCNN (Ultralytics) | 640 | 13.7 ms | ~75 ms | 422 MB |
| yolo26n | PyTorch | 640 / 416 / 320 | 19.0 / 10.7 / 7.5 ms | ~300 / 170 / 120 ms | 409 MB |
| yolo26n | ONNX Runtime (raw, 4 threads) | 640 / 416 | 15.7 / 6.9 ms | ~85 / 37 ms | 228 MB |
| **yolo26n** | **NCNN (raw)** | **640 / 416 / 320** | **12.4 / 5.5 / 3.4 ms** | **~67 / 30 / 18 ms** | **135 MB** |
| yoloe-26n, PH vocabulary | NCNN (Ultralytics) | 640 | 17.8 ms | ~95 ms | 465 MB |
| yoloe-26s, PH vocabulary | NCNN (raw) | 640 / 416 | 35.5 / 15.4 ms | ~190 / 83 ms | 217 MB |

What this shows:
- **The current model costs about 20× more time than it needs to.** The config comment's "~1.5–2 s" (written by hand, never measured) is consistent with the ~1.2 s inference estimate plus pre/post-processing.
- **Input size scales almost quadratically** [Mac-measured, raw NCNN]. 416 costs 0.44× of 640 and 320 costs 0.27×, against theoretical 0.42× and 0.25×. No published Pi sweep exists, so this is our own evidence.
- **NCNN is the fastest CPU backend** for every nano model here, and the lightest when called directly.
- **Every candidate except the current one is fast enough not to matter** next to the ~5 s STT→LLM→TTS chain. On-demand latency stops being the deciding factor; **accuracy on Philippine classes and RAM decide**.

### 2.3 Accelerators

| Option | Price | Published performance | Verdict |
|---|---|---|---|
| AI HAT+ 13 TOPS (Hailo-8L) | $70 | YOLOv8n ~200 FPS (batch 1) on an x86 host; slower on the Pi's PCIe Gen3 ×1 ([Hailo zoo](https://github.com/hailo-ai/hailo_model_zoo/blob/master/docs/public_models/HAILO8L/HAILO8L_object_detection.rst)) | Not now |
| AI HAT+ 26 TOPS (Hailo-8) | $110 | YOLO11n ~105 FPS on a Pi 5 ([Hailo forum](https://community.hailo.ai/t/official-fps-benchmark-on-hailo-8-using-raspberry-pi-5/18873)) | Not now |
| AI HAT+ 2 (Hailo-10H, 8 GB on board) | $130 at launch, now [$200](https://www.raspberrypi.com/products/ai-hat-plus-2/) | Vision "comparable to the 26 TOPS HAT+"; its real draw is offloading the LLM | A separate decision (LLM offload) |
| AI Camera (IMX500) | $70 | YOLO11n 58.8 ms on-sensor; **only v8n/11n**, 8 MB model limit ([Ultralytics](https://docs.ultralytics.com/integrations/sony-imx500/)) | Not now |

[Published; [RPi AI docs](https://www.raspberrypi.com/documentation/computers/ai.html), [Ultralytics Hailo export](https://docs.ultralytics.com/integrations/hailo/)]

Why the accelerators are rejected:
- Detection is **on demand**, and a nano model on the CPU takes ~70 ms per call (estimated). An NPU saves under 0.1 s per question while adding cost, a second toolchain (the Hailo Dataflow Compiler runs only on x86 Linux; at least 1,024 calibration images; INT8), battery draw and a HAT stack.
- The PCIe slot is free [Pi-measured: `lspci` lists only the RP1], so this stays open.
- **When to revisit:** if detection becomes *continuous*, for example camera-based hazard alerts running alongside the ultrasonics. That is the point at which 4 cores at ~67 ms per frame would compete with the 100 Hz loop and the LLM.

## 3. Can anything recognise Philippine objects today? [Mac-measured probe]

Method:
- **Images:** 48 photos from Wikimedia Commons, 8 per category, 1280 px; licences recorded per file (30 CC0, the rest CC BY / BY-SA).
- **Curation by eye:** two jeepney interiors removed; three "modern jeepney" photos that actually show traditional jeepneys relabelled. That leaves 42 images.
- **Settings:** `imgsz=640`, `conf=0.3` (the current config).
- **YOLOE vocabulary:** person, car, motorcycle, bicycle, bus, truck, dog, chair, table, door, stairs, jeepney, "modern jeepney minibus", "tricycle motorcycle with sidecar", "pedicab bicycle with sidecar", "street vendor cart", "sari-sari store front", "open manhole", "open canal".

**This is an illustration, not a validation.** The tricycle, pedicab and kariton categories are each mostly near-duplicate frames of a single vehicle, and n is tiny.

Each cell gives the label on the **largest non-person box** (most frequent first), or the hit rate where the model has the right class:

| Truth (n) | yolov8n COCO | yolo26n COCO | yolov8m-oiv7 (current) | YOLOE-26n, PH prompts | **YOLOE-26s, PH prompts** |
|---|---|---|---|---|---|
| Jeepney (9) | truck 8, bus 1 | **truck 9** | Truck 3, Tree 2, Wheel 2 | "modern jeepney" 9 (wrong subtype) | jeepney 2, modern jeepney 2, truck 4 |
| Modern jeepney (5) | **bus 5** | bus 5 | Bus 4, Van 1 | modern jeepney 2, bus 3 | bus 5 |
| Tricycle (8) | motorcycle 4, truck 4 | motorcycle 5, truck 3 | Motorcycle 3, misc | confused (pedicab / jeepney) | tricycle 2, pedicab 3, motorcycle 3 |
| Pedicab (8) | bicycle 3, motorcycle 2 | motorcycle 2, umbrella 2 | Bicycle 4 | **pedicab 6** | pedicab 5 (in 7/8 images) |
| Kariton / vendor cart (8) | truck 3, bicycle 2 | bicycle 4 | Bicycle 7 | jeepney 3 (wrong) | vendor cart 3 |
| Sari-sari store (8) | nothing 4 | bicycle/motorcycle | Building 2 | sari-sari 1 | sari-sari 3 (4 at conf 0.15) |

Conclusions:
1. **Stock COCO is consistent, not random:** jeepney → "truck", modern jeepney → "bus", tricycle → "motorcycle" or "truck". A spoken "I see a truck" for a jeepney is wrong for a Filipino user, but it is safely wrong (the user still hears that a large vehicle is there). No published confusion matrix for this exists (see §8), so this table is original evidence for the thesis.
2. **The current OIV7-medium model is no better on these classes**, and is noisier ("Wheel", "Tree", "Tire").
3. **Open-vocabulary detection (YOLOE) partly works out of the box.** It handles pedicabs, sometimes vendor carts and sari-sari fronts, but it **cannot reliably tell jeepney from modern jeepney from tricycle**, which is exactly the distinction a fine-grained class needs. The nano version is substantially worse than the small one.
4. Only a model **trained on Philippine images** separates these classes. Published results support this: a DLSU-D 14-class Philippine set reaches 90.3 % mAP50 with YOLO11s ([Kaggle](https://www.kaggle.com/datasets/jancarloparedes/philippine-vehicle-classification-14class)), and a Metro Manila YOLOv12 study reports AP50 0.968 for jeepney and 0.980 for tricycle ([Smart Cities 2026](https://doi.org/10.3390/smartcities9050085)). The Indian analogue (auto-rickshaws, [UVH-26](https://arxiv.org/abs/2511.02563)) shows +8–31 % mAP from in-domain data over COCO weights.

## 4. Comparison of the four options

| | (a) Stock COCO nano | (b) Open-vocab, fixed vocabulary | (c) Fine-tuned nano, one merged model | (d) COCO model + PH model |
|---|---|---|---|---|
| **Example** | YOLO26n COCO | YOLOE-26s-seg + `set_classes` → NCNN | YOLO26n trained on COCO subset + OIV7 door/stairs + PH data | YOLO26n COCO + YOLO26n 8-class PH |
| **PH classes** | None (jeepney → truck) | Partial, zero-shot, unreliable subtypes (§3) | Yes, learned (published PH AP50 ≈ 0.9+) | Yes |
| **Universal classes** | 80 COCO; **no door, no stairs** | Whatever you prompt, including door and stairs | Chosen set, including door and stairs | 80 COCO + PH |
| **Training effort** | None | None (choosing prompts) | Days: dataset merge, pseudo-labelling, 1 training run on a GPU (Colab/Kaggle) | Same data work, two models |
| **Pi latency** [Extrap.] | ~67 ms @640 | ~190 ms @640 / ~83 ms @416 | ~67 ms @640 (head size barely changes) | ~135 ms (two passes) |
| **Marginal RAM** [Mac] | ~60 MB raw NCNN | ~140 MB | ~60 MB | ~120 MB |
| **Licence** | AGPL-3.0 (code **and** weights, [Ultralytics](https://www.ultralytics.com/license)) | AGPL-3.0 ([THU-MIG/yoloe](https://github.com/THU-MIG/yoloe)); YOLO-World is GPL-3.0 | AGPL-3.0 + attribution for CC BY 4.0 datasets | Same as (c) |
| **Main risk** | Wrong-but-plausible labels | Silent misclassification between PH subtypes; segmentation head in every checkpoint; prompt-free models can't export to ONNX | Forgetting COCO classes; unlabelled persons in PH images; viewpoint shift (CCTV → chest) | Cross-model duplicates ("truck" + "jeepney" for one object) need merge logic |

### Why (d) is rejected in favour of (c)

Two models look modular, but the outputs collide. The COCO model calls every jeepney a "truck", so a jeepney produces two detections from two models. Suppressing one needs cross-model, class-aware NMS, which means new logic and new failure modes. The cost also doubles (latency and RAM), and you validate two models instead of one.

One merged model learns "jeepney ≠ truck" directly from data that contains both. Training on a COCO subset alongside the PH data ("replay") is the standard defence against forgetting.

The one real advantage of (d), iterating on the PH model without retraining COCO classes, does not matter for a one-person thesis with a fixed class list.

### Why (b) is the fallback, not the primary

The value of (b) is that it costs zero training and its vocabulary is editable. It also makes the best **auto-labeller** for building (c)'s dataset.

Its weaknesses:
- §3 shows it confusing exactly the classes that matter.
- Zero-shot accuracy on regional classes is unmeasured anywhere in the literature (§8).
- Ultralytics publishes only `-seg` checkpoints, so every inference carries a mask head we discard.

### Rejected outright

- **Grounding DINO, OWLv2, Florence-2, Moondream.** These run at seconds per image on a Pi CPU. Florence-2-base was measured at 20–41 s per image and >5 GB RAM on a Pi 5 ([mlsysbook](https://mlsysbook.ai/kits/contents/raspi/vlm/vlm.html)). They are useful only offline on a laptop, as labellers.
- **YOLO-World v2.** Superseded by YOLOE: the YOLOE paper reports +3.5 LVIS AP and 1.4× faster inference ([arXiv 2503.07465](https://arxiv.org/abs/2503.07465)). There are also reports that it fails to export to NCNN.
- **Staying on yolov8m-oiv7.** It is 20× slower and 160–320 MB heavier, has the label defects in §0, and is no better on PH classes.

## 5. Recommendation

### Primary: (c) YOLO26n fine-tuned as one merged model → NCNN, imgsz 640, resident

**Classes (proposal; ~30).**
- The COCO classes that matter to a blind pedestrian: person, bicycle, car, motorcycle, bus, truck, traffic light, stop sign, bench, dog, cat, chair, couch, bed, dining table, toilet, tv, laptop, cell phone, bottle, cup, backpack, umbrella, potted plant, fire hydrant.
- From OIV7 (CC BY 4.0 annotations): door, stairs.
- Philippine classes: jeepney, modern_jeepney, tricycle, pedicab, vendor_cart (kariton), open_manhole.
- **Left out on purpose until data exists:** habal-habal, sari-sari store front, open canal. No public dataset exists for any of them (§7). Habal-habal is visually a motorcycle with a rider, so "motorcycle" plus "person" is already the right spoken answer.

**Why YOLO26n.** It is the best published Pi 5 NCNN latency (67 ms) and the highest nano COCO mAP (40.9).

**Why NCNN.** It is fastest in both the published and our own measurements. Called directly through `ncnn`, it is also the lightest (+60 MB), because every Ultralytics backend imports torch and Ultralytics' own stack. Two consequences for the implementation:
- The default NCNN export emits the raw `(84, 8400)` head even for YOLO26 (`end2end=True` had no effect in 8.4.72). A runtime without Ultralytics therefore needs ~20 lines of decoding plus `cv2.dnn.NMSBoxes`.
- That is a structural change for you to approve. The simpler intermediate step is to keep `YOLO("…_ncnn_model")` through Ultralytics (+216 MB, still lighter than today).

**Why imgsz 640.** Detection is on demand, so ~70 ms is invisible, and the 1280×720 frame keeps more pixels for distant or small objects. Use 416 (~30 ms) only if detection ever becomes continuous. Validate both sizes on the test set below before deciding.

**Threads.** Set `net.opt.num_threads = 3` and test against 4. ncnn defaults to all 4 big cores and spin-waits 20 ms after each layer, which can steal time from the 100 Hz loop. Measure loop jitter during a detection; no published Pi data covers this.

**Training recipe.**
1. Merge sources:
   - The [DLSU-D Kaggle set](https://www.kaggle.com/datasets/jancarloparedes/philippine-vehicle-classification-14class) (CC BY 4.0, already cleaned).
   - The [G17 set](https://universe.roboflow.com/groups-workspace/g17-datasets) (CC BY 4.0; jeepney, tricycle, pedicab, kariton, kalesa).
   - [PH Vehicles](https://universe.roboflow.com/vehicle-detection-and-data-generation/ph-vehicles-728sm) for e-jeep.
   - [CityFix](https://universe.roboflow.com/inacap-rp6mt/cityfix-projects2) for open manholes.
   - A COCO subset and an OIV7 door/stairs subset, for replay.
2. **Pseudo-label the missing classes on the PH images.** PH vehicle sets usually leave people and dogs unlabelled, which would teach the model that a person is background. Run COCO YOLO26s, or YOLOE for door and stairs, over the PH images; review by hand ([Autodistill](https://github.com/autodistill/autodistill) describes the pattern).
3. Deduplicate across all sources by perceptual hash *before* splitting train and val. Several Roboflow projects are re-uploads of each other.
4. Fine-tune from `yolo26n.pt` on a free GPU (Colab or Kaggle), `imgsz=640`, ~100 epochs. Export `format="ncnn"`.
5. **Viewpoint gap:** the public PH data is mostly CCTV or roadside; the wearable sees from chest height. Add a few hundred chest-height frames from the Camera Module 3 to *training*, kept separate from the test set described below.

### Fallback: (b) YOLOE-26s-seg, fixed PH + universal vocabulary → NCNN, imgsz 416

Use this if there is no time to build the dataset, or as an interim release while it is built.
- Fixed with `set_classes()` and exported once, so no text encoder runs on the Pi.
- ~83 ms (estimated), +142 MB.
- **Speak open-vocabulary PH classes only at the generic level.** Collapse jeepney, modern jeepney and tricycle into "public utility vehicle" if the probe pattern in §3 holds on the real test set. A wrong subtype is worse than a correct generic class.

### Spoken labels, all in `intents/messages.py`

Today, labels are model class names passed straight into `count_label`, with an optional `_TL_LABELS` lookup. That design breaks whenever the model changes (§0). Proposal, for you to approve:

- **Class names in the trained model become stable snake_case keys** that we choose: `jeepney`, `modern_jeepney`, `tricycle`, `pedicab`, `vendor_cart`, `open_manhole`, `door`, `stairs`, `dining_table` …
- **`messages.py` gets one label table** holding each key's per-language spoken form:

  | Key | en (singular / plural) | tl | Note |
  |---|---|---|---|
  | `jeepney` | jeepney / jeepneys | dyip | |
  | `modern_jeepney` | modern jeepney / modern jeepneys | modern jeep | code-switch, as everyday speech does |
  | `tricycle` | tricycle / tricycles | traysikel | |
  | `pedicab` | pedicab / pedicabs | padyak | regional: *trisikad* in the Visayas |
  | `vendor_cart` | vendor cart / vendor carts | kariton | |
  | `open_manhole` | open manhole / open manholes | bukas na manhole | |
  | `dining_table` | table / tables | mesa | the key differs from the spoken word on purpose |

  **The Tagalog column needs checking by a native speaker**, especially the regional pedicab term.
- **A unit test loads the deployed model's class list** (committed next to the model as a small YAML) **and asserts every class has every language.** A new class without a translation then fails the suite, exactly as a missing message already does. This replaces the deliberate "fall through to English" rule, which only made sense while the vocabulary was COCO's and not ours to name.

## 6. Validation plan

**1. Test set (held out, never trained on).**
- Recorded with the wearable's own Camera Module 3 at chest height.
- Captured across ≥ 5 separate sessions in different places, with day, dusk, night and rain.
- **Split by session, not by frame.** Video frames from one walk are near-duplicates (the tricycle and kariton rows in §3 show how badly that inflates any metric).
- Target ≥ 50 instances per class, plus ≥ 100 frames with no PH object as negatives. Below ~50, a recall of 0.8 has a 95 % interval wider than ±0.11, so report Wilson intervals.
- Annotate in CVAT or Label Studio in YOLO format. Double-annotate ~10 % and report agreement.

**2. Detector metrics.** Run `model.val(data=ph_test.yaml, split="test", imgsz=640, conf=0.001)` for per-class precision, recall, AP50 and AP50-95, plus the confusion matrix. The jeepney ↔ truck/bus and tricycle ↔ motorcycle cells are the key thesis figures.

**3. Operational metric (what the user hears).**
- Re-run at the deployed `conf=0.3` and score at image level: did the spoken sentence name a class present in the frame (recall), and did it name anything absent (precision)?
- This captures the `_MAX_SCENE_ITEMS = 5` cap and the threshold, which AP ignores.

**4. Regression on universal classes.** Validate the fine-tuned model on a COCO val2017 subset limited to the retained classes, and compare with stock YOLO26n. This puts a number on forgetting.

**5. Head-to-head baseline.** Run the same test set through:
- stock YOLO26n COCO, with a mapping (truck/bus → "large vehicle");
- the YOLOE fallback;
- the current yolov8m-oiv7.

This gives the thesis its before/after table.

**6. On-device (manual test, Pi).**
- Benchmark latency at 320, 416 and 640 with the app running.
- Log `system_performance --csv` throughout.
- Measure main-loop period jitter during a detection with 3 vs 4 ncnn threads.
- Record peak RSS during a navigation session, to resolve the JVM uncertainty in §1.
- This is the evidence needed to retire every [Extrapolated] number above. It should become a manual test listed in the README table.

## 7. Datasets and licences

| Dataset | Classes of interest | Size | Licence | Viewpoint |
|---|---|---|---|---|
| [DLSU-D Vehicle (Kaggle, cleaned)](https://www.kaggle.com/datasets/jancarloparedes/philippine-vehicle-classification-14class) | PUJ (jeepney), tricycle, e-bike + 11 | 34,792 | CC BY 4.0 | Campus/roadside |
| [G17 Datasets (Roboflow)](https://universe.roboflow.com/groups-workspace/g17-datasets) | jeepney, tricycle, pedicab, kariton, kalesa, tuktuk + 11 | 25,864 | CC BY 4.0 | Not stated |
| [Vehicle Detection YOLO v11](https://universe.roboflow.com/vehicle-detection-gads7/vehicle-detection-yolo-v11-amnce) | jeepney, tricycle, e-tricycle, pedicab | 9,570 | CC BY 4.0 | Not stated |
| [PH Vehicles](https://universe.roboflow.com/vehicle-detection-and-data-generation/ph-vehicles-728sm) | **e-jeep**, jeepney, tricycle | 4,936 | CC BY 4.0 | Not stated |
| [kariton](https://universe.roboflow.com/thesis-datasets-at8oz/kariton) | kariton | 1,092 | CC BY 4.0 | Not stated |
| [CityFix Projects2](https://universe.roboflow.com/inacap-rp6mt/cityfix-projects2) | open / improperly closed manhole, pothole | 4,240 | CC BY 4.0 | Not stated |
| [SOD sidewalk obstacles](https://universe.roboflow.com/lamao/sod-enect) | pole, curb, stairs, bench, bins … | 10,000 | CC BY 4.0 | Sidewalk |
| [Navigation assistance for the visually impaired, Bangladesh](https://data.mendeley.com/datasets/m68g3h7p87) | food cart, rickshaw, stairs, pole … | 8,114 | CC BY 4.0 | **Pedestrian, eye level**: the closest analogue |
| COCO | 80 universal | 118k | Annotations CC BY 4.0; images under Flickr terms | Mixed |
| Open Images V7 | door, stairs, wheelchair … | — | Annotations CC BY 4.0; images listed as CC BY 2.0 | Mixed |
| IDD (India) / Dhaka-AI | auto-rickshaw / CNG | 10k / 4k | **Restricted** (registration, non-commercial) / **GPL-2.0** | Keep out of any redistributed set |

Source: dataset search, 2026-10-07. Roboflow owners can change licences or delete projects, and two links found during search had already disappeared. **Record the export version and date** for each source.

**Gaps:**
- **No public data for:** habal-habal, sari-sari store fronts (the Roboflow "sari-sari" set is shelf products, not shop fronts), open canals at pedestrian view.
- E-jeep data runs only to a few hundred images.
- **No Philippine dataset is documented as eye-level.**

**Licence obligations:**
- CC BY 4.0 requires attribution: keep a `DATASETS.md` crediting every source.
- Ultralytics code and weights are AGPL-3.0, including weights we train ourselves. That is fine for an open thesis repository, but a closed or commercial build would need an Ultralytics Enterprise licence. This parallels the existing MMS-TTS CC-BY-NC note in `docs/voice.md`.

## 8. What nobody has published (original contribution)

- A confusion analysis of COCO detectors on Philippine vehicles. §3 is a first illustration; the §6 test set would make it rigorous.
- Zero-shot accuracy of any open-vocabulary detector (YOLOE, YOLO-World, Grounding DINO, CLIP) on jeepney, tricycle, pedicab, tuk-tuk or becak.
- A Pi 5 latency sweep across input sizes, and per-backend RSS on ARM.
- Any Filipino assistive device using camera-based detection with released data.

## Sources not linked inline

- YOLOE paper: https://arxiv.org/abs/2503.07465; Ultralytics YOLOE docs: https://docs.ultralytics.com/models/yoloe/
- YOLO-World: https://arxiv.org/abs/2401.17270, https://github.com/AILab-CVC/YOLO-World
- Pi 5 thermals: https://www.raspberrypi.com/news/heating-and-cooling-raspberry-pi-5/
- ncnn thread defaults: https://github.com/Tencent/ncnn/blob/master/src/option.cpp
- Indian auto-rickshaw detection: https://www.cse.iitd.ac.in/~rijurekha/papers/ictd19.pdf

---

## Measured results (v1, 2026-10-08)

The primary recommendation was built: YOLO26n fine-tuned on the merged set,
NCNN, 640, resident. Pipeline and data provenance: `training/detector/`.

**Classes (33):** 25 COCO (person, bicycle, car, motorcycle, bus, truck,
traffic light, stop sign, bench, dog, cat, chair, couch, bed, dining table,
toilet, tv, laptop, cell phone, bottle, cup, backpack, umbrella, potted
plant, fire hydrant), door and stairs (Open Images), and jeepney, tricycle,
pedicab, pushcart, open_manhole, pothole. Modern jeepney was dropped (35
labelled instances in all public data) and is spoken as "bus".

**Training set:** 54,088 train / 8,144 val images after deduplication;
teacher models added 42k person boxes and ~5k other boxes to sources that
did not label them. 80 epochs, ~4.5 h on an RTX 6000 Ada. Final validation
mAP50 0.578, mAP50-95 0.422.

### Held-out Philippine test split [measured, `detector_eval`, NCNN, conf 0.3]

3,984 images from the PH sources' test splits plus held-out pedicab/pushcart
groups; never seen in training or model selection.

| | **v1** | Stock YOLO26n | yolov8m-oiv7 (previous) |
|---|---|---|---|
| Micro F1 (all classes) | **0.713** | 0.484 | 0.384 |
| Precision / recall | 0.83 / 0.62 | 0.51 / 0.47 | 0.62 / 0.28 |
| jeepney P / R (399 boxes) | **0.85 / 0.79** | 0 / 0 — "truck" 141, "bus" 72, missed 142 | 0 / 0 |
| tricycle P / R (797) | **0.80 / 0.60** | 0 / 0 | 0 / 0 |
| pedicab P / R (24) | **0.90 / 0.79** | 0 / 0 | 0 / 0 |
| pushcart R (37) | 0.35 | 0 | 0 |
| open_manhole R (24) | 0.38 | 0 | 0 |
| person R | 0.58 | 0.56 | 0.18 (labels "Man"/"Woman") |
| Median latency, gpuer CPU, 4 threads | 30 ms | 32 ms | 149 ms |

### Forgetting check: COCO regression set [measured]

2,502 COCO val2017 images never used for training or model selection.

| | v1 | Stock YOLO26n |
|---|---|---|
| Best micro F1 (over thresholds) | 0.609 (@0.15) | 0.641 (@0.25) |
| P / R at 0.3 | 0.86 / 0.42 | 0.81 / 0.52 |

v1 is more precise but finds fewer everyday objects; recall dropped most on
chair, bottle, cup, cat, dog and backpack. The 18k-image COCO replay subset
limited forgetting but did not prevent it. A larger replay share is the
standard remedy.

### Out-of-domain check: eye-level Commons photos [measured, illustrative]

The 42 curated Wikimedia Commons photos of §3 (different photographers,
eye-level, never in any training source), image level — does the spoken
description name the vehicle:

| | v1 | Stock YOLO26n |
|---|---|---|
| jeepney (9) | 2 | 0 |
| tricycle (8) | 0 | 0 |
| pedicab (8) | 1 | 0 |
| pushcart (8) | 0 | 0 |
| modern jeepney → "bus" (5) | 5 | 5 |

**This is the most important finding.** v1 learned the Philippine classes
in the training domain (F1 0.71 against 0.48) but barely transfers to close
eye-level photos — the view a chest camera has. The sample is tiny and the
tricycle/pedicab/kariton photos are near-duplicate frames of one or two
vehicles each, so it shows direction, not magnitude. Two causes are
plausible: most PH training images are CCTV, dashcam or elevated roadside
views, and the G17 export was stretched to 512×512, distorting vehicle
shape. Both point at data, not model size: the fix is a few hundred
labelled chest-height frames from the wearable's own camera (§6 already
called for them as the test set; this makes them training data too).

### Operating point [measured]

`YOLO_CONFIDENCE_THRESHOLD = 0.25`, chosen from the test-split sweep (F1
0.722 at P 0.80, within 0.005 of the peak) — see the comment in
`config.py`.

### Verified locally, not yet on the Pi

`vision.describe` through the runtime's own `IntentExecutor` and
`NCNNDetector` on the committed model: loads and warms up in 52 ms; 20 ms
per description on an M4 at 3 threads; correct nouns in both languages on
7 of 8 held-out PH images ("Nakikita ko ang isang traysikel at isang
padyak"). Pi latency, RSS and main-loop impact remain [Extrapolated] until
`detector_benchmark` runs on the device.
