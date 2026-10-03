from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from app.jobs.models import JobStage, LogLine, RunOptions, StepState


class JobStatusResponse(BaseModel):
    job_id: str
    stage: JobStage
    error: Optional[str] = None
    is_georeferenced: bool
    outputs: dict[str, str]
    progress: int
    mode: str = "relative"
    steps: list[StepState] = []
    logs: list[LogLine] = []
    options: Optional[RunOptions] = None
    attempts: int = 0
    cancel_requested: bool = False
    summary: dict[str, Any] = {}
    source_filename: Optional[str] = None
    is_sample: bool = False


class DepthStatsOut(BaseModel):
    min: float
    max: float
    mean: float


class DepthResultResponse(BaseModel):
    job_id: str
    da_v2: DepthStatsOut
    depth_pro: DepthStatsOut
    depth_pro_focallength_px: float


class Building(BaseModel):
    """One heuristic building candidate (app/buildings/segment.py,height.py,shadow.py).

    `height_m` and `confidence` may be null if a footprint had no valid
    (finite) height/confidence pixels -- never fabricated. `is_metric=False`
    means `height_m` is in the DSM's relative units, not meters.
    """

    id: int
    footprint: list[list[float]]  # polygon vertices, pixel [x, y] coords
    area_px: int
    height_m: Optional[float] = None
    is_metric: bool
    confidence: Optional[float] = None
    shadow_estimate_m: Optional[float] = None
    depth_vs_shadow_delta_m: Optional[float] = None


class BuildingsResponse(BaseModel):
    job_id: str
    count: int
    buildings: list[Building]
    note: Optional[str] = None


class ReferenceScaleRequest(BaseModel):
    """One user-supplied real-world height, used as a single-point GCP-style
    scale anchor for scenes with no GeoTIFF/SRTM/GCP calibration at all."""

    reference_building_id: int
    reference_height_m: float


class ReferenceScaledBuildingsResponse(BaseModel):
    job_id: str
    status: str  # "scaled" | "unavailable"
    note: str
    scale_factor: Optional[float] = None
    reference_building_id: Optional[int] = None
    reference_height_m: Optional[float] = None
    buildings: list[Building] = []


class ReferencePoint(BaseModel):
    building_id: int
    reference_height_m: float


class ReferenceScaleMultiRequest(BaseModel):
    """3+ user-supplied real-world heights (PRD.md "GCP refinement"), fit by
    least squares instead of anchoring on a single point. Works with as
    few as 1 point (falls back to the single-point pure-ratio behavior)."""

    points: list[ReferencePoint]


class ReferenceScaledBuildingsMultiResponse(BaseModel):
    job_id: str
    status: str  # "scaled" | "unavailable"
    note: str
    scale_factor: Optional[float] = None
    offset_m: Optional[float] = None
    residual_rmse_m: Optional[float] = None
    reference_points: list[ReferencePoint] = []
    buildings: list[Building] = []


class ViewshedRequest(BaseModel):
    observer_px: tuple[float, float]
    observer_height_agl: float = 10.0
    max_radius_px: Optional[int] = None


class ViewshedResponse(BaseModel):
    job_id: str
    status: str  # "computed" | "unavailable"
    note: str
    visible_fraction: Optional[float] = None
    visible_area_m2: Optional[float] = None
    observer_elevation: Optional[float] = None
    preview_url: Optional[str] = None


class ReportResponse(BaseModel):
    job_id: str
    status: str  # "generated" | "unavailable"
    note: str
    report_url: Optional[str] = None


class DisasterZone(BaseModel):
    """One GeoJSON-style Feature from app/buildings/disaster.py.

    All three producing functions are explicitly heuristic decision-support
    only -- see that module's docstring. `geometry` is a GeoJSON Polygon
    dict in pixel coords, or map coords if the source image was georeferenced.
    """

    type: str  # "landing_zone" | "flood_risk_zone" | "fire_access_risk"
    geometry: dict[str, Any]
    risk_level: Optional[str] = None
    notes: Optional[str] = None
    properties: dict[str, Any] = {}


class DisasterZonesResponse(BaseModel):
    job_id: str
    count: int
    zones: list[DisasterZone]
    note: Optional[str] = None


