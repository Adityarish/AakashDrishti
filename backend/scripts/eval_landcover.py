"""Score the heuristic building/land-cover logic against GAMUS labels using GAMUS AGL as height input."""
import sys, glob
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.buildings.segment import segment_buildings_agl
from app.landcover.classify import classify_land_cover, BUILDING, TREE, ROAD, WATER

root = Path(__file__).resolve().parents[2] / "data" / "samples" / "gamus"
def iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else float("nan")
rows = []
for rgb_path in sorted(root.glob("*_rgb.png")):
    stem = rgb_path.name[:-8]
    rgb = np.array(Image.open(rgb_path).convert("RGB"))
    agl = np.load(root / f"{stem}_agl.npy")
    cls = np.array(Image.open(root / f"{stem}_cls.png"))
    seg = segment_buildings_agl(rgb, agl)
    lc = classify_land_cover(rgb, agl, seg.mask, height_is_agl=True)
    r = dict(tile=stem, bIoU=iou(lc.labels == BUILDING, cls == 3), tIoU=iou(lc.labels == TREE, cls == 6),
             rIoU=iou(lc.labels == ROAD, cls == 5), wIoU=iou(lc.labels == WATER, cls == 4), n=len(seg.footprints))
    rows.append(r)
    print({k: (round(v, 2) if isinstance(v, float) else v) for k, v in r.items()})
for k in ("bIoU", "tIoU", "rIoU", "wIoU"):
    print(k, "mean", round(float(np.nanmean([r[k] for r in rows])), 3))
