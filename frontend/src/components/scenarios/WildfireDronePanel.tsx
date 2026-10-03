"use client";

import { useState } from "react";

import { runWildfireDroneScenario, type WildfireDroneResult } from "@/lib/api/pipeline";

interface WildfireDronePanelProps {
  jobId: string;
  /** Fire location picked on the live 3D terrain by the parent scenarios
   * page (TerrainViewer's onTerrainPick, in pixel space) -- this panel no
   * longer owns its own 2D click surface. `null` until picked. */
  firePointPx: [number, number] | null;
  pickModeActive: boolean;
  onRequestPick: () => void;
  /** Reports the real backend result (or null on reset/error) up to the
   * parent so it can render a live drone/fire marker on the 3D terrain from
   * a CONFIRMED computed result -- `hoverAltitudeAglM` is already part of
   * `WildfireDroneResult`, so no extra echo param is needed here. */
  onResult?: (result: WildfireDroneResult | null) => void;
}

type RunState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; result: WildfireDroneResult }
  | { status: "error"; message: string };

// Illustrative pre-fill defaults, clearly labeled as assumptions in the UI --
// not real product specs. Matches the backend's own defaults
// (app/schemas/pipeline.py:WildfireDroneRequest) so a first, un-edited
// submission reflects exactly what the physics note describes.
const DEFAULT_HOVER_ALTITUDE_M = 30;
const DEFAULT_EXIT_VELOCITY_MPS = 20;

