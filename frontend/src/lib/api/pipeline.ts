/**
 * Pipeline execution/status endpoints, matching the real backend contract
 * (backend/app/api/routes_pipeline.py):
 *   POST /api/pipeline/run/{job_id}
 *   GET  /api/pipeline/{job_id}
 *   GET  /api/pipeline/output/{job_id}/{filename}
 */

import { API_BASE_URL, ApiError, apiFetch } from "./client";
import type { ProcessingStage, ProcessingStatus } from "@/lib/types/processing";
import type { Building, DisasterZone, DisasterZoneType, ValidationResult } from "@/lib/types/results";

interface JobStatusDto {
  job_id: string;
  stage: ProcessingStage;
  error: string | null;
  is_georeferenced: boolean;
  outputs: Record<string, string>;
  progress: number;
}

function mapStatus(dto: JobStatusDto): ProcessingStatus {
  return {
    jobId: dto.job_id,
    stage: dto.stage,
    error: dto.error,
    outputs: dto.outputs,
    progress: dto.progress,
  };
}

export async function runPipeline(jobId: string): Promise<ProcessingStatus> {
  const dto = await apiFetch<JobStatusDto>(`/api/pipeline/run/${jobId}`, {
    method: "POST",
  });
  return mapStatus(dto);
}

export async function getJobStatus(jobId: string): Promise<ProcessingStatus> {
  const dto = await apiFetch<JobStatusDto>(`/api/pipeline/${jobId}`);
  return mapStatus(dto);
}

/**
 * One row of the job history list, from `GET /api/pipeline` (new endpoint,
 * added alongside the History page -- may not be deployed yet; callers must
 * treat a thrown ApiError as "history unavailable", never fabricate rows).
 */
export interface JobSummary {
  jobId: string;
  sourceFilename: string;
  stage: ProcessingStage;
  isGeoreferenced: boolean;
  /** Unix timestamp, seconds. */
  createdAt: number;
  /** Unix timestamp, seconds. */
  updatedAt: number;
  thumbnailUrl: string | null;
  buildingCount: number | null;
}

interface JobSummaryDto {
  job_id: string;
  source_filename: string;
  stage: ProcessingStage;
  is_georeferenced: boolean;
  created_at: number;
  updated_at: number;
  thumbnail_url: string | null;
  building_count: number | null;
}

interface JobListResponseDto {
  jobs: JobSummaryDto[];
}

export async function listJobs(): Promise<JobSummary[]> {
  const dto = await apiFetch<JobListResponseDto>("/api/pipeline");
  return dto.jobs.map((j) => ({
    jobId: j.job_id,
    sourceFilename: j.source_filename,
    stage: j.stage,
    isGeoreferenced: j.is_georeferenced,
    createdAt: j.created_at,
    updatedAt: j.updated_at,
    thumbnailUrl: j.thumbnail_url ? outputUrl(j.thumbnail_url) : null,
    buildingCount: j.building_count,
  }));
}

/** Permanently removes a job and its outputs (`DELETE /api/pipeline/{job_id}`). */
export async function deleteJob(jobId: string): Promise<void> {
  await apiFetch<void>(`/api/pipeline/${jobId}`, { method: "DELETE" });
}

/** Resolves a backend-relative output path (e.g. from `outputs.fused_depth_preview_png`) to a full URL. */
export function outputUrl(path: string): string {
  return `${API_BASE_URL}${path}`;
}

/**
 * Shape of outputs/{job_id}/metadata.json, written by
 * backend/app/pipeline/run.py at the end of a successful run. Fetched
 * directly as a static file (it's just another pipeline output), not
 * through a bespoke endpoint.
 */
export interface ResultMetadata {
  job_id: string;
  source_filename: string;
  is_georeferenced: boolean;
  crs: string | null;
  width: number;
  height: number;
  da_v2_encoder: string;
  da_v2_stats: { min: number; max: number; mean: number };
  depth_pro_stats: { min: number; max: number; mean: number };
  depth_pro_focallength_px: number;
  fusion_method: string;
  confidence_available: boolean;
  calibration_status: "calibrated" | "unavailable" | "not_applicable";
  calibration_note: string;
  dsm_is_metric: boolean;
  mesh_status: "pending" | "ready";
  mesh_vertex_count?: number;
  mesh_triangle_count?: number;
  mesh_grid_rows?: number;
  mesh_grid_cols?: number;
  mesh_downsample_factor?: number;
  mesh_elevation_min?: number;
  mesh_elevation_max?: number;
  mesh_texture_width?: number;
  mesh_texture_height?: number;
  mesh_spacing_units?: "meters" | "scene-units";
  mesh_vertical_exaggeration?: number;
  /** Real-world spacing PER DOWNSAMPLED MESH GRID CELL, not per original
   * image pixel -- divide by `mesh_downsample_factor` to get meters-per-
   * original-pixel (see app/mesh/generate.py:generate_terrain_mesh, `dx *=
   * downsample_factor`). Only meaningful when `mesh_spacing_units ===
   * "meters"`. Used by the scenarios page to convert a real-meters hazard
   * radius into the original-pixel space building footprints/backend
   * scenario endpoints share. */
  mesh_horizontal_spacing_x?: number;
}

