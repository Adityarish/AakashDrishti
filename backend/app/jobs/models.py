"""Job state machine and live progress model for pipeline runs.

Coarse stages (kept stable for the API contract):
UPLOADED -> VALIDATING -> DEPTH -> FUSION -> CALIBRATION -> DSM -> MESH -> READY | FAILED

Fine-grained pipeline steps drive the live timeline in the UI (FR-47):
ingest, tiling, inference, blending, dem, calibration, shadow, mesh, export.
"""

from __future__ import annotations

import time
import uuid
from enum import StrEnum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class JobStage(StrEnum):
    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    DEPTH = "DEPTH"
    FUSION = "FUSION"
    CALIBRATION = "CALIBRATION"
    DSM = "DSM"
    MESH = "MESH"
    READY = "READY"
    FAILED = "FAILED"


StepStatus = Literal["pending", "running", "done", "skipped", "failed"]

STEP_DEFINITIONS: list[tuple[str, str, float, JobStage]] = [
    ("ingest", "Ingest and validate", 4, JobStage.VALIDATING),
    ("tiling", "Tiling", 4, JobStage.DEPTH),
    ("inference", "AI height inference", 40, JobStage.DEPTH),
    ("blending", "Blending and uncertainty", 8, JobStage.FUSION),
    ("dem", "DEM fetch", 6, JobStage.CALIBRATION),
    ("calibration", "Scale calibration", 8, JobStage.CALIBRATION),
    ("shadow", "Shadow cross-check", 6, JobStage.CALIBRATION),
    ("detect", "Object detection", 6, JobStage.MESH),
    ("mesh", "Mesh generation", 12, JobStage.MESH),
    ("export", "Export", 12, JobStage.MESH),
]


class GroundControlPoint(BaseModel):
    """A point with a known elevation. Either pixel (col,row) or map (x,y in the scene CRS,
    or lon/lat when `lonlat` is true) coordinates are given."""

    label: str = ""
    elevation_m: float
    col: Optional[float] = None
    row: Optional[float] = None
    x: Optional[float] = None
    y: Optional[float] = None
    lonlat: bool = False


class RunOptions(BaseModel):
    gsd_m: Optional[float] = Field(default=None, gt=0)
    crs: Optional[str] = None
    origin_x: Optional[float] = None
    origin_y: Optional[float] = None
    sun_azimuth_deg: Optional[float] = Field(default=None, ge=0, le=360)
    sun_elevation_deg: Optional[float] = Field(default=None, gt=0, le=90)
    dem_source: Literal["auto", "local", "none"] = "auto"
    tta: bool = True
    ensemble: bool = False
    tile_size: int = Field(default=1024, ge=256, le=2048)
    overlap: float = Field(default=0.25, ge=0.2, le=0.5)


class StepState(BaseModel):
    key: str
    label: str
    status: StepStatus = "pending"
    progress: float = 0.0
    detail: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None


class LogLine(BaseModel):
    t: float
    level: Literal["info", "warn", "error"] = "info"
    step: Optional[str] = None
    msg: str


def default_steps() -> list[StepState]:
    return [StepState(key=key, label=label) for key, label, _weight, _stage in STEP_DEFINITIONS]


class JobState(BaseModel):
    job_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    stage: JobStage = JobStage.UPLOADED
    source_filename: str
    stored_path: str
    is_georeferenced: bool = False
    error: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    outputs: dict[str, str] = Field(default_factory=dict)
    """Relative-to-output-dir file paths keyed by artifact name."""

    mode: Literal["absolute", "relative"] = "relative"
    options: RunOptions = Field(default_factory=RunOptions)
    gcps: list[GroundControlPoint] = Field(default_factory=list)
    steps: list[StepState] = Field(default_factory=default_steps)
    logs: list[LogLine] = Field(default_factory=list)
    cancel_requested: bool = False
    attempts: int = 0
    is_sample: bool = False
    sample_id: Optional[str] = None
    owner: Optional[str] = None
    summary: dict[str, Any] = Field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = time.time()

    def progress(self) -> int:
        total = sum(weight for _k, _l, weight, _s in STEP_DEFINITIONS)
        weights = {key: weight for key, _l, weight, _s in STEP_DEFINITIONS}
        done = 0.0
        for step in self.steps:
            weight = weights.get(step.key, 0)
            if step.status in ("done", "skipped"):
                done += weight
            elif step.status == "running":
                done += weight * max(0.0, min(100.0, step.progress)) / 100.0
        if self.stage == JobStage.READY:
            return 100
        return int(round(100 * done / total)) if total else 0
