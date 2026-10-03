"""Pipeline execution, status, and output-serving endpoints.

Matches the frontend contract in frontend/src/lib/api/pipeline.ts exactly:
  POST /api/pipeline/run/{job_id}
  GET  /api/pipeline/{job_id}

Processing runs as a FastAPI BackgroundTask so the HTTP request returns
immediately with the current job state; the frontend polls GET .../{job_id}
for real progress (IMPLEMENTATION.md Section 10).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from fastapi import APIRouter, BackgroundTasks, Body, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.api.deps import get_job_store
from app.auth.service import Principal, require_analyst, require_responder
from app.buildings.disaster import assess_aircraft_fit
from app.buildings.height import BuildingHeight, scale_buildings_to_reference, scale_buildings_to_reference_multi
from app.buildings.scenarios import (
    _sanitize_level_for_filename,
    compute_drone_water_drop,
    compute_viewshed,
    save_flood_preview,
    save_viewshed_preview,
    simulate_explosion_impact,
    simulate_flood_level,
)
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.export.report import generate_pdf_report
from app.input.detect import GeoMetadata
from app.jobs.models import JobStage, RunOptions, default_steps
from app.jobs.store import JobNotFoundError, JobStore
from app.schemas.pipeline import (
    BuildingsResponse,
    DisasterZonesResponse,
    ExplosionImpactRequest,
    ExplosionImpactResponse,
    FloodSimulationRequest,
    FloodSimulationResponse,
    JobListResponse,
    JobStatusResponse,
    JobSummary,
    ReferenceScaledBuildingsMultiResponse,
    ReferenceScaledBuildingsResponse,
    ReferenceScaleMultiRequest,
    ReferenceScaleRequest,
    ReportResponse,
    ValidationResponse,
    ViewshedRequest,
    ViewshedResponse,
    WildfireDroneRequest,
    WildfireDroneResponse,
)

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])
logger = get_logger(__name__)

# Stages that mean "a background run is already in flight" -- starting a
# second run concurrently would load a second copy of the depth models and
# blow past the 8GB VRAM budget (CLAUDE.md Section 5), so it's rejected.
_IN_PROGRESS_STAGES = {
    JobStage.VALIDATING,
    JobStage.DEPTH,
    JobStage.FUSION,
    JobStage.CALIBRATION,
    JobStage.DSM,
    JobStage.MESH,
}

# Approximate, monotonic progress for UI display. Reflects real stage
# transitions the job store actually persisted -- not a fabricated timer.
_STAGE_PROGRESS: dict[JobStage, int] = {
    JobStage.UPLOADED: 0,
    JobStage.VALIDATING: 10,
    JobStage.DEPTH: 35,
    JobStage.FUSION: 55,
    JobStage.CALIBRATION: 65,
    JobStage.DSM: 80,
    JobStage.MESH: 92,
    JobStage.READY: 100,
    JobStage.FAILED: 0,
}


_ACTIVE: set[str] = set()


def _run_tracked(job_id: str, store: JobStore, settings: Settings) -> None:
    from app.pipeline.run import execute_pipeline  # heavy (torch); imported only when a run starts

    try:
        execute_pipeline(job_id, store, settings)
    finally:
        _ACTIVE.discard(job_id)


def fail_orphaned_jobs(store: JobStore) -> int:
    """Jobs left mid-run by a killed server can never finish; mark them failed so new runs are not blocked."""
    count = 0
    for job in store.list_all():
        if job.stage in _IN_PROGRESS_STAGES:
            job.stage = JobStage.FAILED
            job.error = "Interrupted: the server restarted while this job was running. Press Retry."
            store.update(job)
            count += 1
    return count


def _to_response(job) -> JobStatusResponse:
    return JobStatusResponse(
        job_id=job.job_id,
        stage=job.stage,
        error=job.error,
        is_georeferenced=job.is_georeferenced,
        outputs=job.outputs,
        progress=job.progress() if job.steps else _STAGE_PROGRESS.get(job.stage, 0),
        mode=job.mode,
        steps=job.steps,
        logs=job.logs[-120:],
        options=job.options,
        attempts=job.attempts,
        cancel_requested=job.cancel_requested,
        summary=job.summary,
        source_filename=job.source_filename,
        is_sample=job.is_sample,
    )


@router.get("/locations")
def list_job_locations(store: JobStore = Depends(get_job_store)) -> dict:
    """Georeferenced jobs for the world-map page: centre, footprint bounds and a thumbnail. Reads each job's
    metadata.json only; jobs without a WGS84 footprint are simply left out."""
    items = []
    for job in store.list_all():
        if job.stage != JobStage.READY:
            continue
        meta_path = store.job_dir(job.job_id) / "metadata.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 -- one unreadable file must not break the map
            continue
        bounds = meta.get("bounds_wgs84")
        if not bounds or len(bounds) != 4:
            continue
        centre = meta.get("centre_lon_lat") or [(bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2]
        items.append({
            "job_id": job.job_id, "name": job.source_filename, "bounds_wgs84": bounds, "centre_lon_lat": centre,
            "thumbnail_url": job.outputs.get("thumb_jpg") or job.outputs.get("original"),
            "width_px": meta.get("width"), "height_px": meta.get("height"), "pixel_size_m": meta.get("pixel_size_m"),
            "buildings": meta.get("buildings_count"), "is_site": bool(meta.get("site")),
        })
    return {"count": len(items), "locations": items}


@router.get("/{job_id}/site-analysis")
def get_site_analysis(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    path = store.job_dir(job_id) / "analysis.json"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="This job has no site analysis.")
    return json.loads(path.read_text(encoding="utf-8"))


@router.get("", response_model=JobListResponse)
def list_pipeline_jobs(store: JobStore = Depends(get_job_store)) -> JobListResponse:
    """Job history listing for the frontend History page. Reads every job's
    persisted job.json (JobStore.list_all) plus, when present, each job's
    own buildings.json artifact for `building_count` -- never re-runs
    detection, and never fabricates a count when the artifact isn't there."""
    jobs = store.list_all()
    summaries: list[JobSummary] = []
    for job in jobs:
        building_count: Optional[int] = None
        buildings_path = store.job_dir(job.job_id) / "buildings.json"
        if buildings_path.is_file():
            try:
                buildings_data = json.loads(buildings_path.read_text(encoding="utf-8"))
                building_count = buildings_data.get("count")
            except Exception:  # noqa: BLE001 -- a corrupt artifact must not break the listing
                logger.warning("Could not read buildings.json for job %s", job.job_id, exc_info=True)

        summaries.append(
            JobSummary(
                job_id=job.job_id,
                source_filename=job.source_filename,
                stage=job.stage,
                is_georeferenced=job.is_georeferenced,
                created_at=job.created_at,
                updated_at=job.updated_at,
                thumbnail_url=job.outputs.get("thumb_jpg") or job.outputs.get("original"),
                building_count=building_count,
                mode=job.mode,
                progress=job.progress() if job.steps else _STAGE_PROGRESS.get(job.stage, 0),
                summary=job.summary,
                is_sample=job.is_sample,
                error=job.error,
                gcp_count=len(job.gcps),
            )
        )

    return JobListResponse(count=len(summaries), jobs=summaries)


