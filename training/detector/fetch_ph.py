"""Download the Philippine source datasets. Keys are read from files, never printed."""
import os, pathlib, subprocess, json, datetime

ROOT = pathlib.Path("raw")
RF_PROJECTS = [  # (workspace, project) — all CC BY 4.0 per their Universe pages, 2026-10-07
    ("groups-workspace", "g17-datasets"),
    ("vehicle-detection-and-data-generation", "ph-vehicles-728sm"),
    ("vehicle-detection-gads7", "vehicle-detection-yolo-v11-amnce"),
    ("thesis-datasets-at8oz", "kariton"),
    ("inacap-rp6mt", "cityfix-projects2"),
]
manifest = []

# Kaggle — the CLI reads ~/.kaggle/access_token itself.
kdir = ROOT / "kaggle_dlsud"
if not kdir.exists():
    subprocess.run([".venv/bin/kaggle", "datasets", "download", "-d",
                    "jancarloparedes/philippine-vehicle-classification-14class", "-p", str(kdir), "--unzip"], check=True)
manifest.append({"source": "kaggle:jancarloparedes/philippine-vehicle-classification-14class", "licence": "CC BY 4.0", "dir": str(kdir)})

from roboflow import Roboflow
rf = Roboflow(api_key=pathlib.Path(".roboflow_key").read_text().strip())
for ws, proj in RF_PROJECTS:
    p = rf.workspace(ws).project(proj)
    versions = [int(str(x.version).split("/")[-1]) for x in p.versions()]
    if not versions:
        print(proj, "has no exportable version, skipped", flush=True)
        continue
    v = max(versions)
    out = ROOT / f"rf_{proj}_v{v}"
    if not out.exists():
        p.version(v).download("yolov8", location=str(out), overwrite=False)
    manifest.append({"source": f"roboflow:{ws}/{proj}/{v}", "licence": "CC BY 4.0", "dir": str(out),
                     "fetched": datetime.date.today().isoformat()})
    print(proj, v, flush=True)
(ROOT / "sources.json").write_text(json.dumps(manifest, indent=1))
print("done")
