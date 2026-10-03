export type StepStatus = "pending" | "running" | "done" | "skipped" | "failed";

export interface Step {
  key: string;
  label: string;
  status: StepStatus;
  progress: number;
  detail: string | null;
  started_at: number | null;
  ended_at: number | null;
}

export interface LogLine {
  t: number;
  level: "info" | "warn" | "error";
  step: string | null;
  msg: string;
}

export interface RunOptions {
  gsd_m?: number | null;
  crs?: string | null;
  origin_x?: number | null;
  origin_y?: number | null;
  sun_azimuth_deg?: number | null;
  sun_elevation_deg?: number | null;
  dem_source: "auto" | "local" | "none";
  tta: boolean;
  ensemble: boolean;
  tile_size: number;
  overlap: number;
}

export type JobStage =
  | "UPLOADED"
  | "VALIDATING"
  | "DEPTH"
  | "FUSION"
  | "CALIBRATION"
  | "DSM"
  | "MESH"
  | "READY"
  | "FAILED";

export interface JobStatus {
  job_id: string;
  stage: JobStage;
  error: string | null;
  is_georeferenced: boolean;
  outputs: Record<string, string>;
  progress: number;
  mode: "absolute" | "relative";
  steps: Step[];
  logs: LogLine[];
  options: RunOptions | null;
  attempts: number;
  cancel_requested: boolean;
  summary: Record<string, string | number | null>;
  source_filename: string | null;
  is_sample: boolean;
}

export interface JobSummary {
  job_id: string;
  source_filename: string;
  stage: JobStage;
  is_georeferenced: boolean;
  created_at: number;
  updated_at: number;
  thumbnail_url: string | null;
  building_count: number | null;
  mode: "absolute" | "relative";
  progress: number;
  summary: Record<string, string | number | null>;
  is_sample: boolean;
  error: string | null;
  gcp_count: number;
}

export interface GeoInfo {
  crs: string;
  bounds: [number, number, number, number];
  resolution: [number, number];
  width: number;
  height: number;
}

export interface UploadInfo {
  job_id: string;
  filename: string;
  width: number;
  height: number;
  band_count: number;
  dtype: string;
  is_georeferenced: boolean;
  geo: GeoInfo | null;
  mode: "absolute" | "relative";
  file_format: string;
  bit_depth: number;
  size_bytes: number;
  gsd_m: number | null;
  sun_azimuth_deg: number | null;
  sun_elevation_deg: number | null;
  bounds_wgs84: [number, number, number, number] | null;
  notes: string[];
  is_sample: boolean;
  sample_id: string | null;
}

export interface Sample {
  id: string;
  title: string;
  city: string;
  landscape: string;
  featured: boolean;
  thumbnail_url: string;
  size_px: number;
  gsd_m: number;
}

export interface CalibrationSource {
  name: string;
  scale: number;
  weight: number;
  detail: string;
}

export interface SceneMetadata {
  job_id: string;
  source_filename: string;
  mode: "absolute" | "relative";
  dsm_kind: "absolute_dsm" | "pseudo_metric" | "relative";
  crs: string | null;
  bounds_wgs84: [number, number, number, number] | null;
  width: number;
  height: number;
  band_count: number;
  bit_depth: number;
  file_format: string;
  gsd_m: number | null;
  pixel_size_m: number;
  /** True when no pixel size was known and the pipeline assumed one (heights are approximate). */
  gsd_assumed?: boolean;
  sun_azimuth_deg: number | null;
  sun_elevation_deg: number | null;
  sun_azimuth_source: string;
  da_v2_checkpoint: string;
  depth_pro_used: boolean;
  depth_pro_skipped_reason: string | null;
  tiles: number;
  tta_variants: number;
  tile_size: number;
  overlap: number;
  calibration_scale: number | null;
  calibration_sources: CalibrationSource[];
  calibration_note: string;
  calibration_scale_log_sigma: number | null;
  ground_residual_rmse_m: number | null;
  gcp_residuals: { label: string; elevation_m: number; predicted_m: number; error_m: number }[];
  shadow_summary: string;
  shadow_measured: number;
  dsm_is_metric: boolean;
  mesh_triangle_count: number;
  mesh_elevation_min?: number;
  mesh_vertical_exaggeration?: number;
  mesh_horizontal_spacing_x?: number;
  mesh_downsample_factor?: number;
  mesh_spacing_units?: "meters" | "scene-units";
  /** Ground size of the Unity 3D scene in metres. */
  unity_world_size_m?: { x: number; z: number };
  is_georeferenced: boolean;
  mesh_chunks: number;
  mesh_lod0_triangles: number;
  buildings_count: number;
  height_range: [number, number];
  mean_height: number | null;
  height_unit: "m" | "relative";
  land_cover_fractions: Record<string, number>;
  timings: { inference_s: number; mesh_s: number; total_s: number };
  pixels_per_second: number;
  options: RunOptions;
}

