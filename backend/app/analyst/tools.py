"""Read-only scene-statistics tools exposed to the AI analyst (FR-41, FR-45).

Design rule: raw imagery and rasters never leave the machine. Every tool returns small JSON of
derived numbers only, and `guard_stats_only` enforces that in code, not just in the prompt.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import numpy as np

from app.analysis import hazards
from app.analysis.scene import Scene, load_scene
from app.landcover.classify import CLASS_NAMES

MAX_LIST_LENGTH = 64
FORBIDDEN_KEY_PARTS = ("png", "base64", "overlay", "raster", "image", "scatter")


def guard_stats_only(payload: Any, path: str = "$") -> Any:
    """Raise if a payload could carry imagery or a large array; otherwise return it unchanged."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if any(part in str(key).lower() for part in FORBIDDEN_KEY_PARTS):
                raise ValueError(f"Refusing to expose '{path}.{key}': analyst tools return statistics only.")
            guard_stats_only(value, f"{path}.{key}")
    elif isinstance(payload, (list, tuple)):
        if len(payload) > MAX_LIST_LENGTH:
            raise ValueError(f"Refusing to expose a {len(payload)}-item list at '{path}': too large for statistics.")
        for index, value in enumerate(payload):
            guard_stats_only(value, f"{path}[{index}]")
    elif isinstance(payload, str) and (payload.startswith("data:image") or len(payload) > 2000):
        raise ValueError(f"Refusing to expose a long/encoded string at '{path}'.")
    return payload


