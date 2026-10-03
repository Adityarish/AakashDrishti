/**
 * Result panel types. Every "available: false" field must be rendered as a
 * clearly-labeled placeholder ("not yet implemented" / "pending"), never as
 * fabricated data. See PRD.md Section 20 / CLAUDE.md Section 7 & 11.
 */

export interface DepthStats {
  min: number;
  max: number;
  mean: number;
}

export interface DepthResult {
  available: boolean;
  daV2Stats: DepthStats | null;
  depthProStats: DepthStats | null;
  depthProFocalLengthPx: number | null;
  previewUrl: string | null;
}

export interface DSMResult {
  available: boolean;
  isMetric: boolean;
  previewUrl: string | null;
  downloadUrl: string | null;
}

export interface ConfidenceResult {
  available: boolean;
  previewUrl: string | null;
}

export interface TerrainMeshResult {
  available: boolean;
  meshUrl: string | null;
  vertexCount: number | null;
  triangleCount: number | null;
  isMetric: boolean;
  spacingUnits: "meters" | "scene-units" | null;
}

export interface ValidationResult {
  available: boolean;
  rmse: number | null;
  mae: number | null;
  correlation: number | null;
  validPixelCount: number | null;
}

/**
 * Detected-building height record, from
 * GET /api/pipeline/{job_id}/buildings (new in Phase 3; backend may not
 * have this job's data yet -- callers must treat fetch failure as "no
 * buildings detected for this job", not a crash).
 */
export interface Building {
  id: string;
  /** Polygon footprint in mesh/image pixel space, as returned by the backend. */
  footprint: number[][];
  heightM: number;
  isMetric: boolean;
  confidence: number;
  shadowEstimateM: number | null;
  depthVsShadowDeltaM: number | null;
}

export type DisasterZoneType = "landing_zone" | "flood_risk" | "fire_access_risk";

/**
 * Disaster-management overlay zone, from
 * GET /api/pipeline/{job_id}/disaster-zones (new in Phase 3).
 */
export interface DisasterZone {
  type: DisasterZoneType;
  /** GeoJSON-like polygon geometry, e.g. { type: "Polygon", coordinates: [...] }. */
  geometry: { type: string; coordinates: number[][][] };
  riskLevel: string | null;
  notes: string | null;
  /**
   * Backend `app.schemas.pipeline.DisasterZone.properties` -- a free-form bag
   * that, for `landing_zone` features, is expected to carry the ranking
   * inputs (e.g. area/flatness) the backend used to order zones. Optional
   * and untyped since the backend hasn't documented exact key names for this
   * yet; consumers must read defensively (see scenarios/LandingZonesPanel).
   */
  properties?: Record<string, unknown>;
}

export interface ProcessingResult {
  jobId: string;
  /** Object URL of the user's own uploaded file -- never a repo/sample asset. */
  originalImageUrl: string;
  isGeoreferenced: boolean;
  depth: DepthResult;
  dsm: DSMResult;
  confidence: ConfidenceResult;
  terrain: TerrainMeshResult;
  validation: ValidationResult;
}
