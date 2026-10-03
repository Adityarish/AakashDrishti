"use client";

import { useEffect, useState } from "react";

import { AppHeader } from "@/components/common/AppHeader";
import { JobPicker } from "@/components/scenarios/JobPicker";
import { FloodPanel } from "@/components/scenarios/FloodPanel";
import { BombSimulationPanel } from "@/components/scenarios/BombSimulationPanel";
import { LandingZonesPanel, type AircraftType, type SelectedLandingZone } from "@/components/scenarios/LandingZonesPanel";
import { WildfireDronePanel } from "@/components/scenarios/WildfireDronePanel";
import { TerrainViewer } from "@/components/viewer/TerrainViewer";
import {
  getJobStatus,
  getResultMetadata,
  outputUrl,
  type ExplosionImpactResult,
  type ResultMetadata,
  type WildfireDroneResult,
} from "@/lib/api/pipeline";
import { buildResultFromOutputs } from "@/hooks/useDepthWizardWorkflow";
import { PROCESSING_STAGE_ORDER, STAGE_LABEL, type ProcessingStatus } from "@/lib/types/processing";
import type { ProcessingResult } from "@/lib/types/results";

type JobLoadState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; job: ProcessingStatus; metadata: ResultMetadata | null; result: ProcessingResult }
  | { status: "error"; message: string };

const SCENARIOS = [
  {
    id: "flood",
    label: "Flood",
    description: "Bathtub-model water-rise simulation with a live 3D water plane and real submerged-area stats.",
    icon: (
      <path d="M3 16c1.5-1.5 3-1.5 4.5 0s3 1.5 4.5 0 3-1.5 4.5 0 3 1.5 4.5 0M3 20c1.5-1.5 3-1.5 4.5 0s3 1.5 4.5 0 3-1.5 4.5 0 3 1.5 4.5 0M12 3v9" strokeLinecap="round" strokeLinejoin="round" />
    ),
  },
  {
    id: "landing",
    label: "Emergency Landing Zones",
    description: "Ranked, low-slope, obstacle-free helicopter/UAV landing candidates from the real DSM.",
    icon: <path d="M4 20h16M6 20V10l6-6 6 6v10M10 20v-6h4v6" strokeLinecap="round" strokeLinejoin="round" />,
  },
  {
    id: "bomb",
    label: "Explosion Impact Simulation",
    description: "Real scaled-distance structural-damage-radius bands and which real buildings fall in each -- not a casualty calculator.",
    icon: <path d="M12 2v6m0 0l4 10H8l4-10zM4 21h16" strokeLinecap="round" strokeLinejoin="round" />,
  },
  {
    id: "wildfire",
    label: "Wildfire Drone Water-Drop",
    description: "Real projectile-motion physics for a firefighting drone's standoff distance and hover altitude.",
    icon: <path d="M12 3c2 3 4 5 4 8a4 4 0 11-8 0c0-3 2-5 4-8z" strokeLinecap="round" strokeLinejoin="round" />,
  },
] as const;

type ScenarioId = (typeof SCENARIOS)[number]["id"];

const MIN_STAGE_INDEX = PROCESSING_STAGE_ORDER.indexOf("DSM");

const BAND_COLOR: Record<string, string> = {
  severe: "#dc2626",
  moderate: "#f97316",
  light: "#facc15",
};