export interface SceneChunk {
  id: string;
  window: [number, number, number, number];
  bounds: [number, number, number, number];
  lods: string[];
  triangles: number[];
  errors: number[];
}

export interface SceneManifest {
  projectId: string;
  mode: "absolute" | "relative";
  kind: string;
  crs: string | null;
  sun: { azimuth: number | null; elevation: number | null };
  texture: string;
  width: number;
  height: number;
  pixelSizeM: number;
  metersPerUnit: number;
  heightUnits: "m" | "relative";
  verticalScale: number;
  baseHeight: number;
  heightRange: [number, number];
  worldSize: [number, number];
  chunks: SceneChunk[];
  overlays: Record<string, string | null>;
}

export interface SceneSummary {
  unit: string;
  kind: string;
  is_metric: boolean;
  pixel_size_m: number;
  shape: [number, number];
  height_min: number;
  height_max: number;
  ndsm_mean: number;
  ndsm_p95: number;
  class_area_km2: Record<string, number>;
  class_fraction: Record<string, number>;
  building_count: number;
  flood_level_range: [number, number];
  flood_reference_elevation: number;
  max_slope_deg: number;
  mean_uncertainty: number;
}

export interface ProbeResult {
  col: number;
  row: number;
  elevation: number;
  height_above_ground: number;
  uncertainty: number;
  slope_deg: number;
  land_cover: string;
  lon: number | null;
  lat: number | null;
  unit: string;
}

export interface ProfileResult {
  distance_m: number[];
  surface: number[];
  terrain: number[];
  uncertainty: number[];
  length_m: number;
  unit: string;
  max_rise: number;
}

export interface FloodResult {
  level: number;
  surface_elevation: number | null;
  reference_elevation: number | null;
  unit: string;
  seed: string;
  area_km2: number;
  area_fraction: number;
  volume_m3: number | null;
  mean_depth: number;
  max_depth: number;
  affected_buildings: number;
  total_buildings: number;
  affected_footprint_m2?: number;
  total_footprint_m2?: number;
  worst_hit_areas: { area: string; flooded_fraction: number; mean_depth: number }[];
  is_metric: boolean;
  overlay_png: string | null;
  terrain_available: boolean;
  note: string | null;
}

export interface LandingSite {
  rank: number;
  col: number;
  row: number;
  clear_radius_m: number;
  mean_slope_deg: number;
  approach_clearance: number;
  approach_heading_deg: number;
  nearest_road_m: number | null;
  score: number;
  lon: number | null;
  lat: number | null;
  elevation: number;
}

export interface LandingResult {
  sites: LandingSite[];
  criteria: { min_radius_m: number; max_slope_deg: number; max_ndsm_m: number };
  candidate_area_km2: number;
  unit: string;
  disclaimer: string;
}

export interface SlopeResult {
  threshold_deg: number;
  area_km2: number;
  area_fraction: number;
  max_slope_deg: number;
  mean_slope_deg: number;
  area_km2_by_class: Record<string, number>;
  histogram: { counts: number[]; edges: number[] };
  overlay_png: string;
}

export interface ViewshedResult {
  observer: { col: number; row: number; height_m: number; elevation: number };
  visible_fraction: number;
  area_km2: number;
  farthest_visible_m: number;
  buildings_visible: number;
  overlay_png: string;
}

export interface Metrics {
  n: number;
  rmse?: number;
  mae?: number;
  bias?: number;
  nmad?: number;
  pearson_r?: number | null;
  delta1?: number | null;
  blocks?: number;
}

export interface ValidationLab {
  status: "ok" | "none";
  has_sample_reference?: boolean;
  reference_kind?: string;
  reference_name?: string;
  reference_source?: string;
  alignment?: string;
  aligned?: boolean;
  caveats?: string[];
  global?: Metrics;
  per_class?: Record<string, Metrics>;
  per_landscape?: Record<string, Metrics>;
  dem_only?: Metrics | null;
  scatter?: [number, number][];
  error_histogram?: { counts: number[]; edges: number[] };
  error_scale_m?: number;
  value_range?: [number, number];
  unit?: string;
  image_urls?: Record<string, string>;
}

