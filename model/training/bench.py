"""Landscape-stratified benchmark: zero-shot Depth Anything V2 vs. the GAMUS
fine-tuned checkpoint, broken down by urban / sparse / forested / mixed
scenes -- exactly the comparison the SIH-26175 evaluation criteria ask for
("performance stability across urban, sparse, hilly, and forested
landscapes").

Landscape subset rule (from GAMUS's own 7-class CLS masks: 0 background,
1 ground, 2 low vegetation, 3 buildings, 4 water, 5 road, 6 tree -- mapping
confirmed against the EarthNets/RSI-MMSegmentation GAMUS docs, not
guessed):
  urban    -- building fraction > 0.2
  sparse   -- building fraction < 0.05 and low-vegetation fraction > 0.3
  forested -- tree fraction > 0.4
  mixed    -- everything else

NOTE on "hilly": the PS also asks for a hilly-terrain subset, defined
upstream as "co-located DEM relief > 50m". GAMUS's height maps are AGL
(height above LOCAL ground), not absolute elevation, so broad terrain
slope/relief is normalized away by construction -- there is no way to
recover "hilly" from this data without a separate bare-earth DEM, which
is not bundled locally. Rather than fabricate a proxy, this script omits
a "hilly" subset and says so in the output; add one only when a real DEM
tile is available (see app/calibration/srtm.py for the DEM-loading
pattern this project already uses elsewhere).

Usage: model/training/.venv/Scripts/python.exe bench.py [--n-per-subset N]
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import h5py
import numpy as np
import torch

from gamus_dataset import IMAGENET_MEAN, IMAGENET_STD, index_split

REPO_ROOT = Path(__file__).resolve().parents[2]
GAMUS_ROOT = Path(r"D:\Datasets\GAMUS")
STOCK_CHECKPOINT = REPO_ROOT / "model" / "depth_anything_v2_vitb.pth"
FINETUNED_CHECKPOINT = REPO_ROOT / "model" / "depth_anything_v2_vitb_gamus_best.pth"
OUT_DIR = Path(__file__).resolve().parent / "benchmarks"

# Same convention as backend/app/core/config.py's DA_V2_HEIGHT_SCALE, so the "production"
# row reflects what the deployed pipeline actually outputs, not just an ideal per-tile fit.
PRODUCTION_HEIGHT_SCALE = 2.6
PRODUCTION_GROUND_PERCENTILE = 2.0

CLASS_BUILDING, CLASS_LOW_VEG, CLASS_TREE = 3, 2, 6


def classify_landscape(cls_mask: np.ndarray) -> str:
    total = cls_mask.size
    building_frac = float((cls_mask == CLASS_BUILDING).sum()) / total
    veg_frac = float((cls_mask == CLASS_LOW_VEG).sum()) / total
    tree_frac = float((cls_mask == CLASS_TREE).sum()) / total
    if building_frac > 0.2:
        return "urban"
    if tree_frac > 0.4:
        return "forested"
    if building_frac < 0.05 and veg_frac > 0.3:
        return "sparse"
    return "mixed"


def load_model(checkpoint: Path, device: torch.device):
    import sys

    sys.path.insert(0, str(REPO_ROOT / "model" / "Depth-Anything-V2"))
    from depth_anything_v2.dpt import DepthAnythingV2

    model = DepthAnythingV2(encoder="vitb", features=128, out_channels=[96, 192, 384, 768])
    model.load_state_dict(torch.load(checkpoint, map_location="cpu"))
    return model.to(device).eval()


def infer(model, image_rgb_uint8: np.ndarray, device: torch.device, size: int = 518) -> np.ndarray:
    img = cv2.resize(image_rgb_uint8, (size, size), interpolation=cv2.INTER_CUBIC)
    img_f = (img.astype(np.float32) / 255.0 - IMAGENET_MEAN) / IMAGENET_STD
    tensor = torch.from_numpy(np.transpose(img_f, (2, 0, 1))).float().unsqueeze(0).to(device)
    with torch.inference_mode():
        pred = model(tensor)
    pred = pred.squeeze().cpu().numpy()
    return cv2.resize(pred, (image_rgb_uint8.shape[1], image_rgb_uint8.shape[0]), interpolation=cv2.INTER_LINEAR)


def robust_affine_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    design = np.vstack([x, np.ones_like(x)]).T
    (a, b), *_ = np.linalg.lstsq(design, y, rcond=None)
    if not np.isfinite(a) or a <= 0:
        return 1.0, 0.0
    return float(a), float(b)


def metrics(pred: np.ndarray, gt: np.ndarray, aligned: bool) -> dict:
    if aligned:
        a, b = robust_affine_fit(pred, gt)
        pred = a * pred + b
    residual = pred - gt
    rmse = float(np.sqrt(np.mean(residual**2)))
    mae = float(np.mean(np.abs(residual)))
    r = float(np.corrcoef(pred, gt)[0, 1]) if np.std(pred) > 1e-9 else 0.0
    return {"rmse": rmse, "mae": mae, "r": r}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n-per-subset", type=int, default=15)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    pairs = index_split(GAMUS_ROOT, "test")
    class_dir = GAMUS_ROOT / "classes" / "test"
    print(f"Indexing landscape subset for {len(pairs)} test tiles...")

    by_subset: dict[str, list] = {"urban": [], "sparse": [], "forested": [], "mixed": []}
    for pair in pairs:
        cls_path = class_dir / f"{pair.tile_id}_CLS.h5"
        if not cls_path.is_file():
            continue
        with h5py.File(cls_path, "r") as f:
            cls_mask = f["image"][()]
        by_subset[classify_landscape(cls_mask)].append(pair)

    rng = np.random.default_rng(args.seed)
    sampled: dict[str, list] = {}
    for subset, items in by_subset.items():
        n = min(args.n_per_subset, len(items))
        idx = rng.choice(len(items), size=n, replace=False) if items else []
        sampled[subset] = [items[i] for i in sorted(idx)]
        print(f"  {subset}: {len(items)} available, sampling {n}")

    print("Loading models...")
    stock_model = load_model(STOCK_CHECKPOINT, device)
    finetuned_model = load_model(FINETUNED_CHECKPOINT, device)

    rows: dict[str, dict[str, list]] = {
        "zero_shot_affine": {s: [] for s in sampled},
        "finetuned_aligned": {s: [] for s in sampled},
        "finetuned_production": {s: [] for s in sampled},
    }

    t0 = time.time()
    n_done = 0
    n_total = sum(len(v) for v in sampled.values())
    for subset, items in sampled.items():
        for pair in items:
            with h5py.File(pair.image_path, "r") as f:
                image = f["image"][()]
            with h5py.File(pair.height_path, "r") as f:
                gt = f["image"][()].astype(np.float32)
            valid = np.isfinite(gt) & (gt >= 0)
            if valid.sum() < 1000:
                continue

            stock_pred = infer(stock_model, image, device)
            ft_pred = infer(finetuned_model, image, device)

            x_gt = gt[valid].astype(np.float64)
            rows["zero_shot_affine"][subset].append(metrics(stock_pred[valid].astype(np.float64), x_gt, aligned=True))
            rows["finetuned_aligned"][subset].append(metrics(ft_pred[valid].astype(np.float64), x_gt, aligned=True))

            ground = float(np.percentile(ft_pred, PRODUCTION_GROUND_PERCENTILE))
            production_pred = np.clip(ft_pred - ground, 0.0, None) * PRODUCTION_HEIGHT_SCALE
            rows["finetuned_production"][subset].append(
                metrics(production_pred[valid].astype(np.float64), x_gt, aligned=False)
            )

            n_done += 1
            if n_done % 5 == 0:
                print(f"  {n_done}/{n_total} tiles ({time.time()-t0:.0f}s)")

    del stock_model, finetuned_model
    if device.type == "cuda":
        torch.cuda.empty_cache()

    OUT_DIR.mkdir(exist_ok=True)
    summary: dict[str, dict[str, dict]] = {}
    for config, subsets in rows.items():
        summary[config] = {}
        for subset, ms in subsets.items():
            if not ms:
                summary[config][subset] = None
                continue
            summary[config][subset] = {
                "n": len(ms),
                "rmse": float(np.mean([m["rmse"] for m in ms])),
                "mae": float(np.mean([m["mae"] for m in ms])),
                "r": float(np.mean([m["r"] for m in ms])),
            }
    (OUT_DIR / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    config_labels = {
        "zero_shot_affine": "Zero-shot DA-V2 + per-tile affine fit",
        "finetuned_aligned": "Fine-tuned DA-V2 + per-tile affine fit",
        "finetuned_production": "Fine-tuned DA-V2, production formula (no per-tile fit)",
    }
    subset_order = ["urban", "sparse", "forested", "mixed"]

    lines = [
        "# DepthWizard / AakashDrishti -- Landscape-Stratified Benchmark",
        "",
        f"GAMUS test split, {n_done} tiles sampled ({args.n_per_subset} per available subset, seed={args.seed}).",
        "Landscape subset from GAMUS's own 7-class CLS masks (urban: building frac > 0.2; "
        "sparse: building frac < 0.05 and low-veg frac > 0.3; forested: tree frac > 0.4; "
        "mixed: everything else). No 'hilly' subset -- GAMUS's AGL height maps normalize away "
        "broad terrain relief by construction, so it cannot be recovered without a separate "
        "bare-earth DEM (not bundled locally); see this script's docstring.",
        "",
        "RMSE and MAE in meters. r = Pearson correlation. 'Aligned' rows fit a per-tile scale+shift "
        "(best case, shows how well the model's SHAPE matches truth); the production row uses the "
        "exact formula the deployed pipeline runs (app/fusion/edge_aware.py::build_height_field), "
        "with no per-tile fitting -- the real number a user would see.",
        "",
        "| Config | " + " | ".join(f"{s} RMSE (n)" for s in subset_order) + " | Mean MAE | Mean r |",
        "|---|" + "---|" * (len(subset_order) + 2),
    ]
    for config, subsets in summary.items():
        cells = []
        maes, rs = [], []
        for s in subset_order:
            v = subsets.get(s)
            if v is None:
                cells.append("n/a")
            else:
                cells.append(f"{v['rmse']:.2f} ({v['n']})")
                maes.append(v["mae"])
                rs.append(v["r"])
        mean_mae = f"{np.mean(maes):.2f}" if maes else "n/a"
        mean_r = f"{np.mean(rs):.3f}" if rs else "n/a"
        lines.append(f"| {config_labels[config]} | " + " | ".join(cells) + f" | {mean_mae} | {mean_r} |")

    (OUT_DIR / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nWrote {OUT_DIR / 'results.md'} and {OUT_DIR / 'results.json'}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