def _round(value: Any, digits: int = 3) -> Any:
    if isinstance(value, (float, np.floating)):
        return None if not np.isfinite(value) else round(float(value), digits)
    if isinstance(value, dict):
        return {k: _round(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_round(v, digits) for v in value]
    if isinstance(value, np.integer):
        return int(value)
    return value


def _meta(job_dir: Path) -> dict:
    path = job_dir / "metadata.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def get_scene_summary(job_dir: Path) -> dict:
    scene = load_scene(job_dir)
    meta = _meta(job_dir)
    finite = scene.dsm[np.isfinite(scene.dsm)]
    counts = np.bincount(scene.labels.ravel(), minlength=len(CLASS_NAMES))
    area_km2 = scene.shape[0] * scene.shape[1] * scene.px_m**2 / 1e6
    return guard_stats_only(_round({
        "mode": "absolute" if scene.kind == "absolute_dsm" else ("pseudo_metric" if scene.kind == "pseudo_metric" else "relative"),
        "height_unit": scene.unit,
        "crs": meta.get("crs"),
        "bounds_wgs84": meta.get("bounds_wgs84"),
        "pixel_size_m": scene.px_m,
        "scene_area_km2": area_km2,
        "height_min": float(finite.min()) if finite.size else None,
        "height_max": float(finite.max()) if finite.size else None,
        "height_above_ground_mean": float(np.nanmean(scene.ndsm)),
        "height_above_ground_p95": float(np.nanpercentile(scene.ndsm, 95)),
        "class_area_km2": {name: counts[i] * scene.px_m**2 / 1e6 for i, name in enumerate(CLASS_NAMES)},
        "building_count": int(len(np.unique(scene.building_labels[scene.building_labels > 0]))),
        "mean_uncertainty": float(np.nanmean(scene.uncertainty_m)),
        "calibration_scale": meta.get("calibration_scale"),
        "calibration_sources": [s["name"] for s in meta.get("calibration_sources", [])],
        "inference_seconds": (meta.get("timings") or {}).get("inference_s"),
    }))


def get_height_profile(job_dir: Path, polyline: list[list[float]] | None = None) -> dict:
    scene = load_scene(job_dir)
    h, w = scene.shape
    points = polyline if polyline and len(polyline) >= 2 else [[0.1 * w, 0.5 * h], [0.9 * w, 0.5 * h]]
    profile = hazards.elevation_profile(scene, points[0][0], points[0][1], points[-1][0], points[-1][1], samples=24)
    return guard_stats_only(_round({
        "length_m": profile["length_m"], "unit": profile["unit"], "max_rise": profile["max_rise"],
        "distance_m": profile["distance_m"], "surface": profile["surface"],
    }, 2))


def get_flood_result(job_dir: Path, level: float | None = None) -> dict:
    scene = load_scene(job_dir)
    lo, hi = hazards.flood_level_range(scene)
    chosen = level if level is not None else 0.35 * hi
    result = hazards.simulate_flood(scene, chosen)
    return guard_stats_only(_round({
        "water_level_above_reference": result["level"], "unit": result["unit"], "level_range": [lo, hi],
        "inundated_area_km2": result["area_km2"], "inundated_fraction": result["area_fraction"],
        "affected_buildings": result["affected_buildings"], "total_buildings": result["total_buildings"],
        "volume_m3": result["volume_m3"], "mean_depth": result["mean_depth"], "max_depth": result["max_depth"],
        "worst_hit_areas": result["worst_hit_areas"], "seed": result["seed"],
    }))


def get_landing_zones(job_dir: Path) -> dict:
    scene = load_scene(job_dir)
    result = hazards.landing_zones(scene, top_n=5)
    return guard_stats_only(_round({
        "sites": [{k: v for k, v in site.items() if k in ("rank", "clear_radius_m", "mean_slope_deg", "approach_clearance",
                                                        "nearest_road_m", "score", "lat", "lon")} for site in result["sites"]],
        "criteria": result["criteria"], "candidate_area_km2": result["candidate_area_km2"], "disclaimer": result["disclaimer"],
    }, 4))


def get_slope_stats(job_dir: Path) -> dict:
    scene = load_scene(job_dir)
    out = {}
    for threshold in (15, 30, 45):
        hazard = hazards.slope_hazard(scene, float(threshold))
        out[f"area_km2_above_{threshold}deg"] = hazard["area_km2"]
    finite = scene.slope[np.isfinite(scene.slope)]
    out.update({"max_slope_deg": float(finite.max()), "mean_slope_deg": float(finite.mean()),
                "p95_slope_deg": float(np.percentile(finite, 95))})
    return guard_stats_only(_round(out))


def get_validation_metrics(job_dir: Path) -> dict:
    path = job_dir / "validation_lab.json"
    if not path.is_file():
        return {"available": False, "note": "No reference data has been uploaded for this scene."}
    data = json.loads(path.read_text(encoding="utf-8"))
    keep = ("rmse", "mae", "bias", "nmad", "pearson_r", "delta1")
    return guard_stats_only(_round({
        "available": True, "reference_kind": data["reference_kind"], "aligned_before_scoring": data["aligned"],
        "global": {k: data["global"].get(k) for k in keep},
        "per_class": {name: {k: m.get(k) for k in ("rmse", "mae", "pearson_r")} for name, m in data["per_class"].items()},
        "per_landscape": {name: {k: m.get(k) for k in ("rmse", "mae", "pearson_r", "blocks")} for name, m in data["per_landscape"].items()},
    }))


def get_detected_objects(job_dir: Path) -> dict:
    """Aerial object detections (app/detect/objects.py), aggregated.

    Returns per-class counts and a small sample of the largest objects, never the full detection
    list: a busy urban scene has hundreds of vehicles and `guard_stats_only` caps list length, so
    sending them all would both trip the guard and waste the model's context.
    """
    path = job_dir / "objects.json"
    if not path.is_file():
        return {"available": False, "note": "Object detection has not run for this scene."}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("status") != "ok":
        return {"available": False, "note": data.get("note", "Object detection was skipped.")}

    objects = data.get("objects", [])
    reliable = [o for o in objects if o.get("height_reliable") and o.get("height_above_ground") is not None]
    largest = sorted(objects, key=lambda o: o.get("area_px") or 0, reverse=True)[:8]
    return guard_stats_only(_round({
        "available": True,
        "model": data.get("model"),
        "total_count": data.get("count", 0),
        "counts_by_class": data.get("counts_by_class", {}),
        "height_unit": data.get("height_unit"),
        "objects_with_reliable_height": len(reliable),
        "tallest_reliable": sorted(
            ({"label": o["label"], "height_above_ground": o["height_above_ground"],
              "surface_elevation": o.get("surface_elevation")} for o in reliable),
            key=lambda o: o["height_above_ground"], reverse=True,
        )[:5],
        "largest_objects": [
            {"label": o["label"], "confidence": o.get("confidence"), "area_px": o.get("area_px"),
             "surface_elevation": o.get("surface_elevation"), "lonlat": o.get("lonlat")}
            for o in largest
        ],
        "note": data.get("note"),
    }))


TOOLS: dict[str, Callable[..., dict]] = {
    "get_scene_summary": get_scene_summary,
    "get_detected_objects": get_detected_objects,
    "get_height_profile": get_height_profile,
    "get_flood_result": get_flood_result,
    "get_landing_zones": get_landing_zones,
    "get_slope_stats": get_slope_stats,
    "get_validation_metrics": get_validation_metrics,
}
TOOL_LABELS = {
    "get_scene_summary": "read scene summary",
    "get_detected_objects": "read detected objects",
    "get_height_profile": "read height profile",
    "get_flood_result": "read flood result",
    "get_landing_zones": "read landing zones",
    "get_slope_stats": "read slope stats",
    "get_validation_metrics": "read validation metrics",
}
