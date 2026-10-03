"""Fine-tune YOLOv8n-OBB (oriented boxes) on an aerial object dataset.

The deployed detector (backend/app/detect/objects.py) is a DOTA-pretrained
YOLOv8-OBB model. This script fine-tunes the nano variant on your own labelled
aerial tiles (or DOTA itself) using the Ultralytics trainer, then copies the
best weights to ml/yolo/ so they can be selected through
OBJECT_DETECTION_WEIGHTS (backend/app/core/config.py).

Dataset format: Ultralytics YOLO-OBB. One .txt per image, one line per object:
    class_id x1 y1 x2 y2 x3 y3 x4 y4        (corners, normalized to 0-1)
described by a data YAML:
    path: /abs/path/to/dataset
    train: images/train
    val: images/val
    names: {0: plane, 1: ship, 2: "storage tank", ...}

If you only have original DOTA-format annotations (x1 y1 ... x4 y4 class difficulty),
pass --convert-dota-root to convert them first with Ultralytics' own converter.

Usage:
    python ml/training/finetune_yolov8n_obb.py --data path/to/data.yaml
    python ml/training/finetune_yolov8n_obb.py --convert-dota-root D:/Datasets/DOTA --data D:/Datasets/DOTA/data.yaml
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from pathlib import Path

from ultralytics import YOLO

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- config ---
BASE_WEIGHTS = REPO_ROOT / "ml" / "yolo" / "yolov8n-obb.pt"  # falls back to auto-download by name if missing
EXPORT_PATH = REPO_ROOT / "ml" / "yolo" / "yolov8n-obb-finetuned.pt"
RUN_DIR = REPO_ROOT / "ml" / "training" / "runs"
RUN_NAME = "yolov8n_obb_finetune"

EPOCHS = 100
IMGSZ = 1024  # DOTA's standard training size; small vehicles vanish below this
BATCH = 8
PATIENCE = 20
LR0 = 1e-3  # lower than the from-scratch default (1e-2) since we start from pretrained weights
FREEZE_LAYERS = 10  # freeze the backbone (first 10 modules); set 0 to train everything
WORKERS = 4


def convert_dota(root: Path) -> None:
    """Convert DOTA-format labels under <root>/labels/{train,val}_original to YOLO-OBB."""
    from ultralytics.data.converter import convert_dota_to_yolo_obb

    convert_dota_to_yolo_obb(str(root))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--data", type=Path, required=True, help="Ultralytics data YAML")
    parser.add_argument("--convert-dota-root", type=Path, default=None, help="DOTA root to convert to YOLO-OBB first")
    parser.add_argument("--weights", type=str, default=None, help="starting weights (default: ml/yolo/yolov8n-obb.pt)")
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--imgsz", type=int, default=IMGSZ)
    parser.add_argument("--batch", type=int, default=BATCH)
    parser.add_argument("--device", type=str, default=None, help="e.g. '0', 'cpu'; default lets Ultralytics choose")
    parser.add_argument("--resume", action="store_true", help="resume the last interrupted run")
    args = parser.parse_args()

    if args.convert_dota_root is not None:
        convert_dota(args.convert_dota_root)

    if args.weights:
        weights = args.weights
    else:
        weights = str(BASE_WEIGHTS) if BASE_WEIGHTS.exists() else "yolov8n-obb.pt"

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    model = YOLO(weights, task="obb")

    start = time.time()
    model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        patience=PATIENCE,
        lr0=LR0,
        freeze=FREEZE_LAYERS,
        workers=WORKERS,
        device=args.device,
        project=str(RUN_DIR),
        name=RUN_NAME,
        exist_ok=True,
        resume=args.resume,
        # Nadir imagery has no canonical orientation or "up", so vertical flips and
        # full rotation are label-safe; mosaic helps the many tiny-object classes.
        flipud=0.5,
        fliplr=0.5,
        degrees=180.0,
        mosaic=1.0,
        amp=True,
        plots=True,
    )
    train_minutes = (time.time() - start) / 60

    best = RUN_DIR / RUN_NAME / "weights" / "best.pt"
    if not best.exists():
        raise FileNotFoundError(f"Training finished but {best} was not produced")

    # Re-validate the best checkpoint to report final OBB metrics.
    best_model = YOLO(str(best), task="obb")
    metrics = best_model.val(data=str(args.data), imgsz=args.imgsz, device=args.device)

    EXPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(best, EXPORT_PATH)

    summary = {
        "event": "done",
        "weights": str(EXPORT_PATH),
        "map50": float(metrics.box.map50),
        "map50_95": float(metrics.box.map),
        "train_minutes": train_minutes,
    }
    print(summary, flush=True)
    (RUN_DIR / RUN_NAME / "summary.json").write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
