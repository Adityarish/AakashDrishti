"""Project routes: upload (FR-01/FR-02), metadata, deletion and GCP management."""

from __future__ import annotations

import csv
import io
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.api.deps import get_job_store
from app.auth.service import Principal, require_analyst
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.input.detect import InputDescriptor, UnsupportedInputError, detect_input
from app.jobs.models import GroundControlPoint, JobStage, JobState
from app.jobs.store import JobNotFoundError, JobStore
from app.schemas.input import GeoMetadataOut, UploadResponse

router = APIRouter(prefix="/api/project", tags=["project"])
logger = get_logger(__name__)

ALLOWED_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff"}
CHUNK = 4 * 1024 * 1024


def descriptor_to_response(job_id: str, filename: str, descriptor: InputDescriptor, **extra) -> UploadResponse:
    geo_out = None
    if descriptor.geo is not None:
        geo_out = GeoMetadataOut(
            crs=descriptor.geo.crs, transform=descriptor.geo.transform, width=descriptor.geo.width,
            height=descriptor.geo.height, bounds=descriptor.geo.bounds, resolution=descriptor.geo.resolution,
            nodata=descriptor.geo.nodata, band_count=descriptor.geo.band_count,
        )
    return UploadResponse(
        job_id=job_id, filename=filename, width=descriptor.width, height=descriptor.height,
        band_count=descriptor.band_count, dtype=descriptor.dtype, is_georeferenced=descriptor.is_georeferenced,
        geo=geo_out, mode="absolute" if descriptor.is_georeferenced else "relative",
        file_format=descriptor.file_format, bit_depth=descriptor.bit_depth, size_bytes=descriptor.size_bytes,
        gsd_m=descriptor.gsd_m, sun_azimuth_deg=descriptor.sun_azimuth_deg, sun_elevation_deg=descriptor.sun_elevation_deg,
        bounds_wgs84=descriptor.bounds_wgs84, notes=descriptor.notes, **extra,
    )


@router.post("/upload", response_model=UploadResponse)
async def upload_project(
    file: UploadFile,
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_job_store),
    principal: Principal = Depends(require_analyst),
) -> UploadResponse:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_SUFFIXES)}")

    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    stored_path = job_dir / f"source{suffix}"

    written = 0
    with stored_path.open("wb") as out_file:
        while True:
            chunk = await file.read(CHUNK)
            if not chunk:
                break
            written += len(chunk)
            if written > settings.max_upload_bytes:
                out_file.close()
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(status_code=413, detail=f"File exceeds the {settings.max_upload_bytes // 2**30} GB upload limit.")
            out_file.write(chunk)

    try:
        descriptor = detect_input(stored_path)
    except UnsupportedInputError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = JobState(
        job_id=job_id, stage=JobStage.UPLOADED, source_filename=file.filename or stored_path.name,
        stored_path=str(stored_path), is_georeferenced=descriptor.is_georeferenced,
        mode="absolute" if descriptor.is_georeferenced else "relative", owner=principal.email,
    )
    store.create(state)
    logger.info("Uploaded job %s: %s (%dx%d, georeferenced=%s)", job_id, file.filename, descriptor.width,
                descriptor.height, descriptor.is_georeferenced)
    return descriptor_to_response(job_id, state.source_filename, descriptor)


@router.get("/{job_id}", response_model=UploadResponse)
def get_project(job_id: str, store: JobStore = Depends(get_job_store)) -> UploadResponse:
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    descriptor = detect_input(Path(job.stored_path))
    return descriptor_to_response(job_id, job.source_filename, descriptor, is_sample=job.is_sample, sample_id=job.sample_id)