export function WildfireDronePanel({
  jobId,
  firePointPx,
  pickModeActive,
  onRequestPick,
  onResult,
}: WildfireDronePanelProps) {
  const [hoverAltitude, setHoverAltitude] = useState(DEFAULT_HOVER_ALTITUDE_M);
  const [exitVelocity, setExitVelocity] = useState(DEFAULT_EXIT_VELOCITY_MPS);
  const [state, setState] = useState<RunState>({ status: "idle" });

  async function handleRun() {
    if (!firePointPx) return;
    setState({ status: "loading" });
    try {
      const result = await runWildfireDroneScenario(jobId, {
        firePointPx,
        hoverAltitudeAglM: hoverAltitude,
        waterExitVelocityMps: exitVelocity,
      });
      setState({ status: "ready", result });
      onResult?.(result);
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : "Wildfire drone endpoint is not reachable.",
      });
      onResult?.(null);
    }
  }

  const ready = state.status === "ready" ? state.result : null;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">Wildfire Drone Water-Drop Calculator</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Real projectile-motion physics using the DSM&apos;s real elevation at the clicked point: how far a water
          drop travels, and from what hover altitude, to reach the marked fire location.
        </p>
      </div>

      <div className="glass-panel rounded-2xl p-5">
        <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/20 px-4 py-3">
          <div className="text-sm">
            <p className="font-medium text-foreground">
              {firePointPx ? "Fire location set" : "No fire location picked yet"}
            </p>
            <p className="text-xs text-muted-foreground">
              {firePointPx
                ? `Pixel (${firePointPx[0].toFixed(0)}, ${firePointPx[1].toFixed(0)}) on the 3D terrain below.`
                : "Click “Pick on Terrain”, then click a point on the live 3D view below."}
            </p>
          </div>
          <button
            type="button"
            onClick={onRequestPick}
            className={`shrink-0 rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
              pickModeActive
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
            }`}
          >
            {pickModeActive ? "Click the terrain..." : firePointPx ? "Re-pick Fire Location" : "Pick on Terrain"}
          </button>
        </div>

        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="hover-alt" className="mb-1 block text-sm font-medium text-foreground">
                Hover altitude AGL (m)
              </label>
              <input
                id="hover-alt"
                type="number"
                min={1}
                value={hoverAltitude}
                onChange={(e) => setHoverAltitude(Number(e.target.value))}
                className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground"
              />
            </div>
            <div>
              <label htmlFor="exit-vel" className="mb-1 block text-sm font-medium text-foreground">
                Water exit velocity (m/s)
              </label>
              <input
                id="exit-vel"
                type="number"
                min={0.1}
                step={0.1}
                value={exitVelocity}
                onChange={(e) => setExitVelocity(Number(e.target.value))}
                className="w-full rounded-lg border border-input bg-card px-3 py-2 text-sm text-foreground"
              />
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Illustrative assumptions, not real product specs -- adjust to match an actual drone&apos;s documented
            capability if available.
          </p>

          <button
            type="button"
            disabled={!firePointPx || state.status === "loading"}
            onClick={handleRun}
            className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {state.status === "loading" ? "Calculating..." : "Calculate Drop"}
          </button>
          {!firePointPx && (
            <p className="text-xs text-muted-foreground">Pick a fire location on the 3D terrain first.</p>
          )}

          {state.status === "error" && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {state.message}
            </p>
          )}

          {ready?.status === "unavailable" && (
            <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
              {ready.note ?? "This job cannot run the wildfire-drone scenario (e.g. no DSM available)."}
            </p>
          )}

          {ready?.status === "computed" && (
            <div className="space-y-3 rounded-lg border border-border bg-muted/20 p-4">
              <div className="grid grid-cols-2 gap-3">
                <Stat
                  label="How far (horizontal reach)"
                  value={ready.horizontalReachM !== null ? `${ready.horizontalReachM.toFixed(1)} m` : "n/a"}
                />
                <Stat
                  label="Hover altitude (AGL)"
                  value={ready.hoverAltitudeAglM !== null ? `${ready.hoverAltitudeAglM.toFixed(1)} m` : "n/a"}
                />
                <Stat
                  label="Target elevation (DSM)"
                  value={ready.targetElevationM !== null ? `${ready.targetElevationM.toFixed(1)} m` : "n/a"}
                />
                <Stat label="Fall time" value={ready.fallTimeS !== null ? `${ready.fallTimeS.toFixed(2)} s` : "n/a"} />
              </div>
              {ready.note && (
                <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  {ready.note}
                </p>
              )}
              {ready.assumptions && (
                <div>
                  <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                    Assumptions
                  </p>
                  <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs text-muted-foreground">
                    <dt className="text-muted-foreground">Water exit velocity</dt>
                    <dd className="text-foreground">{ready.assumptions.waterExitVelocityMps} m/s</dd>
                    <dt className="text-muted-foreground">g</dt>
                    <dd className="text-foreground">{ready.assumptions.g} m/s²</dd>
                  </dl>
                  {ready.assumptions.caveats.length > 0 && (
                    <ul className="mt-1.5 list-inside list-disc text-xs text-muted-foreground">
                      {ready.assumptions.caveats.map((caveat) => (
                        <li key={caveat}>{caveat}</li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {ready?.status === "computed" && (
        <DropDiagram
          hoverAltitudeM={ready.hoverAltitudeAglM}
          horizontalReachM={ready.horizontalReachM}
          targetElevationM={ready.targetElevationM}
          droneAbsoluteAltitudeM={ready.droneAbsoluteAltitudeM}
        />
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-lg font-semibold text-primary">{value}</p>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
    </div>
  );
}

/** Simple, schematic (not to a physical scale beyond relative proportions)
 * side-view SVG: drone at hover altitude, a water arc, and the target on the
 * ground -- a nice-to-have visual aid for the numeric result above. */
function DropDiagram({
  hoverAltitudeM,
  horizontalReachM,
  targetElevationM,
  droneAbsoluteAltitudeM,
}: {
  hoverAltitudeM: number | null;
  horizontalReachM: number | null;
  targetElevationM: number | null;
  droneAbsoluteAltitudeM: number | null;
}) {
  const width = 560;
  const height = 220;
  const groundY = height - 30;
  const droneX = 90;
  const droneY = 40;
  const targetX = width - 90;

  return (
    <div className="glass-panel rounded-2xl p-5">
      <p className="mb-3 text-sm font-medium text-foreground">Side-View Diagram (schematic, not to scale)</p>
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full text-muted-foreground" role="img" aria-label="Drone water-drop side view">
        <line x1={0} y1={groundY} x2={width} y2={groundY} stroke="currentColor" strokeWidth={1.5} opacity={0.5} />
        <line x1={droneX} y1={droneY} x2={droneX} y2={groundY} stroke="currentColor" strokeWidth={1} strokeDasharray="4 4" opacity={0.4} />
        <path
          d={`M ${droneX} ${droneY} Q ${(droneX + targetX) / 2} ${groundY + 20} ${targetX} ${groundY}`}
          fill="none"
          className="text-primary"
          stroke="currentColor"
          strokeWidth={2.5}
        />
        <circle cx={droneX} cy={droneY} r={8} className="fill-current text-primary" />
        <text x={droneX} y={droneY - 14} textAnchor="middle" className="fill-current text-[11px]">
          Drone
        </text>
        <circle cx={targetX} cy={groundY} r={6} className="fill-current text-destructive" />
        <text x={targetX} y={groundY + 20} textAnchor="middle" className="fill-current text-[11px]">
          Fire target
        </text>
        <text x={droneX - 6} y={(droneY + groundY) / 2} textAnchor="end" className="fill-current text-[10px]">
          {hoverAltitudeM !== null ? `${hoverAltitudeM.toFixed(0)} m AGL` : ""}
        </text>
        <text x={(droneX + targetX) / 2} y={groundY + 40} textAnchor="middle" className="fill-current text-[10px]">
          {horizontalReachM !== null ? `${horizontalReachM.toFixed(0)} m horizontal reach` : ""}
        </text>
      </svg>
      <div className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[11px] text-muted-foreground">
        {droneAbsoluteAltitudeM !== null && <span>Drone absolute altitude: {droneAbsoluteAltitudeM.toFixed(1)} m</span>}
        {targetElevationM !== null && <span>Target (ground) elevation: {targetElevationM.toFixed(1)} m</span>}
      </div>
    </div>
  );
}
