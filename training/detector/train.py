"""Fine-tune YOLO26n on the unified set, then export NCNN at the deployment sizes.

From COCO-pretrained yolo26n.pt rather than from scratch: the backbone
already knows the COCO classes, and the COCO replay subset in the data
keeps it from forgetting them while the head learns the new ones.
"""
import pathlib, shutil, sys
from ultralytics import YOLO

# Absolute: a relative `project` is nested under ultralytics' own runs/detect/.
RUN = pathlib.Path("runs").resolve() / "y26n-ph"

EPOCHS = int(sys.argv[1]) if len(sys.argv) > 1 else 80
model = YOLO("yolo26n.pt")
model.train(
    # 8 workers, batch 64: the first run used 24 workers at batch 128, filled
    # the shared box's RAM with pinned dataloader memory, and the trainer was
    # killed in its first epoch, leaving the workers hung.
    data="data/unified/val.yaml", epochs=EPOCHS, imgsz=640, batch=64, workers=8,
    patience=25, seed=0, deterministic=True, project=str(RUN.parent), name=RUN.name, exist_ok=True,
    plots=True,
)
best = YOLO(RUN / "weights" / "best.pt")
for size in (640, 416):
    path = best.export(format="ncnn", imgsz=size)
    shutil.move(path, RUN / f"yolo26n-ph_{size}_ncnn_model")
print("done")
