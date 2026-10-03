/**
 * Processing stages mirror the backend's real job state machine
 * (backend/app/jobs/models.py JobStage), documented in IMPLEMENTATION.md
 * Section 8:
 *   UPLOADED -> VALIDATING -> DEPTH -> FUSION -> CALIBRATION -> DSM -> MESH -> READY
 *                                                                            -> FAILED
 *
 * The frontend never invents intermediate stages the backend hasn't
 * confirmed. `DEPTH` covers both Depth Anything V2 and Depth Pro internally
 * (see StageLabel below) because the backend currently reports depth
 * inference as a single stage.
 */
export type ProcessingStage =
  | "UPLOADED"
  | "VALIDATING"
  | "DEPTH"
  | "FUSION"
  | "CALIBRATION"
  | "DSM"
  | "MESH"
  | "READY"
  | "FAILED";

export const PROCESSING_STAGE_ORDER: ProcessingStage[] = [
  "UPLOADED",
  "VALIDATING",
  "DEPTH",
  "FUSION",
  "CALIBRATION",
  "DSM",
  "MESH",
  "READY",
];

export const STAGE_LABEL: Record<ProcessingStage, string> = {
  UPLOADED: "Uploading",
  VALIDATING: "Analyzing Image",
  DEPTH: "Depth Estimation (Depth Anything V2 + Depth Pro)",
  FUSION: "Elevation Fusion",
  CALIBRATION: "DEM / GCP Calibration",
  DSM: "DSM Generation",
  MESH: "3D Terrain Generation",
  READY: "Complete",
  FAILED: "Failed",
};

/**
 * Client-side workflow state. Distinct from `ProcessingStage` because it also
 * covers states the backend has no concept of (idle, local upload transfer,
 * and "the processing endpoint doesn't exist yet" as a real, surfaced error).
 */
export type WorkflowStatus =
  | "idle"
  | "selected"
  | "uploading"
  | "processing"
  | "complete"
  | "error";

export interface ProcessingStatus {
  jobId: string;
  stage: ProcessingStage;
  error: string | null;
  /** Raw backend output-artifact keys, when available; not interpreted here. */
  outputs: Record<string, string>;
  /** Backend-computed, monotonic progress reflecting real stage transitions (0-100). */
  progress: number;
}
