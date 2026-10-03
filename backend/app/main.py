"""FastAPI application entrypoint.

Wires up: upload (FR-1/FR-2), pipeline run/status/output (FR-3 through
FR-8: depth, fusion, confidence, calibration, DSM/rDSM, and terrain mesh
generation all run for real -- see app/pipeline/run.py). First-person
flythrough (FR-9) is a frontend concern (Three.js) and reference
validation (FR-11) remains unimplemented -- see IMPLEMENTATION.md.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_analysis import router as analysis_router
from app.api.routes_analyst import router as analyst_router
from app.api.routes_auth import router as auth_router
from app.api.routes_pipeline import router as pipeline_router
from app.api.routes_project import router as project_router
from app.api.routes_samples import router as samples_router
from app.api.routes_validation import router as validation_router
from app.core.config import get_settings
from app.core.logging import configure_logging

configure_logging()

settings = get_settings()

app = FastAPI(title="AakashDrishti API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(project_router)
app.include_router(pipeline_router)
app.include_router(analysis_router)
app.include_router(validation_router)
app.include_router(analyst_router)
app.include_router(samples_router)


@app.on_event("startup")
def _recover_orphaned_jobs() -> None:
    from app.api.deps import get_job_store
    from app.api.routes_pipeline import fail_orphaned_jobs

    fail_orphaned_jobs(get_job_store())

    from app.samples.featured import install_featured_scene, install_site_scene

    install_featured_scene(settings)
    install_site_scene(settings)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/capabilities")
def capabilities() -> dict:
    import os

    return {
        "auth_required": settings.auth_required,
        "analyst_online": settings.analyst_available,
        "dem_auto_download": settings.dem_auto_download,
        "device_preference": settings.device,
        "checkpoint": settings.da_v2_checkpoint_path.name,
        "offline_ready": not (settings.analyst_available or settings.dem_auto_download),
        "cuda_visible": os.environ.get("CUDA_VISIBLE_DEVICES") != "",
    }
