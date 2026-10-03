"""Disaster-analysis and measurement endpoints (FR-26/27, FR-36..FR-40), computed from arrays.npz."""

from __future__ import annotations

import json
from typing import Literal, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.analysis import hazards, unity_scenario
from app.analysis.scene import Scene, load_scene
from app.api.deps import get_job_store
from app.auth.service import Principal, get_principal, require_responder
from app.jobs.store import JobNotFoundError, JobStore
from app.landcover.classify import CLASS_NAMES

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


def _scene(job_id: str, store: JobStore) -> Scene:
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    try:
        return load_scene(store.job_dir(job_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


class FloodBody(BaseModel):
    level: float = Field(ge=0)
    seed: str = "auto"
    col: Optional[float] = None
    row: Optional[float] = None


class LandingBody(BaseModel):
    min_radius_m: float = Field(default=15.0, gt=0)
    max_slope_deg: float = Field(default=5.0, gt=0, le=45)
    top_n: int = Field(default=8, ge=1, le=30)
    flood_level: Optional[float] = None


class SlopeBody(BaseModel):
    threshold_deg: float = Field(default=30.0, ge=1, le=89)


class ViewshedBody(BaseModel):
    col: float
    row: float
    observer_height_m: float = Field(default=2.0, ge=0)
    max_radius_m: Optional[float] = None


class ExplosionBody(BaseModel):
    col: float
    row: float
    yield_kg: float = Field(default=500.0, ge=1, le=20000)


class WildfireBody(BaseModel):
    col: float
    row: float
    hover_agl_m: float = Field(default=30.0, gt=0, le=500)
    exit_velocity_mps: float = Field(default=20.0, gt=0, le=200)


class UnityScenarioBody(BaseModel):
    """One scenario to paint onto the 3D terrain; only the fields of the chosen `kind` are read."""

    kind: Literal["flood", "landing", "explosion", "wildfire"]
    level: float = Field(default=0.0, ge=0)  # flood
    min_radius_m: float = Field(default=15.0, gt=0)  # landing
    max_slope_deg: float = Field(default=5.0, gt=0, le=45)
    flood_level: Optional[float] = None
    selected_rank: Optional[int] = None
    col: float = 0.0  # explosion / wildfire
    row: float = 0.0
    yield_kg: float = Field(default=500.0, ge=1, le=20000)
    hover_agl_m: float = Field(default=30.0, gt=0, le=500)
    exit_velocity_mps: float = Field(default=20.0, gt=0, le=200)


def _buildings(job_id: str, store: JobStore) -> list[dict]:
    path = store.job_dir(job_id) / "buildings.json"
    if not path.is_file():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("buildings", [])
    except (OSError, ValueError):
        return []


@router.get("/{job_id}/summary")
def scene_summary(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    scene = _scene(job_id, store)
    finite = scene.dsm[np.isfinite(scene.dsm)]
    counts = np.bincount(scene.labels.ravel(), minlength=len(CLASS_NAMES))
    px_area_km2 = scene.px_m**2 / 1e6
    lo, hi = flood_range = hazards.flood_level_range(scene)
    return {
        "job_id": job_id,
        "unit": scene.unit,
        "kind": scene.kind,
        "is_metric": scene.is_metric,
        "pixel_size_m": scene.px_m,
        "shape": list(scene.shape),
        "height_min": float(finite.min()) if finite.size else None,
        "height_max": float(finite.max()) if finite.size else None,
        "ndsm_mean": float(np.nanmean(scene.ndsm)),
        "ndsm_p95": float(np.nanpercentile(scene.ndsm, 95)),
        "class_area_km2": {name: float(counts[i] * px_area_km2) for i, name in enumerate(CLASS_NAMES)},
        "class_fraction": {name: float(counts[i] / scene.labels.size) for i, name in enumerate(CLASS_NAMES)},
        "building_count": int(len(np.unique(scene.building_labels[scene.building_labels > 0]))),
        "flood_level_range": [lo, hi],
        "flood_reference_elevation": hazards.flood_reference_level(scene),
        "max_slope_deg": float(np.nanmax(scene.slope)),
        "mean_uncertainty": float(np.nanmean(scene.uncertainty_m)),
    }


@router.get("/{job_id}/objects")
def detected_objects(job_id: str, store: JobStore = Depends(get_job_store),
                     label: Optional[str] = Query(None, description="Only return objects of this class"),
                     limit: int = Query(500, ge=1, le=5000)) -> dict:
    """Aerial objects detected for this scene, with the elevations sampled from its height field
    (app/detect/objects.py). A busy urban scene holds hundreds of vehicles, so the list is capped
    by `limit` (highest confidence first) while the counts always describe the full set."""
    path = store.job_dir(job_id) / "objects.json"
    if not path.is_file():
        return {"job_id": job_id, "status": "unavailable", "count": 0, "objects": [],
                "note": "Object detection has not run for this scene (it predates the feature, or was skipped)."}
    data = json.loads(path.read_text(encoding="utf-8"))
    objects = data.get("objects", [])
    if label:
        objects = [o for o in objects if o.get("label") == label]
    data["returned"] = min(len(objects), limit)
    data["objects"] = objects[:limit]
    return data


@router.post("/{job_id}/flood")
def flood(job_id: str, body: FloodBody, store: JobStore = Depends(get_job_store),
          principal: Principal = Depends(require_responder)) -> dict:
    return hazards.simulate_flood(_scene(job_id, store), body.level, body.seed, body.col, body.row)


@router.post("/{job_id}/landing-zones")
def landing_zones(job_id: str, body: LandingBody, store: JobStore = Depends(get_job_store),
                  principal: Principal = Depends(require_responder)) -> dict:
    return hazards.landing_zones(_scene(job_id, store), body.min_radius_m, body.max_slope_deg, top_n=body.top_n,
                                 flood_level=body.flood_level)


@router.post("/{job_id}/slope-hazard")
def slope_hazard(job_id: str, body: SlopeBody, store: JobStore = Depends(get_job_store),
                 principal: Principal = Depends(require_responder)) -> dict:
    return hazards.slope_hazard(_scene(job_id, store), body.threshold_deg)


@router.post("/{job_id}/viewshed")
def viewshed(job_id: str, body: ViewshedBody, store: JobStore = Depends(get_job_store),
             principal: Principal = Depends(require_responder)) -> dict:
    return hazards.viewshed(_scene(job_id, store), body.col, body.row, body.observer_height_m, body.max_radius_m)


@router.get("/{job_id}/profile")
def profile(job_id: str, x0: float = Query(...), y0: float = Query(...), x1: float = Query(...), y1: float = Query(...),
            samples: int = 256, store: JobStore = Depends(get_job_store)) -> dict:
    return hazards.elevation_profile(_scene(job_id, store), x0, y0, x1, y1, samples)


@router.get("/{job_id}/probe")
def probe(job_id: str, col: float = Query(...), row: float = Query(...), store: JobStore = Depends(get_job_store)) -> dict:
    scene = _scene(job_id, store)
    r, c = int(round(row)), int(round(col))
    if not (0 <= r < scene.shape[0] and 0 <= c < scene.shape[1]):
        raise HTTPException(status_code=422, detail="Point is outside the scene.")
    lonlat = scene.pixel_to_lonlat(c, r)
    return {
        "col": c, "row": r, "elevation": float(scene.dsm[r, c]), "height_above_ground": float(scene.ndsm[r, c]),
        "uncertainty": float(scene.uncertainty_m[r, c]), "slope_deg": float(scene.slope[r, c]),
        "land_cover": CLASS_NAMES[int(scene.labels[r, c])], "lon": lonlat[0] if lonlat else None,
        "lat": lonlat[1] if lonlat else None, "unit": scene.unit,
    }


@router.post("/{job_id}/explosion")
def explosion(job_id: str, body: ExplosionBody, store: JobStore = Depends(get_job_store),
              principal: Principal = Depends(require_responder)) -> dict:
    try:
        return hazards.explosion_impact(_scene(job_id, store), _buildings(job_id, store), body.col, body.row, body.yield_kg)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{job_id}/wildfire-drone")
def wildfire_drone(job_id: str, body: WildfireBody, store: JobStore = Depends(get_job_store),
                   principal: Principal = Depends(require_responder)) -> dict:
    try:
        return hazards.wildfire_drop(_scene(job_id, store), body.col, body.row, body.hover_agl_m, body.exit_velocity_mps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _legend(*entries: tuple[str, str]) -> list[dict]:
    return [{"level": level, "color": unity_scenario.LEVEL_COLORS[level], "label": label} for level, label in entries]


@router.post("/{job_id}/unity-scenario")
def unity_scenario_bundle(job_id: str, body: UnityScenarioBody, store: JobStore = Depends(get_job_store),
                          principal: Principal = Depends(require_responder)) -> dict:
    """Write a copy of the job's Unity scene whose zones are this scenario, for the 3D viewer to load."""
    scene = _scene(job_id, store)
    job_dir = store.job_dir(job_id)
    zones = unity_scenario.Zones()
    px = scene.px_m
    h, w = scene.shape

    if body.kind == "flood":
        flood = hazards.simulate_flood(scene, body.level, keep_mask=True)
        if not flood["terrain_available"]:
            return {"available": False, "note": flood["note"]}
        depth, mask = flood["_depth"], flood["_mask"]
        zones.add_mask("flood", "low", mask & (depth <= 0.5))
        zones.add_mask("flood", "medium", mask & (depth > 0.5) & (depth <= 1.5))
        zones.add_mask("flood", "high", mask & (depth > 1.5))
        legend = _legend(("low", "Shallow (up to 0.5 m)"), ("medium", "0.5 to 1.5 m"), ("high", "Deeper than 1.5 m"))
        tag = f"flood_{body.level:.2f}"
    elif body.kind == "landing":
        result = hazards.landing_zones(scene, body.min_radius_m, body.max_slope_deg, top_n=8, flood_level=body.flood_level)
        for site in result["sites"]:
            selected = body.selected_rank == site["rank"]
            zones.add_disc("landing_zone", "high" if selected else "low", site["col"], site["row"], site["clear_radius_m"] / px)
        legend = _legend(("low", "Candidate site"), ("high", "Selected site"))
        tag = f"landing_{body.min_radius_m:g}_{body.max_slope_deg:g}_{body.flood_level}_{body.selected_rank}"
    elif body.kind == "explosion":
        result = hazards.explosion_impact(scene, _buildings(job_id, store), body.col, body.row, body.yield_kg)
        level_of = {"light": "low", "moderate": "medium", "severe": "high"}
        for band in reversed(result["bands"]):  # widest first; the viewer paints higher levels on top anyway
            zones.add_disc("explosion", level_of[band["severity"]], body.col, body.row, band["radius_px"])
        legend = _legend(("low", "Light damage"), ("medium", "Moderate damage"), ("high", "Severe damage"))
        tag = f"blast_{int(body.col)}_{int(body.row)}_{body.yield_kg:g}"
    else:
        result = hazards.wildfire_drop(scene, body.col, body.row, body.hover_agl_m, body.exit_velocity_mps)
        if result.get("status") != "computed":
            return {"available": False, "note": result.get("note")}
        zones.add_disc("wildfire", "high", body.col, body.row, max(3.0 / px, 2.0))
        zones.add_ring("wildfire", "medium", body.col, body.row, result["reach_px"], max(2.0 / px, 1.5))
        legend = _legend(("high", "Fire location"), ("medium", "Drone standoff ring"))
        tag = f"fire_{int(body.col)}_{int(body.row)}_{body.hover_agl_m:g}_{body.exit_velocity_mps:g}"

    base_file = job_dir / "unity_scene.json"
    stamp = int(base_file.stat().st_mtime) if base_file.is_file() else 0
    try:
        written = unity_scenario.write_bundle(job_dir, job_id, f"{unity_scenario.slugify(tag)}_{stamp}", zones, (h, w),
                                              {"kind": body.kind})
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"available": True, "legend": legend, **written}
