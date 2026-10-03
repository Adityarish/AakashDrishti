import { API_BASE_URL } from "./client";
import { apiFetch, apiJson, apiUpload, getToken } from "./http";
import type {
  AnalystStatus,
  AuthUser,
  BenchmarkTable,
  Capabilities,
  ExplosionResult,
  Finding,
  FloodResult,
  Gcp,
  JobStatus,
  JobSummary,
  LandingResult,
  ProbeResult,
  ProfileResult,
  RunOptions,
  SelfCheck,
  Sample,
  SceneManifest,
  SceneMetadata,
  SceneSummary,
  SlopeResult,
  UnityScenarioRequest,
  UnityScenarioResult,
  UploadInfo,
  ValidationLab,
  ViewshedResult,
  WildfireResult,
} from "../sceneTypes";

export { ApiError } from "./client";
export { API_BASE_URL };

/** Resolve a backend-relative path (e.g. /api/pipeline/output/<id>/ortho.jpg) to a full URL. */
export function outputUrl(path: string): string {
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

export function jobFileUrl(jobId: string, filename: string): string {
  return `${API_BASE_URL}/api/pipeline/output/${jobId}/${filename}`;
}

export const capabilities = () => apiFetch<Capabilities>("/api/capabilities");

// ---- samples & upload ----
export const listSamples = () => apiFetch<{ samples: Sample[] }>("/api/samples").then((r) => r.samples);
export const loadSample = (id: string, variant: "png" | "geotiff") =>
  apiFetch<UploadInfo>(`/api/samples/${id}/load?variant=${variant}`, { method: "POST" });
export const sampleThumb = (id: string) => `${API_BASE_URL}/api/samples/${id}/thumb`;

export function uploadImage(file: File, onProgress?: (fraction: number) => void): Promise<UploadInfo> {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<UploadInfo>("/api/project/upload", form, onProgress);
}
export const getProject = (id: string) => apiFetch<UploadInfo>(`/api/project/${id}`);
/** New job from an earlier job's uploaded image (the earlier results are left untouched). */
export const cloneProject = (id: string) => apiFetch<UploadInfo>(`/api/project/${id}/clone`, { method: "POST" });
export const deleteProject = (id: string) => apiFetch<{ deleted: string }>(`/api/project/${id}`, { method: "DELETE" });
export const putGcps = (id: string, gcps: Gcp[]) => apiJson<{ count: number }>(`/api/project/${id}/gcps`, "PUT", { gcps });
export const getGcps = (id: string) => apiFetch<{ gcps: Gcp[] }>(`/api/project/${id}/gcps`).then((r) => r.gcps);
export function uploadGcpCsv(id: string, file: File): Promise<{ count: number }> {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<{ count: number }>(`/api/project/${id}/gcps/csv`, form);
}

// ---- pipeline ----
export const runPipeline = (id: string, options?: RunOptions) =>
  apiJson<JobStatus>(`/api/pipeline/run/${id}`, "POST", options ?? null);
export const cancelPipeline = (id: string) => apiFetch<JobStatus>(`/api/pipeline/${id}/cancel`, { method: "POST" });
export const getJob = (id: string) => apiFetch<JobStatus>(`/api/pipeline/${id}`);
export const listJobs = () => apiFetch<{ jobs: JobSummary[] }>("/api/pipeline").then((r) => r.jobs);

export function subscribeJob(
  id: string,
  onUpdate: (job: JobStatus) => void,
  onDone: () => void,
  onError: () => void,
): () => void {
  const token = getToken();
  const source = new EventSource(`${API_BASE_URL}/api/pipeline/${id}/events${token ? `?token=${encodeURIComponent(token)}` : ""}`);
  source.addEventListener("progress", (event) => onUpdate(JSON.parse((event as MessageEvent).data) as JobStatus));
  source.addEventListener("done", () => {
    source.close();
    onDone();
  });
  source.onerror = () => {
    source.close();
    onError();
  };
  return () => source.close();
}

async function getJsonFile<T>(id: string, name: string): Promise<T> {
  const response = await fetch(jobFileUrl(id, name), { cache: "no-store" });
  if (!response.ok) throw new Error(`${name} is not available for this scene yet (${response.status}).`);
  return (await response.json()) as T;
}
export const getMetadata = (id: string) => getJsonFile<SceneMetadata>(id, "metadata.json");
export const getSceneManifest = (id: string) => getJsonFile<SceneManifest>(id, "scene.json");

// ---- analysis ----
export const sceneSummary = (id: string) => apiFetch<SceneSummary>(`/api/analysis/${id}/summary`);
export const probe = (id: string, col: number, row: number) =>
  apiFetch<ProbeResult>(`/api/analysis/${id}/probe?col=${col.toFixed(2)}&row=${row.toFixed(2)}`);
export const profile = (id: string, x0: number, y0: number, x1: number, y1: number) =>
  apiFetch<ProfileResult>(`/api/analysis/${id}/profile?x0=${x0}&y0=${y0}&x1=${x1}&y1=${y1}&samples=240`);
export const runFlood = (id: string, level: number, seed = "auto", col?: number, row?: number) =>
  apiJson<FloodResult>(`/api/analysis/${id}/flood`, "POST", { level, seed, col, row });
export const runLanding = (id: string, body: { min_radius_m: number; max_slope_deg: number; top_n?: number; flood_level?: number | null }) =>
  apiJson<LandingResult>(`/api/analysis/${id}/landing-zones`, "POST", body);
export const runSlope = (id: string, threshold_deg: number) =>
  apiJson<SlopeResult>(`/api/analysis/${id}/slope-hazard`, "POST", { threshold_deg });
export const runViewshed = (id: string, col: number, row: number, observer_height_m: number, max_radius_m?: number) =>
  apiJson<ViewshedResult>(`/api/analysis/${id}/viewshed`, "POST", { col, row, observer_height_m, max_radius_m });

export const runExplosion = (id: string, body: { col: number; row: number; yield_kg: number }) =>
  apiJson<ExplosionResult>(`/api/analysis/${id}/explosion`, "POST", body);
export const runWildfire = (id: string, body: { col: number; row: number; hover_agl_m: number; exit_velocity_mps: number }) =>
  apiJson<WildfireResult>(`/api/analysis/${id}/wildfire-drone`, "POST", body);
/** Writes a copy of the job's Unity scene with this scenario painted on the terrain; the viewer loads `job_param`. */
export const buildUnityScenario = (id: string, body: UnityScenarioRequest) =>
  apiJson<UnityScenarioResult>(`/api/analysis/${id}/unity-scenario`, "POST", body);

// ---- validation ----
export const getSelfCheck = (id: string) => apiFetch<SelfCheck>(`/api/validation/${id}/self-check`);
export const getValidation = (id: string) => apiFetch<ValidationLab>(`/api/validation/${id}`);
export function uploadReference(
  id: string,
  file: File,
  kind: "auto" | "dsm" | "ndsm",
  onProgress?: (fraction: number) => void,
): Promise<ValidationLab> {
  const form = new FormData();
  form.append("file", file);
  form.append("reference_kind", kind);
  return apiUpload<ValidationLab>(`/api/validation/${id}/reference`, form, onProgress);
}
export const applySampleReference = (id: string) => apiFetch<ValidationLab>(`/api/validation/${id}/sample-reference`, { method: "POST" });
export const benchmarks = () => apiFetch<BenchmarkTable>("/api/validation/benchmarks/table");

// ---- analyst ----
export const analystStatus = () => apiFetch<AnalystStatus>("/api/analyst/status");
export const listFindings = (id: string) => apiFetch<{ findings: Finding[] }>(`/api/analyst/${id}/findings`).then((r) => r.findings);
export const addFinding = (id: string, body: { tool: string; title: string; text: string; data?: Record<string, unknown> }) =>
  apiJson<Finding>(`/api/analyst/${id}/findings`, "POST", body);
export const clearFindings = (id: string) => apiFetch<{ cleared: boolean }>(`/api/analyst/${id}/findings`, { method: "DELETE" });
export const cachedReport = (id: string) =>
  apiFetch<{ available: boolean; report: { text: string; mode: string; generated_at: number; unverified_numbers: string[]; notice: string | null } | null }>(
    `/api/analyst/${id}/report`,
  );
export const askAnalyst = (id: string, question: string) =>
  apiJson<{ answer: string; mode: string; tools: string[]; notice?: string }>(`/api/analyst/${id}/ask`, "POST", { question });

export type ReportEvent =
  | { event: "tool"; name: string; label: string }
  | { event: "text"; text: string }
  | { event: "reset" }
  | { event: "notice"; text: string }
  | { event: "done"; mode: string; unverified_numbers: string[]; generated_at: number };

/** POST an SSE endpoint via fetch (so the auth header can be sent) and dispatch each `data:` frame. */
async function streamSse<T>(path: string, body: unknown, onEvent: (event: T) => void, signal?: AbortSignal, label = "Request"): Promise<void> {
  const token = getToken();
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) throw new Error(`${label} failed (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data:"));
      if (line) onEvent(JSON.parse(line.slice(5)) as T);
    }
  }
}

/** Stream the analyst report over SSE. */
export const streamReport = (id: string, onEvent: (event: ReportEvent) => void, forceOffline = false, signal?: AbortSignal) =>
  streamSse<ReportEvent>(`/api/analyst/${id}/report/stream`, { force_offline: forceOffline }, onEvent, signal, "Report request");

export type ChatEvent =
  | { event: "tool"; name: string; label: string }
  | { event: "text"; text: string }
  | { event: "reset" }
  | { event: "notice"; text: string }
  | { event: "done"; mode: string; tools: string[]; unverified_numbers: string[] };

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/** Stream a multi-turn chat answer about this scene. `history` carries the prior turns. */
export const streamChat = (id: string, question: string, history: ChatTurn[], onEvent: (event: ChatEvent) => void, signal?: AbortSignal) =>
  streamSse<ChatEvent>(`/api/analyst/${id}/chat/stream`, { question, history }, onEvent, signal, "Chat request");

// ---- detected objects ----
export interface DetectedObject {
  id: number;
  label: string;
  confidence: number;
  polygon: [number, number][];
  center_px: [number, number];
  area_px: number;
  surface_elevation: number | null;
  terrain_elevation: number | null;
  height_above_ground: number | null;
  height_reliable: boolean;
  lonlat: [number, number] | null;
}

export interface DetectedObjects {
  job_id: string;
  status: string;
  note: string;
  model?: string;
  count: number;
  returned?: number;
  counts_by_class: Record<string, number>;
  height_unit?: string;
  objects: DetectedObject[];
}

export const detectedObjects = (id: string, limit = 1000) =>
  apiFetch<DetectedObjects>(`/api/analysis/${id}/objects?limit=${limit}`);

// ---- auth ----
export const login = (email: string, password: string) =>
  apiJson<{ token: string; user: AuthUser }>("/api/auth/login", "POST", { email, password });
export const register = (email: string, password: string, name: string, role: string) =>
  apiJson<{ token: string; user: AuthUser }>("/api/auth/register", "POST", { email, password, name, role });
export const me = () => apiFetch<{ user: AuthUser; authenticated: boolean; auth_required: boolean }>("/api/auth/me");
