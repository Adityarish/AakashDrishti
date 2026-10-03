"""Estimated heights from cast shadows (no models).

Principle (flat ground, vertical edge height H, sun elevation e):  shadow length = H / tan(e).
  * building eave height: median shadow length measured outward from the footprint edges that face away from the sun;
  * roof rise: pitched roofs add 0.5 * short-side * tan(pitch) (4:12 pitch, 18.4 deg) -- a modelled allowance, flagged;
  * tree height: distance from the crown centre to the far end of its shadow * tan(e).
Everything carries an uncertainty and a `method` so the UI can say how a number was obtained.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import HALF_PX_M  # noqa: E402
from shadows import shadow_length_m, shadow_mask  # noqa: E402

PITCH_DEG = 18.4
# (lowest eave, highest eave) in metres. Floors are physical minimums for each type, not measurements: a one-storey house
# eave is >= 2.6 m, a retail/commercial box >= 5.5 m, and shadows on soft lawn/penumbra tend to read short.
HEIGHT_LIMITS = {"house": (2.7, 9.0), "shed": (2.2, 4.2), "flat": (5.5, 14.0), "canopy": (2.6, 5.0), "greenhouse": (2.4, 4.5)}
ROOF_RISE_SHARE = 0.85   # share of the pitched-roof rise shown in the (flat-topped) 3D block, so silhouettes reach near the ridge
FALLBACK_M = {"house": 4.4, "shed": 2.6, "flat": 6.5, "canopy": 3.8, "greenhouse": 3.2}
ELEV_SIGMA_DEG = 3.0


def _crop(mosaic: np.ndarray, poly: np.ndarray, pad: int) -> tuple[np.ndarray, int, int]:
    x0, y0 = np.maximum(poly.min(0).astype(int) - pad, 0)
    x1, y1 = np.minimum(poly.max(0).astype(int) + pad + 1, [mosaic.shape[1], mosaic.shape[0]])
    return np.ascontiguousarray(mosaic[y0:y1, x0:x1]), int(x0), int(y0)


def building_height(mosaic: np.ndarray, b: dict, az_deg: float, elev_deg: float) -> dict:
    kind = b["kind"]
    poly = np.round(np.asarray(b["polygon"])).astype(np.int32)
    crop, x0, y0 = _crop(mosaic, poly, 60 if kind != "flat" else 120)
    sh = shadow_mask(crop)
    fill = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(fill, [poly - [x0, y0]], 1)
    length, n_edges = shadow_length_m(sh, fill, az_deg, max_px=260 if kind == "flat" else 160)
    tan_e = math.tan(math.radians(elev_deg))
    lo, hi = HEIGHT_LIMITS.get(kind, (2.4, 12.0))
    (_, _), (rw, rh), _ = cv2.minAreaRect(poly.astype(np.float32))
    short_m = min(rw, rh) * HALF_PX_M
    rise = 0.5 * short_m * math.tan(math.radians(PITCH_DEG)) if kind in ("house", "shed", "canopy") else 0.0
    rise = float(np.clip(rise, 0.0, 2.8))

    if not math.isnan(length) and n_edges >= 5:
        eave = float(np.clip(length * tan_e, lo, hi))
        method = "shadow"
        # per-edge spread -> uncertainty; plus the sun-elevation uncertainty
        spread = 0.18 * eave
        sigma_e = eave * (math.tan(math.radians(elev_deg + ELEV_SIGMA_DEG)) / tan_e - 1.0)
        unc = float(math.hypot(spread, sigma_e))
    else:
        eave = max(lo, FALLBACK_M.get(kind, 4.0) - rise * 0.5)
        method = "assumed"
        unc = 1.2
    area_m2 = float(b.get("area_m2") or 0.0)
    if kind == "flat":
        # large commercial roofs are taller than small shops: big box >= 8 m, mid-size >= 6.5 m (typical clear heights)
        eave = max(eave, 8.0 if area_m2 > 3000 else 6.5 if area_m2 > 800 else 5.5)
    height = float(np.clip(eave + ROOF_RISE_SHARE * rise, lo, hi + 3.0))
    return {
        "height_m": round(height, 2), "eave_m": round(eave, 2), "ridge_m": round(eave + rise, 2),
        "uncertainty_m": round(unc, 2), "height_method": method, "shadow_len_m": None if math.isnan(length) else round(length, 2),
        "shadow_edges": int(n_edges),
    }


def tree_height(mosaic: np.ndarray, tree: dict, az_deg: float, elev_deg: float) -> dict:
    cx, cy = tree["center"]
    r_px = tree["radius_px"]
    crop_r = int(r_px + 220)
    x0, y0 = max(0, int(cx) - crop_r), max(0, int(cy) - crop_r)
    x1, y1 = min(mosaic.shape[1], int(cx) + crop_r), min(mosaic.shape[0], int(cy) + crop_r)
    crop = np.ascontiguousarray(mosaic[y0:y1, x0:x1])
    sh = shadow_mask(crop)
    az = math.radians(az_deg)
    dx, dy = math.sin(az), -math.cos(az)
    px, py = cx - x0, cy - y0
    far = 0.0
    gap = 0
    for step in range(int(r_px * 0.5), 230):
        x, y = int(round(px + dx * step)), int(round(py + dy * step))
        if not (0 <= x < crop.shape[1] and 0 <= y < crop.shape[0]):
            break
        if sh[y, x]:
            far, gap = step, 0
        elif step > r_px:
            gap += 1
            if gap > 5:
                break
    tan_e = math.tan(math.radians(elev_deg))
    d_m = far * HALF_PX_M
    if far > r_px * 1.15:
        h = float(np.clip(d_m * tan_e, 3.0, 24.0))
        return {"height_m": round(h, 2), "height_method": "shadow", "uncertainty_m": round(0.25 * h + 0.8, 2)}
    h = float(np.clip(4.2 + 1.1 * r_px * HALF_PX_M, 3.0, 14.0))
    return {"height_m": round(h, 2), "height_method": "assumed", "uncertainty_m": 3.0}