export async function getResultMetadata(metadataUrl: string): Promise<ResultMetadata> {
  const response = await fetch(outputUrl(metadataUrl));
  if (!response.ok) {
    throw new ApiError(`Could not load result metadata (${response.status})`, response.status);
  }
  return (await response.json()) as ResultMetadata;
}

/**
 * The three endpoints below (`buildings`, `disaster-zones`, `validation`)
 * are new Phase-3 backend additions and may not be deployed/populated for a
 * given job yet. Every caller MUST treat a thrown ApiError (network error,
 * 404, 501, etc.) as "no data yet for this job" -- a graceful empty/absent
 * state, never a crash or a fabricated value.
 */

interface BuildingDto {
  id: string;
  footprint: number[][];
  height_m: number;
  is_metric: boolean;
  confidence: number;
  shadow_estimate_m: number | null;
  depth_vs_shadow_delta_m: number | null;
}

interface BuildingsResponseDto {
  buildings: BuildingDto[];
}

export async function getBuildings(jobId: string): Promise<Building[]> {
  const dto = await apiFetch<BuildingsResponseDto>(`/api/pipeline/${jobId}/buildings`);
  return dto.buildings.map((b) => ({
    id: b.id,
    footprint: b.footprint,
    heightM: b.height_m,
    isMetric: b.is_metric,
    confidence: b.confidence,
    shadowEstimateM: b.shadow_estimate_m,
    depthVsShadowDeltaM: b.depth_vs_shadow_delta_m,
  }));
}

interface DisasterZoneDto {
  type: DisasterZoneType;
  geometry: { type: string; coordinates: number[][][] };
  risk_level: string | null;
  notes: string | null;
  properties?: Record<string, unknown>;
}

interface DisasterZonesResponseDto {
  zones: DisasterZoneDto[];
}

export async function getDisasterZones(jobId: string, aircraftType?: "plane" | "helicopter"): Promise<DisasterZone[]> {
  const query = aircraftType ? `?aircraft_type=${aircraftType}` : "";
  const dto = await apiFetch<DisasterZonesResponseDto>(`/api/pipeline/${jobId}/disaster-zones${query}`);
  return dto.zones.map((z) => ({
    type: z.type,
    geometry: z.geometry,
    riskLevel: z.risk_level,
    notes: z.notes,
    properties: z.properties,
  }));
}

/**
 * ---------------------------------------------------------------------------
 * Scenario endpoints (src/app/scenarios). Field names below are the REAL,
 * finalized backend contract (app/schemas/pipeline.py:
 * FloodSimulationResponse / HazardExposureResponse / WildfireDroneResponse,
 * confirmed against the backend agent's report and reconciled here -- the
 * scenario UI was originally coded against a guessed contract before the
 * backend landed; see context/decisions-log.md's integration-pass entry for
 * exactly what was wrong and fixed). Status strings are real too: flood uses
 * "simulated"/"unavailable", hazard-exposure uses "estimated"/"unavailable",
 * wildfire-drone uses "computed"/"unavailable" -- there is no shared "ok"
 * value across them.
 * ---------------------------------------------------------------------------
 */

export interface FloodScenarioResult {
  status: "simulated" | "unavailable";
  note: string | null;
  waterLevel: number | null;
  unit: "meters" | "relative_dsm_units" | null;
  submergedPixelFraction: number | null;
  submergedAreaM2: number | null;
  areaNote: string | null;
  affectedBuildingIds: number[];
  previewUrl: string | null;
}

interface FloodScenarioDto {
  status: "simulated" | "unavailable";
  note: string;
  water_level: number | null;
  unit: "meters" | "relative_dsm_units" | null;
  submerged_pixel_fraction: number | null;
  submerged_area_m2: number | null;
  area_note: string | null;
  affected_building_ids: number[];
  preview_url: string | null;
}

export async function runFloodScenario(jobId: string, waterLevel: number): Promise<FloodScenarioResult> {
  const dto = await apiFetch<FloodScenarioDto>(`/api/pipeline/${jobId}/scenario/flood`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ water_level: waterLevel }),
  });
  return {
    status: dto.status,
    note: dto.note ?? null,
    waterLevel: dto.water_level ?? null,
    unit: dto.unit ?? null,
    submergedPixelFraction: dto.submerged_pixel_fraction ?? null,
    submergedAreaM2: dto.submerged_area_m2 ?? null,
    areaNote: dto.area_note ?? null,
    affectedBuildingIds: dto.affected_building_ids ?? [],
    previewUrl: dto.preview_url ? outputUrl(dto.preview_url) : null,
  };
}