def _load_job_dsm(store: JobStore, job_id: str) -> tuple[np.ndarray, Optional[GeoMetadata], bool, Optional[str]]:
    """Load a job's persisted dsm.tif and reconstruct GeoMetadata from it the
    same way app/input/detect.py:detect_input does for the original upload
    (CRS/transform are embedded in dsm.tif whenever the source was
    georeferenced -- see app/geospatial/raster_io.py). `dsm_is_metric` is
    read from the job's metadata.json (written by app/pipeline/run.py).

    Returns (dsm_height, geo, dsm_is_metric, error_message). error_message
    is None on success; callers must check it before using the array.
    """
    job_dir = store.job_dir(job_id)
    dsm_path = job_dir / "dsm.tif"
    if not dsm_path.is_file():
        return np.zeros((0, 0), dtype=np.float32), None, False, "This job has no DSM yet (still running, failed, or predates this stage)."

    with rasterio.open(dsm_path) as dataset:
        dsm_height = dataset.read(1).astype(np.float32)
        geo: Optional[GeoMetadata] = None
        if dataset.crs is not None and not dataset.transform.is_identity:
            bounds = dataset.bounds
            geo = GeoMetadata(
                crs=dataset.crs.to_string(),
                transform=tuple(dataset.transform)[:6],
                width=dataset.width,
                height=dataset.height,
                bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
                resolution=(abs(dataset.transform.a), abs(dataset.transform.e)),
                nodata=dataset.nodata,
                band_count=dataset.count,
            )

    dsm_is_metric = False
    metadata_path = job_dir / "metadata.json"
    if metadata_path.is_file():
        try:
            dsm_is_metric = bool(json.loads(metadata_path.read_text(encoding="utf-8")).get("dsm_is_metric", False))
        except Exception:  # noqa: BLE001 -- fall back to non-metric rather than crash
            logger.warning("Could not read metadata.json for job %s", job_id, exc_info=True)

    return dsm_height, geo, dsm_is_metric, None