class ValidationResult(BaseModel):
    """FR-11 output (app/validation/metrics.py). All numeric fields are
    null when status == "unavailable" -- never fabricated."""

    status: str  # "calibrated" | "unavailable"
    note: str
    rmse: Optional[float] = None
    mae: Optional[float] = None
    correlation: Optional[float] = None
    valid_pixel_count: Optional[int] = None
    reference_source: Optional[str] = None


class ValidationResponse(BaseModel):
    job_id: str
    result: ValidationResult


class JobSummary(BaseModel):
    """One row for the job-history listing (GET /api/pipeline).

    `thumbnail_url`/`building_count` are null when the underlying artifact
    isn't available yet (job still running, failed before that stage, or
    predates the artifact) -- never fabricated."""

    job_id: str
    source_filename: str
    stage: JobStage
    is_georeferenced: bool
    created_at: float
    updated_at: float
    thumbnail_url: Optional[str] = None
    building_count: Optional[int] = None
    mode: str = "relative"
    progress: int = 0
    summary: dict[str, Any] = {}
    is_sample: bool = False
    error: Optional[str] = None
    gcp_count: int = 0


class JobListResponse(BaseModel):
    count: int
    jobs: list[JobSummary]


class FloodSimulationRequest(BaseModel):
    water_level: float


class FloodSimulationResponse(BaseModel):
    """app/buildings/scenarios.py:simulate_flood_level -- a bathtub-model
    approximation, not a hydrological/hydraulic simulation. See that
    function's docstring and this response's `note` for the specific
    limitation (the DSM is a surface model, so building roofs are treated
    as ground too)."""

    job_id: str
    status: str  # "simulated" | "unavailable"
    note: str
    water_level: Optional[float] = None
    unit: Optional[str] = None  # "meters" | "relative_dsm_units"
    submerged_pixel_fraction: Optional[float] = None
    submerged_area_m2: Optional[float] = None
    area_note: Optional[str] = None
    affected_building_ids: list[int] = []
    preview_url: Optional[str] = None


class ExplosionImpactRequest(BaseModel):
    epicenter_px: tuple[float, float]
    yield_kg: float


class ExplosionImpactBand(BaseModel):
    severity: str  # "severe" | "moderate" | "light"
    radius_m: float
    building_ids: list[int] = []


class ExplosionImpactResponse(BaseModel):
    """app/buildings/scenarios.py:simulate_explosion_impact -- a real
    cube-root scaled-distance (Z = R / W^(1/3)) structural-damage-radius
    safety-engineering approximation, the same category of tool as
    ATF/OSHA/NFPA quantity-distance planning tables used for industrial
    explosion standoff planning, NOT a weapons-effects or
    casualty/injury/lethality calculator. Bands represent structural damage
    severity to buildings only."""

    job_id: str
    status: str  # "simulated" | "unavailable"
    note: str
    epicenter_px: Optional[list[float]] = None
    yield_kg: Optional[float] = None
    spacing_units: Optional[str] = None  # "meters" | "pixels"
    bands: list[ExplosionImpactBand] = []


class WildfireDroneRequest(BaseModel):
    fire_point_px: tuple[float, float]
    hover_altitude_agl_m: float = 30.0
    """Default is an illustrative, reasonable assumption for a typical small
    firefighting drone -- not a measured spec of any real product."""
    water_exit_velocity_mps: float = 20.0
    """Same caveat as above -- illustrative default, not a measured spec."""


class DroneAssumptions(BaseModel):
    water_exit_velocity_mps: float
    g: float
    caveats: list[str]


class WildfireDroneResponse(BaseModel):
    """app/buildings/scenarios.py:compute_drone_water_drop -- textbook
    no-drag projectile motion anchored on the real DSM elevation at the
    fire point. `status: "unavailable"` (with no numeric fields) when the
    DSM isn't metrically calibrated, since a pixel-unit distance would
    misleadingly imply a real physical distance."""

    job_id: str
    status: str  # "computed" | "unavailable"
    note: str
    fall_time_s: Optional[float] = None
    horizontal_reach_m: Optional[float] = None
    hover_altitude_agl_m: Optional[float] = None
    target_elevation_m: Optional[float] = None
    drone_absolute_altitude_m: Optional[float] = None
    assumptions: Optional[DroneAssumptions] = None
