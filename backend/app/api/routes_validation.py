"""Validation lab endpoints (FR-31..FR-35): score a job against reference data, benchmark table."""

from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile

from app.analysis.scene import load_scene
from app.api.deps import get_job_store
from app.auth.service import Principal, require_analyst
from app.core.config import Settings, get_settings
from app.jobs.store import JobNotFoundError, JobStore
from app.validation import lab, selfcheck

router = APIRouter(prefix="/api/validation", tags=["validation"])

ALLOWED_REFERENCE_SUFFIXES = {".tif", ".tiff", ".png", ".npy"}


def _sanitize(value):
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _job(job_id: str, store: JobStore):
    try:
        return store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


def _register_outputs(job_id: str, store: JobStore, result: dict) -> dict:
    job = store.get(job_id)
    base = f"/api/pipeline/output/{job_id}"
    for key, name in result["images"].items():
        job.outputs[f"validation_{key}"] = f"{base}/{name}"
    job.outputs["validation_lab_json"] = f"{base}/validation_lab.json"
    job.summary = {**job.summary, "rmse": result["global"].get("rmse"), "pearson_r": result["global"].get("pearson_r")}
    store.update(job)
    scene_path = store.job_dir(job_id) / "scene.json"
    if scene_path.is_file():
        scene = json.loads(scene_path.read_text(encoding="utf-8"))
        scene.setdefault("overlays", {})["error"] = "error_map.png"
        scene_path.write_text(json.dumps(scene), encoding="utf-8")
    result["image_urls"] = {key: f"{base}/{name}" for key, name in result["images"].items()}
    return result


def _run(job_id: str, store: JobStore, path: Path, kind: str, scale: float, offset: float) -> dict:
    try:
        scene = load_scene(store.job_dir(job_id))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    try:
        reference, note = lab.read_reference(path, scene, scale, offset)
        result = lab.evaluate(scene, reference, kind, store.job_dir(job_id), note)
    except lab.ReferenceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _sanitize(_register_outputs(job_id, store, result))


@router.post("/{job_id}/reference")
async def upload_reference(
    job_id: str,
    file: UploadFile,
    reference_kind: str = Form("auto"),
    value_scale: float = Form(1.0),
    value_offset: float = Form(0.0),
    store: JobStore = Depends(get_job_store),
    principal: Principal = Depends(require_analyst),
) -> dict:
    _job(job_id, store)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_REFERENCE_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Reference must be one of {sorted(ALLOWED_REFERENCE_SUFFIXES)}")
    if reference_kind not in ("auto", "dsm", "ndsm"):
        raise HTTPException(status_code=422, detail="reference_kind must be auto, dsm or ndsm")
    target = store.job_dir(job_id) / f"reference_upload{suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(file.file, handle)
    result = _run(job_id, store, target, reference_kind, value_scale, value_offset)
    result["reference_name"] = file.filename
    result["reference_source"] = "uploaded"
    return result


@router.post("/{job_id}/sample-reference")
def use_sample_reference(job_id: str, store: JobStore = Depends(get_job_store),
                         principal: Principal = Depends(require_analyst)) -> dict:
    job = _job(job_id, store)
    path = store.job_dir(job_id) / "sample_reference.npy"
    if not job.is_sample or not path.is_file():
        raise HTTPException(status_code=404, detail="This scene has no bundled reference. Upload a LiDAR DSM instead.")
    result = _run(job_id, store, path, "ndsm", 1.0, 0.0)
    result["reference_name"] = "GAMUS reference nDSM (bundled with the sample)"
    result["reference_source"] = "bundled"
    return result


@router.get("/{job_id}/self-check")
def get_self_check(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    """Reference-free consistency check computed from the scene's own outputs (nothing to upload)."""
    _job(job_id, store)
    try:
        return _sanitize(selfcheck.self_check(store.job_dir(job_id)))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/{job_id}")
def get_validation(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    job = _job(job_id, store)
    path = store.job_dir(job_id) / "validation_lab.json"
    has_sample_reference = job.is_sample and (store.job_dir(job_id) / "sample_reference.npy").is_file()
    if not path.is_file():
        return {"status": "none", "has_sample_reference": has_sample_reference}
    result = json.loads(path.read_text(encoding="utf-8"))
    base = f"/api/pipeline/output/{job_id}"
    result["image_urls"] = {key: f"{base}/{name}" for key, name in result["images"].items()}
    result["has_sample_reference"] = has_sample_reference
    return _sanitize(result)


CONFIG_LABELS = [
    ("zero_shot_affine", "Zero-shot DA-V2 + per-tile affine", "Off-the-shelf Depth Anything V2, scale and shift fitted per tile (best case)"),
    ("finetuned_aligned", "Fine-tuned + per-tile affine", "GAMUS fine-tuned checkpoint, scale and shift fitted per tile (shows shape quality)"),
    ("finetuned_production", "Fine-tuned, production formula", "Exactly what the deployed pipeline computes, no per-tile fitting"),
]
BENCHMARK_FILE = "model/training/benchmarks/results.json"
GROUPS = ("urban", "sparse", "forested", "mixed")


def _aggregate(config: dict) -> dict | None:
    total = sum(config[g]["n"] for g in GROUPS if g in config)
    if not total:
        return None
    return {
        "rmse": (sum(config[g]["n"] * config[g]["rmse"] ** 2 for g in GROUPS if g in config) / total) ** 0.5,
        "mae": sum(config[g]["n"] * config[g]["mae"] for g in GROUPS if g in config) / total,
        "r": sum(config[g]["n"] * config[g]["r"] for g in GROUPS if g in config) / total,
        "tiles": total,
    }


@router.get("/benchmarks/table")
def benchmark_table() -> dict:
    """Landscape-stratified benchmark measured by model/training/bench.py on real GAMUS test tiles."""
    from app.core.config import REPO_ROOT

    path = REPO_ROOT / BENCHMARK_FILE
    if not path.is_file():
        return {"measured": False, "rows": [{"key": k, "label": label, "note": note, "measured": False} for k, label, note in CONFIG_LABELS],
                "note": "Benchmark not run yet (model/training/bench.py)."}
    data = _sanitize(json.loads(path.read_text(encoding="utf-8")))
    rows = []
    for key, label, note in CONFIG_LABELS:
        config = data.get(key)
        if not config:
            rows.append({"key": key, "label": label, "note": note, "measured": False})
            continue
        rows.append({"key": key, "label": label, "note": note, "measured": True, "overall": _aggregate(config),
                     **{g: ({"rmse": config[g]["rmse"], "tiles": config[g]["n"]} if g in config else None) for g in GROUPS}})
    tiles = sum(data["finetuned_production"][g]["n"] for g in GROUPS if g in data.get("finetuned_production", {}))
    return {
        "measured": True, "dataset": "GAMUS test split", "tiles": tiles,
        "protocol": "Landscape subsets come from GAMUS's own class masks. 'Per-tile affine' rows fit scale+shift per tile; the production row applies no fitting.",
        "hilly": "not measurable: GAMUS height maps normalise away terrain relief", "device": None, "rows": rows,
    }