def _load_job_building_heights(store: JobStore, job_id: str) -> list[BuildingHeight]:
    """Load buildings.json (if present) as BuildingHeight objects, reusing
    the exact same persisted footprint/height fields app/pipeline/run.py
    wrote -- never re-runs segmentation."""
    buildings_path = store.job_dir(job_id) / "buildings.json"
    if not buildings_path.is_file():
        return []
    try:
        data = json.loads(buildings_path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        logger.warning("Could not read buildings.json for job %s", job_id, exc_info=True)
        return []

    return [
        BuildingHeight(
            id=b["id"],
            footprint=[tuple(pt) for pt in b.get("footprint", [])],
            area_px=b.get("area_px", 0),
            height_value=b.get("height_m"),
            is_metric=b.get("is_metric", False),
            mean_confidence=b.get("confidence"),
        )
        for b in data.get("buildings", [])
    ]


@router.post("/run/{job_id}", response_model=JobStatusResponse)
def run_pipeline(
    job_id: str,
    background_tasks: BackgroundTasks,
    options: Optional[RunOptions] = Body(default=None),
    store: JobStore = Depends(get_job_store),
    settings: Settings = Depends(get_settings),
    principal: Principal = Depends(require_analyst),
) -> JobStatusResponse:
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.stage in _IN_PROGRESS_STAGES:
        return _to_response(job)  # idempotent: never start a second concurrent run (memory safety)
    if job.stage == JobStage.READY and options is None:
        return _to_response(job)

    if _ACTIVE - {job_id}:
        raise HTTPException(status_code=409, detail="Another job is currently running. Wait for it to finish or cancel it.")

    if options is not None:
        job.options = options
    else:
        job.options.ensemble = settings.enable_depth_pro  # dashboard flow: Depth Pro reference output per config
    job.stage = JobStage.VALIDATING
    job.error = None
    job.cancel_requested = False
    job.steps = default_steps()
    job.logs = []
    job.outputs = {}
    store.update(job)

    _ACTIVE.add(job_id)
    background_tasks.add_task(_run_tracked, job_id, store, settings)
    logger.info("Queued pipeline run for job %s", job_id)
    return _to_response(job)


@router.post("/{job_id}/cancel", response_model=JobStatusResponse)
def cancel_pipeline(job_id: str, store: JobStore = Depends(get_job_store),
                    principal: Principal = Depends(require_analyst)) -> JobStatusResponse:
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.stage in _IN_PROGRESS_STAGES:
        job.cancel_requested = True
        store.update(job)
    return _to_response(job)


@router.get("/{job_id}/events")
async def pipeline_events(job_id: str, request: Request, store: JobStore = Depends(get_job_store)) -> StreamingResponse:
    """Server-sent events: one `progress` event whenever the job state changes, `done` at the end (FR-47)."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    async def stream():
        last_stamp = -1.0
        sent_logs = 0
        while True:
            if await request.is_disconnected():
                return
            job = store.get(job_id)
            if job.updated_at != last_stamp:
                last_stamp = job.updated_at
                payload = _to_response(job).model_dump(mode="json")
                payload["logs"] = [line.model_dump(mode="json") for line in job.logs[sent_logs:]]
                sent_logs = len(job.logs)
                yield "event: progress\ndata: " + json.dumps(payload) + "\n\n"
            if job.stage in (JobStage.READY, JobStage.FAILED):
                yield "event: done\ndata: {}\n\n"
                return
            await asyncio.sleep(0.4)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{job_id}", response_model=JobStatusResponse)
def get_pipeline_status(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> JobStatusResponse:
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return _to_response(job)


@router.delete("/{job_id}", status_code=204)
def delete_pipeline_job(job_id: str, store: JobStore = Depends(get_job_store),
                        principal: Principal = Depends(require_analyst)) -> Response:
    """Remove a job and all its outputs from history. Running jobs must be cancelled first."""
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.stage in _IN_PROGRESS_STAGES:
        raise HTTPException(status_code=409, detail="Job is still processing; cancel it before deleting.")
    store.delete(job_id)
    return Response(status_code=204)


@router.get("/output/{job_id}/{filename:path}")
def get_pipeline_output(
    job_id: str,
    filename: str,
    store: JobStore = Depends(get_job_store),
) -> FileResponse:
    try:
        store.get(job_id)  # 404s if the job doesn't exist
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job_dir = store.job_dir(job_id)
    # Path-traversal guard: resolve and ensure the file stays inside job_dir.
    candidate = (job_dir / filename).resolve()
    if job_dir.resolve() not in candidate.parents and candidate != job_dir.resolve():
        raise HTTPException(status_code=400, detail="Invalid output filename")
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"Output '{filename}' not found for job {job_id}")

    return FileResponse(candidate)


def _read_job_artifact(store: JobStore, job_id: str, filename: str) -> Optional[dict]:
    """Load a JSON artifact written by execute_pipeline (app/pipeline/run.py),
    or None if the stage hasn't produced it yet (job still running/failed
    before that stage, or an older job predating this artifact)."""
    try:
        store.get(job_id)  # 404s if the job doesn't exist
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    artifact_path = store.job_dir(job_id) / filename
    if not artifact_path.is_file():
        return None
    return json.loads(artifact_path.read_text(encoding="utf-8"))


@router.get("/{job_id}/buildings", response_model=BuildingsResponse)
def get_pipeline_buildings(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> BuildingsResponse:
    data = _read_job_artifact(store, job_id, "buildings.json")
    if data is None:
        return BuildingsResponse(
            job_id=job_id,
            count=0,
            buildings=[],
            note="Building analysis has not produced output yet for this job (still running, or job predates this stage).",
        )
    return BuildingsResponse(**data)


@router.post("/{job_id}/buildings/scale-reference", response_model=ReferenceScaledBuildingsResponse)
def post_pipeline_buildings_scale_reference(
    job_id: str,
    body: ReferenceScaleRequest,
    store: JobStore = Depends(get_job_store),
) -> ReferenceScaledBuildingsResponse:
    """Rescale this job's relative building heights using one caller-supplied
    real-world height (e.g. a landmark) as a single-point anchor -- for scenes
    with no GeoTIFF/SRTM/GCP calibration, where /buildings otherwise reports
    `is_metric: false`. See app/buildings/height.py:scale_buildings_to_reference
    for why this is explicitly NOT the same as DEM/GCP-verified calibration and
    why the result still reports `is_metric: false` per building -- it's one
    unverified reference point, not a certified measurement. Nothing is
    persisted to buildings.json; this is a derived, on-demand view."""
    data = _read_job_artifact(store, job_id, "buildings.json")
    if not data or not data.get("buildings"):
        return ReferenceScaledBuildingsResponse(
            job_id=job_id,
            status="unavailable",
            note="No building detections available for this job yet.",
        )

    scaled = scale_buildings_to_reference(
        data["buildings"], body.reference_building_id, body.reference_height_m
    )
    if scaled is None:
        return ReferenceScaledBuildingsResponse(
            job_id=job_id,
            status="unavailable",
            note=(
                f"Reference building {body.reference_building_id} not found, or has no usable "
                "relative height to scale from."
            ),
        )

    return ReferenceScaledBuildingsResponse(
        job_id=job_id,
        status="scaled",
        note=(
            "Heights are linearly rescaled from one user-supplied reference height, not verified "
            "against a DEM/GCP survey -- treat as an approximate, demo-oriented estimate, not a "
            "calibrated metric DSM."
        ),
        scale_factor=scaled["scale_factor"],
        reference_building_id=scaled["reference_building_id"],
        reference_height_m=scaled["reference_height_m"],
        buildings=scaled["buildings"],
    )


@router.post("/{job_id}/buildings/scale-reference-multi", response_model=ReferenceScaledBuildingsMultiResponse)
def post_pipeline_buildings_scale_reference_multi(
    job_id: str,
    body: ReferenceScaleMultiRequest,
    store: JobStore = Depends(get_job_store),
) -> ReferenceScaledBuildingsMultiResponse:
    """Multi-point GCP refinement -- see
    app/buildings/height.py:scale_buildings_to_reference_multi. Fits scale
    AND offset by least squares over 2+ reference heights instead of
    anchoring on one point; falls back to the single-point pure-ratio
    behavior with exactly 1 point. Still not DEM/GCP-verified calibration
    -- results report `is_metric: false`, same as the single-point endpoint."""
    data = _read_job_artifact(store, job_id, "buildings.json")
    if not data or not data.get("buildings"):
        return ReferenceScaledBuildingsMultiResponse(
            job_id=job_id, status="unavailable", note="No building detections available for this job yet."
        )

    scaled = scale_buildings_to_reference_multi(
        data["buildings"], [(p.building_id, p.reference_height_m) for p in body.points]
    )
    if scaled is None:
        return ReferenceScaledBuildingsMultiResponse(
            job_id=job_id,
            status="unavailable",
            note="None of the given reference points matched a building with a usable relative height.",
        )

    return ReferenceScaledBuildingsMultiResponse(
        job_id=job_id,
        status="scaled",
        note=(
            f"Heights are least-squares rescaled from {len(scaled['reference_points'])} user-supplied "
            f"reference point(s) (residual RMSE {scaled['residual_rmse_m']:.2f}), not verified against a "
            "DEM/GCP survey -- treat as an approximate, demo-oriented estimate."
        ),
        scale_factor=scaled["scale_factor"],
        offset_m=scaled["offset_m"],
        residual_rmse_m=scaled["residual_rmse_m"],
        reference_points=scaled["reference_points"],
        buildings=scaled["buildings"],
    )


@router.post("/{job_id}/viewshed", response_model=ViewshedResponse)
def post_pipeline_viewshed(
    job_id: str,
    body: ViewshedRequest,
    store: JobStore = Depends(get_job_store),
) -> ViewshedResponse:
    """Radial line-of-sight viewshed from an observer point -- see
    app/buildings/scenarios.py:compute_viewshed. Writes a visible-area
    preview PNG into the job's output directory, same pattern as the flood
    simulation endpoint."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    dsm_height, geo, dsm_is_metric, error = _load_job_dsm(store, job_id)
    if error is not None:
        return ViewshedResponse(job_id=job_id, status="unavailable", note=error)

    result = compute_viewshed(
        dsm_height, body.observer_px, body.observer_height_agl, geo=geo, dsm_is_metric=dsm_is_metric,
        max_radius_px=body.max_radius_px,
    )

    visible_mask = result.pop("_visible_mask", None)
    observer_rc = result.pop("_observer_rc", None)
    preview_url = None
    if result["status"] == "computed" and visible_mask is not None:
        job_dir = store.job_dir(job_id)
        filename = f"viewshed_{int(round(body.observer_px[0]))}_{int(round(body.observer_px[1]))}.png"
        save_viewshed_preview(dsm_height, visible_mask, observer_rc, job_dir / filename)
        job = store.get(job_id)
        job.outputs[f"viewshed_{int(round(body.observer_px[0]))}_{int(round(body.observer_px[1]))}_png"] = (
            f"/api/pipeline/output/{job_id}/{filename}"
        )
        store.update(job)
        preview_url = f"/api/pipeline/output/{job_id}/{filename}"

    return ViewshedResponse(job_id=job_id, preview_url=preview_url, **result)