@router.post("/{job_id}/clone", response_model=UploadResponse)
def clone_project(job_id: str, store: JobStore = Depends(get_job_store),
                  principal: Principal = Depends(require_analyst)) -> UploadResponse:
    """Start a new job from an earlier job's uploaded image, so it can be re-run with other options
    without re-uploading and without overwriting the earlier results."""
    try:
        source = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    source_path = Path(source.stored_path)
    if not source_path.is_file():
        raise HTTPException(status_code=404, detail="The image for that job is no longer on disk. Upload it again.")

    new_id = uuid.uuid4().hex
    new_dir = store.job_dir(new_id)
    stored_path = new_dir / f"source{source_path.suffix.lower()}"
    try:
        os.link(source_path, stored_path)  # same bytes, no second multi-GB copy
    except OSError:
        shutil.copyfile(source_path, stored_path)
    reference = source_path.parent / "sample_reference.npy"
    if source.is_sample and reference.is_file():
        shutil.copyfile(reference, new_dir / "sample_reference.npy")

    try:
        descriptor = detect_input(stored_path)
    except UnsupportedInputError as exc:
        shutil.rmtree(new_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    state = JobState(
        job_id=new_id, stage=JobStage.UPLOADED, source_filename=source.source_filename, stored_path=str(stored_path),
        is_georeferenced=descriptor.is_georeferenced, mode="absolute" if descriptor.is_georeferenced else "relative",
        owner=principal.email, is_sample=source.is_sample, sample_id=source.sample_id, gcps=list(source.gcps),
    )
    store.create(state)
    logger.info("Cloned job %s -> %s (%s)", job_id, new_id, source.source_filename)
    return descriptor_to_response(new_id, state.source_filename, descriptor, is_sample=state.is_sample, sample_id=state.sample_id)


@router.delete("/{job_id}")
def delete_project(job_id: str, store: JobStore = Depends(get_job_store), principal: Principal = Depends(require_analyst)) -> dict:
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    if job.stage not in (JobStage.READY, JobStage.FAILED, JobStage.UPLOADED):
        raise HTTPException(status_code=409, detail="Cancel the running job before deleting it.")
    store.delete(job_id)
    return {"deleted": job_id}


class GcpBody(BaseModel):
    gcps: list[GroundControlPoint]


@router.get("/{job_id}/gcps")
def list_gcps(job_id: str, store: JobStore = Depends(get_job_store)) -> dict:
    try:
        return {"gcps": [g.model_dump() for g in store.get(job_id).gcps]}
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")


@router.put("/{job_id}/gcps")
def set_gcps(job_id: str, body: GcpBody, store: JobStore = Depends(get_job_store),
             principal: Principal = Depends(require_analyst)) -> dict:
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    job.gcps = body.gcps
    store.update(job)
    return {"count": len(job.gcps)}


@router.post("/{job_id}/gcps/csv")
async def upload_gcp_csv(job_id: str, file: UploadFile, store: JobStore = Depends(get_job_store),
                         principal: Principal = Depends(require_analyst)) -> dict:
    """CSV columns: label,elevation_m and either col,row or x,y (or lon,lat)."""
    try:
        job = store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    text = (await file.read()).decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    parsed: list[GroundControlPoint] = []
    for line, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        elevation = row.get("elevation_m") or row.get("elevation") or row.get("z")
        if not elevation:
            raise HTTPException(status_code=422, detail=f"Line {line}: missing elevation_m")
        try:
            if "lon" in row and "lat" in row:
                gcp = GroundControlPoint(label=row.get("label", ""), elevation_m=float(elevation), x=float(row["lon"]),
                                         y=float(row["lat"]), lonlat=True)
            elif "col" in row and "row" in row:
                gcp = GroundControlPoint(label=row.get("label", ""), elevation_m=float(elevation), col=float(row["col"]),
                                         row=float(row["row"]))
            elif "x" in row and "y" in row:
                gcp = GroundControlPoint(label=row.get("label", ""), elevation_m=float(elevation), x=float(row["x"]),
                                         y=float(row["y"]))
            else:
                raise HTTPException(status_code=422, detail=f"Line {line}: need col,row or x,y or lon,lat")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Line {line}: {exc}") from exc
        parsed.append(gcp)
    job.gcps = parsed
    store.update(job)
    return {"count": len(parsed)}