export default function ScenariosPage() {
  const [scenario, setScenario] = useState<ScenarioId | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [loadState, setLoadState] = useState<JobLoadState>({ status: "idle" });

  // Flood: lifted so the same value drives both the panel's debounced stats
  // request and the live, instant 3D water-plane overlay.
  const [waterLevel, setWaterLevel] = useState(5);

  // Bomb-simulation / wildfire-drone: the picked point lives here since
  // picking now happens on the shared 3D terrain, not inside either panel.
  // `pickTarget` says which scenario's picker is "armed" -- only one at a
  // time, and only while that scenario is actually selected.
  const [epicenterPx, setEpicenterPx] = useState<[number, number] | null>(null);
  const [firePointPx, setFirePointPx] = useState<[number, number] | null>(null);
  const [pickTarget, setPickTarget] = useState<"bomb" | "wildfire" | null>(null);
  const [bombResult, setBombResult] = useState<ExplosionImpactResult | null>(null);
  const [wildfireResult, setWildfireResult] = useState<WildfireDroneResult | null>(null);

  // Emergency landing: which aircraft type, and the zone the user picked
  // from LandingZonesPanel's list to visualize on the 3D terrain.
  const [aircraftType, setAircraftType] = useState<AircraftType>("helicopter");
  const [selectedZone, setSelectedZone] = useState<SelectedLandingZone | null>(null);

  // Reset to "loading" synchronously during render when the job changes --
  // this project's established pattern (a second useState tracking the
  // previous key, not a ref -- refs can't be read/written during render
  // under this project's lint config) instead of a setState-in-effect call,
  // which the same lint config also flags.
  const [lastJobId, setLastJobId] = useState<string | null>(null);
  if (jobId !== lastJobId) {
    setLastJobId(jobId);
    setLoadState(jobId ? { status: "loading" } : { status: "idle" });
    setEpicenterPx(null);
    setFirePointPx(null);
    setPickTarget(null);
    setBombResult(null);
    setWildfireResult(null);
    setSelectedZone(null);
  }

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;

    (async () => {
      try {
        const job = await getJobStatus(jobId);
        let metadata: ResultMetadata | null = null;
        if (job.outputs.metadata_json) {
          try {
            metadata = await getResultMetadata(job.outputs.metadata_json);
          } catch {
            metadata = null; // metadata.json genuinely not available yet -- not fatal to loading the job
          }
        }
        const originalUrl = job.outputs.original ? outputUrl(job.outputs.original) : "";
        const result = await buildResultFromOutputs(jobId, job.outputs, originalUrl, metadata?.is_georeferenced ?? false);
        if (!cancelled) setLoadState({ status: "ready", job, metadata, result });
      } catch (err) {
        if (!cancelled) {
          setLoadState({
            status: "error",
            message: err instanceof Error ? err.message : `Could not load job ${jobId}.`,
          });
        }
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [jobId]);

  const job = loadState.status === "ready" ? loadState.job : null;
  const metadata = loadState.status === "ready" ? loadState.metadata : null;
  const result = loadState.status === "ready" ? loadState.result : null;
  const stageIndex = job ? PROCESSING_STAGE_ORDER.indexOf(job.stage) : -1;
  const stageReady = stageIndex >= MIN_STAGE_INDEX;
  const isMetric = metadata?.dsm_is_metric ?? false;
  const imageUrl = job?.outputs.original
    ? outputUrl(job.outputs.original)
    : job?.outputs.dsm_preview_png
      ? outputUrl(job.outputs.dsm_preview_png)
      : null;

  // Real-world meters-per-ORIGINAL-image-pixel, derived (not guessed) from
  // the mesh's own per-downsampled-grid-cell spacing -- see
  // ResultMetadata.mesh_horizontal_spacing_x's doc comment for the exact
  // derivation. Only meaningful when the mesh spacing is real meters.
  const metersPerOriginalPixel =
    metadata?.mesh_spacing_units === "meters" &&
    metadata.mesh_horizontal_spacing_x != null &&
    metadata.mesh_downsample_factor
      ? metadata.mesh_horizontal_spacing_x / metadata.mesh_downsample_factor
      : null;

  function selectScenario(id: ScenarioId) {
    setScenario(id);
    setJobId(null);
  }

  function handleTerrainPick(pick: { px: number | null; py: number | null }) {
    if (pick.px == null || pick.py == null) return;
    if (pickTarget === "bomb") {
      setEpicenterPx([pick.px, pick.py]);
      setBombResult(null);
    } else if (pickTarget === "wildfire") {
      setFirePointPx([pick.px, pick.py]);
      setWildfireResult(null);
    }
    setPickTarget(null);
  }

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-10 xl:px-10">
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-foreground">Disaster Scenarios</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Interactive, decision-support simulations run live against a job&apos;s real DSM and detected buildings.
            Every figure here is a planning heuristic, not a certified survey or a guarantee.
          </p>
        </div>

        {/* Breadcrumb, once past step 1 */}
        {scenario && (
          <div className="mb-5 flex flex-wrap items-center gap-2 text-sm">
            <button
              type="button"
              onClick={() => {
                setScenario(null);
                setJobId(null);
              }}
              className="text-primary hover:underline"
            >
              Scenarios
            </button>
            <span className="text-muted-foreground">/</span>
            <span className="font-medium text-foreground">{SCENARIOS.find((s) => s.id === scenario)?.label}</span>
            {jobId && (
              <>
                <span className="text-muted-foreground">/</span>
                <span className="text-muted-foreground">{jobId.slice(0, 8)}</span>
                <button
                  type="button"
                  onClick={() => setJobId(null)}
                  className="ml-1 rounded-full border border-border px-2.5 py-0.5 text-xs text-muted-foreground hover:border-primary/40 hover:text-foreground"
                >
                  Change map
                </button>
              </>
            )}
          </div>
        )}

        {/* Step 1: scenario type */}
        {!scenario && (
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
            {SCENARIOS.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => selectScenario(s.id)}
                className="glass-panel group flex flex-col items-start gap-3 rounded-2xl p-6 text-left transition-colors hover:border-primary/40"
              >
                <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-primary/30 bg-primary/10 text-primary">
                  <svg viewBox="0 0 24 24" fill="none" className="h-6 w-6" stroke="currentColor" strokeWidth={1.75}>
                    {s.icon}
                  </svg>
                </div>
                <p className="text-base font-semibold text-foreground">{s.label}</p>
                <p className="text-xs text-muted-foreground">{s.description}</p>
                <span className="mt-1 text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
                  Select &rarr;
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Step 2: pick a map/job */}
        {scenario && !jobId && <JobPicker selectedJobId={jobId} onSelect={setJobId} />}

        {scenario && jobId && loadState.status === "loading" && (
          <div className="glass-panel rounded-2xl px-6 py-10 text-center text-sm text-muted-foreground">
            Loading job {jobId}...
          </div>
        )}

        {scenario && jobId && loadState.status === "error" && (
          <div className="rounded-2xl border border-destructive/30 bg-destructive/10 px-6 py-6 text-sm text-destructive">
            {loadState.message}
          </div>
        )}

        {scenario && jobId && job && !stageReady && (
          <div className="glass-panel rounded-2xl px-6 py-6 text-sm text-muted-foreground">
            This job is at stage <strong className="text-foreground">{STAGE_LABEL[job.stage]}</strong>, which hasn&apos;t
            reached DSM generation yet. Scenarios need at least a DSM to run against -- wait for processing to
            continue, or pick a different job.
          </div>
        )}

        {/* Step 3: live 3D simulation */}
        {scenario && jobId && job && stageReady && result && (
          <div className="grid gap-6 xl:grid-cols-[1.15fr_0.85fr]">
            <div>
              <TerrainViewer
                terrain={result.terrain}
                jobId={jobId}
                confidencePreviewUrl={result.confidence.previewUrl}
                waterLevelOverlay={scenario === "flood" ? waterLevel : null}
                elevationMin={metadata?.mesh_elevation_min ?? null}
                verticalExaggeration={metadata?.mesh_vertical_exaggeration ?? null}
                pickModeActive={pickTarget !== null}
                onTerrainPick={handleTerrainPick}
                imageWidth={metadata?.width ?? null}
                imageHeight={metadata?.height ?? null}
                metersPerOriginalPixel={metersPerOriginalPixel}
                bombMarker={
                  scenario === "bomb" && epicenterPx && bombResult?.status === "simulated"
                    ? {
                        centerPx: epicenterPx,
                        bands: bombResult.bands.map((b) => ({
                          severity: b.severity,
                          radiusM: b.radiusM,
                          color: BAND_COLOR[b.severity] ?? "#94a3b8",
                        })),
                        spacingUnits: bombResult.spacingUnits ?? "meters",
                        justComputed: bombResult,
                      }
                    : null
                }
                fireMarker={
                  scenario === "wildfire" && firePointPx
                    ? {
                        px: firePointPx,
                        hoverAltitudeAglM: wildfireResult?.hoverAltitudeAglM ?? null,
                        horizontalReachM: wildfireResult?.horizontalReachM ?? null,
                        justComputed: wildfireResult,
                      }
                    : null
                }
                landingMarker={
                  scenario === "landing" && selectedZone
                    ? {
                        centerPx: selectedZone.centerPx,
                        widthM: selectedZone.widthM,
                        lengthM: selectedZone.lengthM,
                        angleDeg: selectedZone.angleDeg,
                        aircraftType,
                        fits: selectedZone.fits,
                        spacingUnits: selectedZone.spacingUnits,
                        animate: selectedZone,
                      }
                    : null
                }
              />
              {(scenario === "bomb" || scenario === "wildfire") && (
                <p className="mt-2 text-xs text-muted-foreground">
                  {pickTarget
                    ? "Click a point on the 3D terrain above to set the location."
                    : "Use the panel's “Pick on Terrain” button, then click the 3D view above."}
                </p>
              )}
            </div>

            <div>
              {scenario === "flood" && (
                <FloodPanel
                  jobId={jobId}
                  isMetric={isMetric}
                  originalImageUrl={imageUrl}
                  waterLevel={waterLevel}
                  onWaterLevelChange={setWaterLevel}
                />
              )}
              {scenario === "landing" && (
                <LandingZonesPanel
                  jobId={jobId}
                  aircraftType={aircraftType}
                  onAircraftTypeChange={setAircraftType}
                  onSelectZone={setSelectedZone}
                />
              )}
              {scenario === "bomb" && (
                <BombSimulationPanel
                  jobId={jobId}
                  epicenterPx={epicenterPx}
                  pickModeActive={pickTarget === "bomb"}
                  onRequestPick={() => setPickTarget("bomb")}
                  onResult={setBombResult}
                />
              )}
              {scenario === "wildfire" && (
                <WildfireDronePanel
                  jobId={jobId}
                  firePointPx={firePointPx}
                  pickModeActive={pickTarget === "wildfire"}
                  onRequestPick={() => setPickTarget("wildfire")}
                  onResult={setWildfireResult}
                />
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
