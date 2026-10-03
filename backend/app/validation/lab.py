"""Validation lab: score a job's DSM against a user-supplied reference (LiDAR DSM / nDSM).

Alignment: georeferenced pairs are reprojected onto the scene grid; otherwise the reference is
resampled to the scene shape. Metrics: RMSE, MAE, bias, NMAD, Pearson r, delta1 - global, per land-
cover class, and per landscape type (urban / sparse / hilly / forested, derived block-wise from
class composition). Nothing is reported that was not computed from the supplied reference.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from scipy import ndimage

from app.analysis.scene import Scene
from app.export.rasters import ERROR_STOPS, HEIGHT_STOPS, apply_colormap, save_png
from app.landcover.classify import BUILDING, CLASS_NAMES, TREE, LOW_VEG

MIN_PIXELS = 400


class ReferenceError(ValueError):
    pass


def read_reference(path: Path, scene: Scene, value_scale: float = 1.0, value_offset: float = 0.0) -> tuple[np.ndarray, str]:
    """Load the reference onto the scene grid. Returns (array, alignment note)."""
    h, w = scene.shape
    if path.suffix.lower() == ".npy":
        arr = np.load(path).astype(np.float32)
        if arr.ndim != 2:
            raise ReferenceError("A .npy reference must be a 2D array.")
        note = "resampled by shape (.npy has no georeferencing)"
        if arr.shape != (h, w):
            arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR)
        return arr * value_scale + value_offset, note

    try:
        with rasterio.open(path) as src:
            if src.count < 1:
                raise ReferenceError("Reference raster has no bands.")
            ref_georef = src.crs is not None and not src.transform.is_identity
            if scene.geo is not None and ref_georef:
                out = np.full((h, w), np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(src, 1), destination=out, src_transform=src.transform, src_crs=src.crs,
                    src_nodata=src.nodata, dst_transform=rasterio.Affine(*scene.geo.transform), dst_crs=scene.geo.crs,
                    dst_nodata=np.nan, resampling=Resampling.bilinear,
                )
                return out * value_scale + value_offset, "reprojected onto the scene grid (CRS-aware)"
            arr = src.read(1).astype(np.float32)
            if src.nodata is not None:
                arr[arr == src.nodata] = np.nan
    except rasterio.errors.RasterioIOError as exc:
        raise ReferenceError(f"Could not read the reference raster: {exc}") from exc

    if arr.shape != (h, w):
        arr = cv2.resize(arr, (w, h), interpolation=cv2.INTER_LINEAR)
    return arr * value_scale + value_offset, "resampled by shape (reference or scene has no georeferencing)"


def _metrics(pred: np.ndarray, ref: np.ndarray) -> dict:
    diff = pred - ref
    n = int(diff.size)
    if n < MIN_PIXELS:
        return {"n": n}
    med = float(np.median(diff))
    out = {
        "n": n,
        "rmse": float(np.sqrt(np.mean(diff**2))),
        "mae": float(np.mean(np.abs(diff))),
        "bias": float(np.mean(diff)),
        "nmad": float(1.4826 * np.median(np.abs(diff - med))),
    }
    out["pearson_r"] = float(np.corrcoef(pred, ref)[0, 1]) if pred.std() > 1e-9 and ref.std() > 1e-9 else None
    positive = (pred > 0.5) & (ref > 0.5)
    if positive.sum() >= 50:
        ratio = np.maximum(pred[positive] / ref[positive], ref[positive] / pred[positive])
        out["delta1"] = float((ratio < 1.25).mean())
    else:
        out["delta1"] = None
    return out


def _landscape_of(block_labels: np.ndarray, block_terrain: np.ndarray) -> Optional[str]:
    total = block_labels.size
    building = float((block_labels == BUILDING).sum()) / total
    tree = float((block_labels == TREE).sum()) / total
    veg = float(np.isin(block_labels, [TREE, LOW_VEG]).sum()) / total
    finite = block_terrain[np.isfinite(block_terrain)]
    relief = float(finite.max() - finite.min()) if finite.size else 0.0
    if relief > 15.0:
        return "hilly"
    if building > 0.2:
        return "urban"
    if tree > 0.4:
        return "forested"
    if building < 0.05 and veg > 0.3:
        return "sparse"
    if building < 0.05:
        return "sparse"
    return None


def evaluate(
    scene: Scene, reference: np.ndarray, reference_kind: str, out_dir: Path, note: str
) -> dict:
    kind = reference_kind
    finite_ref = reference[np.isfinite(reference)]
    if kind == "auto":
        kind = "ndsm" if finite_ref.size and float(np.nanpercentile(finite_ref, 1)) >= -1.0 and float(np.nanpercentile(finite_ref, 50)) < 15.0 else "dsm"

    pred_full = scene.ndsm if kind == "ndsm" else scene.dsm
    valid = np.isfinite(pred_full) & np.isfinite(reference)
    if valid.sum() < MIN_PIXELS:
        raise ReferenceError("The reference and the scene overlap on too few valid pixels to score.")

    caveats: list[str] = []
    pred = pred_full.copy()
    aligned = False
    if not scene.is_metric:
        x, y = pred[valid].astype(np.float64), reference[valid].astype(np.float64)
        design = np.stack([x, np.ones_like(x)], axis=1)
        (a, b), *_ = np.linalg.lstsq(design, y, rcond=None)
        pred = a * pred + b
        aligned = True
        caveats.append("The scene DSM is relative, so predictions were scale-and-shift aligned to the reference "
                       "before scoring (SSI-style). Errors are not absolute.")
    elif kind == "dsm" and scene.kind == "pseudo_metric":
        offset = float(np.nanmedian(reference[valid] - pred[valid]))
        pred = pred + offset
        aligned = True
        caveats.append("The scene has no absolute datum, so a constant offset was removed before scoring.")

    p, r = pred[valid], reference[valid]
    global_metrics = _metrics(p, r)

    per_class = {}
    for index, name in enumerate(CLASS_NAMES):
        mask = valid & (scene.labels == index)
        if mask.sum() >= MIN_PIXELS:
            per_class[name] = _metrics(pred[mask], reference[mask])

    block = max(64, min(scene.shape) // 8)
    landscape_pixels: dict[str, list[tuple[np.ndarray, np.ndarray]]] = {}
    landscape_blocks: dict[str, int] = {}
    for r0 in range(0, scene.shape[0] - block // 2, block):
        for c0 in range(0, scene.shape[1] - block // 2, block):
            sl = (slice(r0, r0 + block), slice(c0, c0 + block))
            v = valid[sl]
            if v.sum() < block * block * 0.5:
                continue
            label = _landscape_of(scene.labels[sl], scene.terrain[sl])
            if label is None:
                continue
            landscape_blocks[label] = landscape_blocks.get(label, 0) + 1
            landscape_pixels.setdefault(label, []).append((pred[sl][v], reference[sl][v]))
    per_landscape = {}
    for label, chunks in landscape_pixels.items():
        m = _metrics(np.concatenate([c[0] for c in chunks]), np.concatenate([c[1] for c in chunks]))
        m["blocks"] = landscape_blocks[label]
        per_landscape[label] = m

    error = np.where(valid, pred - reference, np.nan).astype(np.float32)
    span = float(np.nanpercentile(np.abs(error[valid]), 95)) or 1.0
    error_rgb = apply_colormap(0.5 + 0.5 * np.clip(np.nan_to_num(error, nan=0.0) / span, -1, 1), ERROR_STOPS)
    error_rgba = np.dstack([error_rgb, np.where(valid, 255, 0).astype(np.uint8)])
    save_png(error_rgba, out_dir / "error_map.png")

    lo = float(np.nanpercentile(np.concatenate([p, r]), 1))
    hi = float(np.nanpercentile(np.concatenate([p, r]), 99))
    common = lambda a: apply_colormap(np.clip((a - lo) / max(hi - lo, 1e-9), 0, 1), HEIGHT_STOPS)  # noqa: E731
    save_png(common(np.where(valid, pred, np.nan)), out_dir / "compare_pred.png")
    save_png(common(np.where(np.isfinite(reference), reference, np.nan)), out_dir / "compare_reference.png")

    # Raw rasters (little-endian float32, NaN = no data) so the UI can read values under the cursor.
    np.where(valid, pred, np.nan).astype("<f4").tofile(out_dir / "lab_pred.f32")
    np.where(np.isfinite(reference), reference, np.nan).astype("<f4").tofile(out_dir / "lab_reference.f32")

    rng = np.random.default_rng(3)
    idx = rng.choice(p.size, size=min(4000, p.size), replace=False)
    scatter = [[float(r[i]), float(p[i])] for i in idx]
    counts, edges = np.histogram(np.clip(p - r, -span * 3, span * 3), bins=41)

    dem_only = None
    if scene.is_metric and scene.kind == "absolute_dsm" and kind == "dsm":
        d = scene.terrain
        vv = np.isfinite(d) & np.isfinite(reference)
        if vv.sum() >= MIN_PIXELS:
            dem_only = _metrics(d[vv], reference[vv])

    result = {
        "status": "ok",
        "reference_kind": kind,
        "alignment": note,
        "aligned": aligned,
        "caveats": caveats,
        "global": global_metrics,
        "per_class": per_class,
        "per_landscape": per_landscape,
        "dem_only": dem_only,
        "scatter": scatter,
        "error_histogram": {"counts": counts.tolist(), "edges": edges.tolist()},
        "error_scale_m": span,
        "value_range": [lo, hi],
        "unit": scene.unit,
        "images": {
            "error_map": "error_map.png", "compare_pred": "compare_pred.png", "compare_reference": "compare_reference.png",
        },
    }
    (out_dir / "validation_lab.json").write_text(json.dumps(result), encoding="utf-8")
    return result