export interface BenchmarkRow {
  key: string;
  label: string;
  note: string;
  measured: boolean;
  overall?: { rmse: number; mae: number; r: number; tiles: number } | null;
  urban?: { rmse: number; tiles: number } | null;
  sparse?: { rmse: number; tiles: number } | null;
  forested?: { rmse: number; tiles: number } | null;
  mixed?: { rmse: number; tiles: number } | null;
}

export interface BenchmarkTable {
  measured: boolean;
  dataset?: string;
  tiles?: number;
  protocol?: string;
  hilly?: string;
  device?: string;
  native_scale_median?: number;
  note?: string;
  rows: BenchmarkRow[];
}

export interface Finding {
  id: string;
  tool: string;
  title: string;
  text: string;
  data: Record<string, unknown>;
  created_at: number;
}

export interface AnalystStatus {
  available: boolean;
  mode: "online" | "offline_template";
  model: string | null;
  note: string;
}

export interface Capabilities {
  auth_required: boolean;
  analyst_online: boolean;
  dem_auto_download: boolean;
  device_preference: string;
  checkpoint: string;
  offline_ready: boolean;
}

export interface Gcp {
  label: string;
  elevation_m: number;
  col?: number | null;
  row?: number | null;
  x?: number | null;
  y?: number | null;
  lonlat?: boolean;
}

export interface AuthUser {
  email: string;
  name: string;
  role: "analyst" | "responder" | "viewer";
}

export interface SelfCheckItem {
  name: string;
  status: "pass" | "warn" | "info";
  detail: string;
}

export interface SelfCheck {
  verdict: "consistent" | "review" | "limited";
  unit: string;
  is_metric: boolean;
  kind: string | null;
  gsd_assumed: boolean;
  pixel_size_m: number;
  scale: number | null;
  sources: CalibrationSource[];
  shadow: {
    n: number;
    bias: number;
    mae: number;
    rmse: number;
    pearson_r: number | null;
    median_ratio: number;
    circular: boolean;
    scatter: [number, number][];
  } | null;
  gcp_rmse_m: number | null;
  ground_residual_rmse_m: number | null;
  uncertainty_mean_m: number | null;
  buildings: { count: number; median_m: number; p90_m: number; max_m: number; median_footprint_m2: number | null } | null;
  checks: SelfCheckItem[];
  note: string;
}

export interface ExplosionBand {
  severity: "severe" | "moderate" | "light";
  label: string;
  scaled_distance: number;
  radius_m: number;
  radius_px: number;
  area_km2: number;
  buildings: number;
  building_ids: number[];
  footprint_m2: number;
  tallest_m: number | null;
}

export interface ExplosionResult {
  epicentre: { col: number; row: number };
  yield_kg: number;
  total_buildings: number;
  bands: ExplosionBand[];
  nearest: { id: number; distance_m: number; height_m: number | null; band: ExplosionBand["severity"] | null }[];
  px_size_m: number;
  is_metric: boolean;
  note: string;
}

export interface WildfireResult {
  status: "computed" | "unavailable";
  note?: string;
  fall_time_s?: number;
  horizontal_reach_m?: number;
  hover_altitude_agl_m?: number;
  target_elevation_m?: number;
  drone_absolute_altitude_m?: number;
  ground_elevation_m?: number | null;
  /** "absolute" when heights are elevations above sea level, "above_ground" when the scene has no DEM. */
  elevation_kind?: "absolute" | "above_ground";
  slope_deg?: number | null;
  land_cover?: string;
  reach_px?: number;
  exit_velocity_mps?: number;
  px_size_m?: number;
  assumptions?: { water_exit_velocity_mps: number; g: number; caveats: string[] };
}

export interface UnityScenarioLegend {
  level: "low" | "medium" | "high";
  color: string;
  label: string;
}

export type UnityScenarioResult =
  | { available: false; note: string | null }
  | { available: true; job_param: string; zones: number; legend: UnityScenarioLegend[] };

export type UnityScenarioRequest =
  | { kind: "flood"; level: number }
  | { kind: "landing"; min_radius_m: number; max_slope_deg: number; flood_level?: number | null; selected_rank?: number | null }
  | { kind: "explosion"; col: number; row: number; yield_kg: number }
  | { kind: "wildfire"; col: number; row: number; hover_agl_m: number; exit_velocity_mps: number };