@router.post("/{job_id}/report", response_model=ReportResponse)
def post_pipeline_report(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> ReportResponse:
    """Generates a PDF situation report from this job's already-persisted
    artifacts (metadata.json, buildings.json, disaster_zones.json,
    validation.json) -- see app/export/report.py. Nothing is computed
    fresh; the report can only restate what the rest of the app already
    reports. Overwrites report.pdf on repeat calls."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    job_dir = store.job_dir(job_id)
    metadata = _read_job_artifact(store, job_id, "metadata.json")
    if metadata is None:
        return ReportResponse(job_id=job_id, status="unavailable", note="This job has not finished the pipeline yet (no metadata.json).")

    buildings = (_read_job_artifact(store, job_id, "buildings.json") or {}).get("buildings", [])
    zones = (_read_job_artifact(store, job_id, "disaster_zones.json") or {}).get("zones", [])
    validation = (_read_job_artifact(store, job_id, "validation.json") or {}).get(
        "result", {"status": "unavailable", "note": "No validation.json for this job."}
    )

    out_path = job_dir / "report.pdf"
    generate_pdf_report(
        job_id=job_id,
        job_dir=job_dir,
        metadata=metadata,
        buildings=buildings,
        zones=zones,
        validation=validation,
        out_path=out_path,
        dsm_preview_path=job_dir / "dsm_preview.png",
        fused_depth_preview_path=job_dir / "fused_depth_preview.png",
    )

    job = store.get(job_id)
    job.outputs["report_pdf"] = f"/api/pipeline/output/{job_id}/report.pdf"
    store.update(job)

    return ReportResponse(
        job_id=job_id, status="generated", note="PDF situation report generated.",
        report_url=f"/api/pipeline/output/{job_id}/report.pdf",
    )


@router.get("/{job_id}/disaster-zones", response_model=DisasterZonesResponse)
def get_pipeline_disaster_zones(
    job_id: str,
    store: JobStore = Depends(get_job_store),
    aircraft_type: Optional[str] = Query(None),
) -> DisasterZonesResponse:
    """`aircraft_type` ("plane" | "helicopter"), when supplied, adds an
    `aircraft_fit` entry to each persisted landing_zone's `properties` --
    computed on the fly from that zone's already-measured `width_m`/
    `length_m` (app/buildings/disaster.py:assess_aircraft_fit) rather than
    re-running the full landing-zone search, since the DSM/building_mask
    used to find zones isn't reloaded for this read-only GET."""
    if aircraft_type not in (None, "plane", "helicopter"):
        raise HTTPException(status_code=422, detail="aircraft_type must be 'plane', 'helicopter', or omitted")

    data = _read_job_artifact(store, job_id, "disaster_zones.json")
    if data is None:
        return DisasterZonesResponse(
            job_id=job_id,
            count=0,
            zones=[],
            note="Disaster-zone analysis has not produced output yet for this job (still running, or job predates this stage).",
        )

    if aircraft_type is not None:
        for zone in data.get("zones", []):
            properties = zone.get("properties") or {}
            if properties.get("zone_type") == "landing_zone":
                properties["aircraft_fit"] = assess_aircraft_fit(
                    properties.get("width_m"), properties.get("length_m"), aircraft_type
                )
                zone["properties"] = properties

    return DisasterZonesResponse(**data)


@router.get("/{job_id}/validation", response_model=ValidationResponse)
def get_pipeline_validation(
    job_id: str,
    store: JobStore = Depends(get_job_store),
) -> ValidationResponse:
    data = _read_job_artifact(store, job_id, "validation.json")
    if data is None:
        return ValidationResponse(
            job_id=job_id,
            result={
                "status": "unavailable",
                "note": "Validation has not produced output yet for this job (still running, or job predates this stage).",
                "rmse": None,
                "mae": None,
                "correlation": None,
                "valid_pixel_count": None,
                "reference_source": None,
            },
        )
    return ValidationResponse(**data)


@router.post("/{job_id}/scenario/flood", response_model=FloodSimulationResponse)
def post_scenario_flood(
    job_id: str,
    body: FloodSimulationRequest,
    store: JobStore = Depends(get_job_store),
) -> FloodSimulationResponse:
    """Bathtub-model flood-extent simulation -- see
    app/buildings/scenarios.py:simulate_flood_level for the real technique
    and its documented limitations. Writes a flood-mask preview PNG into the
    job's output directory and registers it in job.outputs."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    dsm_height, geo, dsm_is_metric, error = _load_job_dsm(store, job_id)
    if error is not None:
        return FloodSimulationResponse(job_id=job_id, status="unavailable", note=error)

    buildings = _load_job_building_heights(store, job_id)
    result = simulate_flood_level(dsm_height, body.water_level, buildings=buildings, geo=geo, dsm_is_metric=dsm_is_metric)

    submerged_mask = result.pop("_submerged_mask", None)
    preview_url = None
    if result["status"] == "simulated" and submerged_mask is not None:
        job_dir = store.job_dir(job_id)
        level_suffix = _sanitize_level_for_filename(body.water_level)
        filename = f"flood_preview_{level_suffix}.png"
        save_flood_preview(dsm_height, submerged_mask, job_dir / filename)
        job = store.get(job_id)
        job.outputs[f"flood_preview_{level_suffix}_png"] = f"/api/pipeline/output/{job_id}/{filename}"
        store.update(job)
        preview_url = f"/api/pipeline/output/{job_id}/{filename}"

    return FloodSimulationResponse(job_id=job_id, preview_url=preview_url, **result)


@router.post("/{job_id}/scenario/bomb-simulation", response_model=ExplosionImpactResponse)
def post_scenario_bomb_simulation(
    job_id: str,
    body: ExplosionImpactRequest,
    store: JobStore = Depends(get_job_store),
) -> ExplosionImpactResponse:
    """Cube-root scaled-distance structural-damage-radius safety-engineering
    approximation -- see app/buildings/scenarios.py:simulate_explosion_impact.
    Same category of tool as ATF/OSHA/NFPA quantity-distance planning
    tables, NOT a weapons-effects or casualty/injury/lethality calculation.
    Unlike the old hazard-exposure route this replaces, georeferencing is
    NOT required -- `simulate_explosion_impact` falls back to an
    illustrative pixel-based scale (`spacing_units: "pixels"`) instead of
    refusing, so this always attempts the computation."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    _dsm_height, geo, _dsm_is_metric, _dsm_error = _load_job_dsm(store, job_id)
    buildings = _load_job_building_heights(store, job_id)
    result = simulate_explosion_impact(
        buildings,
        body.epicenter_px,
        body.yield_kg,
        geo,
    )
    return ExplosionImpactResponse(job_id=job_id, **result)


@router.post("/{job_id}/scenario/wildfire-drone", response_model=WildfireDroneResponse)
def post_scenario_wildfire_drone(
    job_id: str,
    body: WildfireDroneRequest,
    store: JobStore = Depends(get_job_store),
) -> WildfireDroneResponse:
    """Firefighting-drone water-drop trajectory -- see
    app/buildings/scenarios.py:compute_drone_water_drop. Real, textbook
    no-drag projectile motion anchored on the real DSM elevation at
    `fire_point_px`. Defaults for hover_altitude_agl_m/water_exit_velocity_mps
    are illustrative, reasonable assumptions for a typical small
    firefighting drone -- NOT measured specs of any real product."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    dsm_height, geo, dsm_is_metric, error = _load_job_dsm(store, job_id)
    if error is not None:
        return WildfireDroneResponse(job_id=job_id, status="unavailable", note=error)

    result = compute_drone_water_drop(
        dsm_height,
        body.fire_point_px,
        body.hover_altitude_agl_m,
        body.water_exit_velocity_mps,
        geo=geo,
        dsm_is_metric=dsm_is_metric,
    )
    return WildfireDroneResponse(job_id=job_id, **result)
