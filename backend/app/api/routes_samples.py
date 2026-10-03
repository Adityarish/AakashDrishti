"""Bundled sample scenes and MP4 export of recorded flythroughs (FR-29)."""

from __future__ import annotations

import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import Response

from app.api.deps import get_job_store
from app.api.routes_project import descriptor_to_response
from app.auth.service import Principal, require_analyst, require_responder
from app.core.config import Settings, get_settings
from app.input.detect import detect_input
from app.jobs.models import JobStage, JobState
from app.jobs.store import JobNotFoundError, JobStore
from app.samples import registry
from app.schemas.input import UploadResponse

router = APIRouter(prefix="/api", tags=["samples"])


@router.get("/samples")
def list_samples(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "samples": [
            {"id": s.sample_id, "title": s.title, "city": s.city, "landscape": s.landscape, "featured": s.featured,
             "thumbnail_url": f"/api/samples/{s.sample_id}/thumb", "size_px": 1024, "gsd_m": registry.SAMPLE_GSD_M}
            for s in registry.list_samples(settings)
        ]
    }


@router.get("/samples/{sample_id}/thumb")
def sample_thumb(sample_id: str, settings: Settings = Depends(get_settings)) -> Response:
    sample = registry.get_sample(settings, sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown sample")
    return Response(registry.thumbnail_jpeg(sample), media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


@router.post("/samples/{sample_id}/load", response_model=UploadResponse)
def load_sample(
    sample_id: str,
    variant: str = Query("geotiff", pattern="^(png|geotiff)$"),
    settings: Settings = Depends(get_settings),
    store: JobStore = Depends(get_job_store),
    principal: Principal = Depends(require_analyst),
) -> UploadResponse:
    sample = registry.get_sample(settings, sample_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="Unknown sample")
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    stored = registry.write_sample_input(sample, job_dir, variant)
    registry.attach_reference(sample, job_dir)
    descriptor = detect_input(stored)
    state = JobState(
        job_id=job_id, stage=JobStage.UPLOADED, source_filename=f"{sample.sample_id}{'.tif' if variant == 'geotiff' else '.png'}",
        stored_path=str(stored), is_georeferenced=descriptor.is_georeferenced,
        mode="absolute" if descriptor.is_georeferenced else "relative", is_sample=True, sample_id=sample_id, owner=principal.email,
    )
    store.create(state)
    return descriptor_to_response(job_id, state.source_filename, descriptor, is_sample=True, sample_id=sample_id)


MAX_VIDEO_BYTES = 600 * 1024 * 1024


@router.post("/pipeline/{job_id}/video")
async def export_video(job_id: str, file: UploadFile, store: JobStore = Depends(get_job_store),
                       principal: Principal = Depends(require_responder)) -> dict:
    """Transcode a browser-recorded WebM/MP4 into a 1080p H.264 MP4 (ffmpeg bundled via imageio-ffmpeg)."""
    try:
        store.get(job_id)
    except JobNotFoundError:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    import imageio_ffmpeg

    job_dir = store.job_dir(job_id)
    source = job_dir / "flythrough_source"
    written = 0
    too_large = False
    with source.open("wb") as handle:
        while chunk := await file.read(4 * 1024 * 1024):
            written += len(chunk)
            if written > MAX_VIDEO_BYTES:
                too_large = True
                break
            handle.write(chunk)
    if too_large:
        source.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail="Recording is too large.")
    target = job_dir / "flythrough.mp4"
    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", str(source),
        "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0xFAFCFE,fps=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-preset", "veryfast", "-movflags", "+faststart", "-an", str(target),
    ]
    result = subprocess.run(command, capture_output=True, timeout=600)
    source.unlink(missing_ok=True)
    if result.returncode != 0 or not target.is_file():
        raise HTTPException(status_code=500, detail="Video transcoding failed: " + result.stderr.decode("utf-8", "replace")[-300:])
    job = store.get(job_id)
    job.outputs["flythrough_mp4"] = f"/api/pipeline/output/{job_id}/flythrough.mp4"
    store.update(job)
    return {"url": job.outputs["flythrough_mp4"], "size_bytes": target.stat().st_size, "resolution": "1920x1080"}
