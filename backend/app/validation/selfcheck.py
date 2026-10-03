"""Reference-free validation: checks a finished scene against evidence the scene already contains.

A real accuracy score needs ground truth (a LiDAR DSM/nDSM), which cannot be derived from the optical image
itself. What can be checked without any upload is internal consistency: how many independent scale sources
agree, how the model's building heights compare with shadow-derived heights (an independent physical
measurement), the residual against any control points, the ground-level residual, the test-time-augmentation
spread and whether the resulting building heights are plausible for their footprints.

Every figure is computed from the job's own outputs; nothing here is a substitute for scoring against reference
elevation data, and the result says so.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Optional

import numpy as np

# A single-family house footprint (m^2); above this the "tall for a house" plausibility check does not apply.
HOUSE_FOOTPRINT_M2 = 250.0
TALL_HOUSE_M = 12.0


def _pearson(a: np.ndarray, b: np.ndarray) -> Optional[float]:
    if a.size < 3 or a.std() < 1e-9 or b.std() < 1e-9:
        return None
    value = float(np.corrcoef(a, b)[0, 1])
    return value if math.isfinite(value) else None


def _check(name: str, status: str, detail: str) -> dict:
    return {"name": name, "status": status, "detail": detail}


def self_check(job_dir: Path) -> dict:
    meta_path = job_dir / "metadata.json"
    if not meta_path.is_file():
        raise FileNotFoundError("This job has no metadata yet (still running, failed, or created before this version).")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    buildings: list[dict] = []
    buildings_path = job_dir / "buildings.json"
    if buildings_path.is_file():
        buildings = json.loads(buildings_path.read_text(encoding="utf-8")).get("buildings", [])

    metric = bool(meta.get("dsm_is_metric"))
    px = float(meta.get("pixel_size_m") or 1.0)
    unit = "m" if metric else "relative units"
    sources = meta.get("calibration_sources") or []
    checks: list[dict] = []

    # ---- scale evidence
    names = [s["name"] for s in sources]
    if not metric:
        checks.append(_check("Scale evidence", "warn", "No scale evidence: heights are relative, not metres."))
    elif names == ["model_native"]:
        checks.append(_check("Scale evidence", "warn", "Only the model's native scale is available "
                             + ("(pixel size assumed). " if meta.get("gsd_assumed") else "")
                             + "Add the real GSD, a sun elevation or control points to tighten it."))
    elif len(names) == 1:
        checks.append(_check("Scale evidence", "info", f"One independent source: {names[0]}."))
    else:
        sigma = meta.get("calibration_scale_log_sigma")
        spread = f" (spread {sigma * 100:.0f}%)" if sigma is not None else ""
        checks.append(_check("Scale evidence", "pass", f"{len(names)} independent sources agree: {', '.join(names)}{spread}."))

    # ---- shadow cross-check
    pairs = [(b["height_m"], b["shadow_estimate_m"]) for b in buildings
             if metric and b.get("height_m") is not None and b.get("shadow_estimate_m") is not None
             and math.isfinite(b["height_m"]) and math.isfinite(b["shadow_estimate_m"])]
    shadow: Optional[dict] = None
    if len(pairs) >= 3:
        model = np.array([p[0] for p in pairs], dtype=np.float64)
        shade = np.array([p[1] for p in pairs], dtype=np.float64)
        diff = model - shade
        shadow = {
            "n": len(pairs), "bias": float(diff.mean()), "mae": float(np.abs(diff).mean()),
            "rmse": float(np.sqrt((diff**2).mean())), "pearson_r": _pearson(model, shade),
            "median_ratio": float(np.median(model / np.maximum(shade, 1e-6))),
            "scatter": [[float(a), float(b)] for a, b in pairs[:400]],
        }
        ratio = shadow["median_ratio"]
        r_text = f", r = {shadow['pearson_r']:.2f}" if shadow["pearson_r"] is not None else ""
        if "shadow" in names:
            # The scale was fitted to these very shadows, so a median ratio of 1 is true by construction and
            # says nothing; only the per-building spread is informative.
            shadow["circular"] = True
            checks.append(_check("Shadow cross-check", "info",
                                 f"The scale was calibrated from these shadows, so the median matches by construction. "
                                 f"Per-building spread over {len(pairs)} buildings: MAE {shadow['mae']:.1f} m{r_text}."))
        else:
            shadow["circular"] = False
            status = "pass" if 0.75 <= ratio <= 1.33 else "warn"
            checks.append(_check("Shadow cross-check", status,
                                 f"Model heights are {ratio:.2f}x the independent shadow-derived heights across "
                                 f"{len(pairs)} buildings (MAE {shadow['mae']:.1f} m{r_text})."))
    else:
        checks.append(_check("Shadow cross-check", "info", "Not available: needs a sun elevation, a known pixel size and at least 3 measurable shadows."))

    # ---- control points
    gcp = meta.get("gcp_residuals") or []
    gcp_rmse = None
    if gcp:
        errors = np.array([g["error_m"] for g in gcp], dtype=np.float64)
        gcp_rmse = float(np.sqrt((errors**2).mean()))
        checks.append(_check("Control points", "pass" if gcp_rmse < 3.0 else "warn", f"{len(gcp)} control point(s), RMSE {gcp_rmse:.2f} m."))

    # ---- ground level
    ground = meta.get("ground_residual_rmse_m")
    if ground is not None:
        checks.append(_check("Ground level", "pass" if ground < 1.0 else "warn",
                             f"Bare ground reads {ground:.2f} m above the fitted terrain (RMS); it should be near 0."))

    # ---- building plausibility
    heights = np.array([b["height_m"] for b in buildings if b.get("height_m") is not None and math.isfinite(b["height_m"])], dtype=np.float64)
    areas = np.array([b.get("area_px", 0) for b in buildings if b.get("height_m") is not None], dtype=np.float64) * px * px
    stats: Optional[dict] = None
    if heights.size:
        stats = {
            "count": int(heights.size), "median_m": float(np.median(heights)), "p90_m": float(np.percentile(heights, 90)),
            "max_m": float(heights.max()), "median_footprint_m2": float(np.median(areas)) if areas.size else None,
        }
        if metric and stats["median_footprint_m2"] is not None and stats["median_footprint_m2"] <= HOUSE_FOOTPRINT_M2 and stats["median_m"] > TALL_HOUSE_M:
            checks.append(_check("Height plausibility", "warn",
                                 f"Median building is {stats['median_m']:.1f} m tall on a {stats['median_footprint_m2']:.0f} m² footprint, tall for houses. "
                                 "The image is probably finer than the ~0.5 m/px the model was trained at: enter its real GSD."))
        elif metric:
            checks.append(_check("Height plausibility", "pass", f"Median building {stats['median_m']:.1f} m, 90th percentile {stats['p90_m']:.1f} m."))
    else:
        checks.append(_check("Height plausibility", "info", "No buildings with a usable height were detected."))

    # ---- uncertainty
    unc_mean = None
    arrays = job_dir / "arrays.npz"
    if arrays.is_file():
        with np.load(arrays) as data:
            unc = data["uncertainty"]
            unc_mean = float(np.nanmean(unc)) if np.isfinite(unc).any() else None
        if unc_mean is not None and metric:
            checks.append(_check("Model agreement", "pass" if unc_mean < 2.0 else "warn",
                                 f"Test-time-augmentation spread averages {unc_mean:.2f} m per pixel."))

    warns = sum(1 for c in checks if c["status"] == "warn")
    passes = sum(1 for c in checks if c["status"] == "pass")
    if not metric or (passes == 0 and warns == 0):
        verdict = "limited"
    elif warns == 0:
        verdict = "consistent"
    else:
        verdict = "review"

    return {
        "verdict": verdict,
        "unit": unit,
        "is_metric": metric,
        "kind": meta.get("dsm_kind"),
        "gsd_assumed": bool(meta.get("gsd_assumed")),
        "pixel_size_m": px,
        "scale": meta.get("calibration_scale"),
        "sources": sources,
        "shadow": shadow,
        "gcp_rmse_m": gcp_rmse,
        "ground_residual_rmse_m": ground,
        "uncertainty_mean_m": unc_mean,
        "buildings": stats,
        "checks": checks,
        "note": ("Internal-consistency check computed from this scene's own image and outputs. It is not an accuracy score: "
                 "that needs reference elevation data (LiDAR), which you can add below."),
    }