/**
 * Bomb / Explosion Impact Simulation -- a real, textbook cube-root
 * scaled-distance (Z = R / W^(1/3)) structural-damage-radius safety-
 * engineering approximation (same category as ATF/OSHA/NFPA quantity-
 * distance planning tables), explicitly NOT a weapons-effects or
 * casualty/injury/lethality calculation. Bands represent structural damage
 * severity to real detected buildings only -- never render/compute a
 * casualty or fatality figure from this.
 */
export interface ExplosionImpactBand {
  severity: string;
  radiusM: number;
  buildingIds: number[];
}

export interface ExplosionImpactResult {
  status: "simulated" | "unavailable";
  note: string | null;
  epicenterPx: [number, number] | null;
  yieldKg: number | null;
  /** "meters" = real calibrated distance; "pixels" = illustrative 1px~=1m
   * visualization only (this job isn't georeferenced), not a real distance. */
  spacingUnits: "meters" | "pixels" | null;
  bands: ExplosionImpactBand[];
}

interface ExplosionImpactBandDto {
  severity: string;
  radius_m: number;
  building_ids: number[];
}

interface ExplosionImpactDto {
  status: "simulated" | "unavailable";
  note: string;
  epicenter_px: number[] | null;
  yield_kg: number | null;
  spacing_units: "meters" | "pixels" | null;
  bands: ExplosionImpactBandDto[];
}

export async function runBombSimulationScenario(
  jobId: string,
  params: { epicenterPx: [number, number]; yieldKg: number },
): Promise<ExplosionImpactResult> {
  const dto = await apiFetch<ExplosionImpactDto>(`/api/pipeline/${jobId}/scenario/bomb-simulation`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      epicenter_px: params.epicenterPx,
      yield_kg: params.yieldKg,
    }),
  });
  return {
    status: dto.status,
    note: dto.note ?? null,
    epicenterPx: dto.epicenter_px ? [dto.epicenter_px[0], dto.epicenter_px[1]] : null,
    yieldKg: dto.yield_kg ?? null,
    spacingUnits: dto.spacing_units ?? null,
    bands: (dto.bands ?? []).map((b) => ({ severity: b.severity, radiusM: b.radius_m, buildingIds: b.building_ids ?? [] })),
  };
}

export interface WildfireDroneAssumptions {
  waterExitVelocityMps: number;
  g: number;
  caveats: string[];
}

export interface WildfireDroneResult {
  status: "computed" | "unavailable";
  note: string | null;
  targetElevationM: number | null;
  hoverAltitudeAglM: number | null;
  droneAbsoluteAltitudeM: number | null;
  fallTimeS: number | null;
  horizontalReachM: number | null;
  assumptions: WildfireDroneAssumptions | null;
}

interface WildfireDroneDto {
  status: "computed" | "unavailable";
  note: string;
  target_elevation_m: number | null;
  hover_altitude_agl_m: number | null;
  drone_absolute_altitude_m: number | null;
  fall_time_s: number | null;
  horizontal_reach_m: number | null;
  assumptions: { water_exit_velocity_mps: number; g: number; caveats: string[] } | null;
}

export async function runWildfireDroneScenario(
  jobId: string,
  params: { firePointPx: [number, number]; hoverAltitudeAglM?: number; waterExitVelocityMps?: number },
): Promise<WildfireDroneResult> {
  const dto = await apiFetch<WildfireDroneDto>(`/api/pipeline/${jobId}/scenario/wildfire-drone`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fire_point_px: params.firePointPx,
      hover_altitude_agl_m: params.hoverAltitudeAglM,
      water_exit_velocity_mps: params.waterExitVelocityMps,
    }),
  });
  return {
    status: dto.status,
    note: dto.note ?? null,
    targetElevationM: dto.target_elevation_m ?? null,
    hoverAltitudeAglM: dto.hover_altitude_agl_m ?? null,
    droneAbsoluteAltitudeM: dto.drone_absolute_altitude_m ?? null,
    fallTimeS: dto.fall_time_s ?? null,
    horizontalReachM: dto.horizontal_reach_m ?? null,
    assumptions: dto.assumptions
      ? {
          waterExitVelocityMps: dto.assumptions.water_exit_velocity_mps,
          g: dto.assumptions.g,
          caveats: dto.assumptions.caveats ?? [],
        }
      : null,
  };
}

interface ValidationDto {
  status: "calibrated" | "unavailable";
  rmse: number | null;
  mae: number | null;
  correlation: number | null;
  valid_pixel_count: number | null;
}

export async function getValidation(jobId: string): Promise<ValidationResult> {
  const dto = await apiFetch<ValidationDto>(`/api/pipeline/${jobId}/validation`);
  return {
    available: dto.status === "calibrated",
    rmse: dto.rmse,
    mae: dto.mae,
    correlation: dto.correlation,
    validPixelCount: dto.valid_pixel_count,
  };
}
