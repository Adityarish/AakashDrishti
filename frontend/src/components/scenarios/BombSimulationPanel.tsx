"use client";

import { useState } from "react";

import { runBombSimulationScenario, type ExplosionImpactResult } from "@/lib/api/pipeline";

interface BombSimulationPanelProps {
  jobId: string;
  /** Epicenter picked on the live 3D terrain by the parent scenarios page
   * (TerrainViewer's onTerrainPick, in pixel space). `null` until picked. */
  epicenterPx: [number, number] | null;
  pickModeActive: boolean;
  onRequestPick: () => void;
  /** Reports the real backend result (or null on reset/error) up to the
   * parent so it can render the concentric impact rings on the 3D terrain
   * from a CONFIRMED computed result. */
  onResult?: (result: ExplosionImpactResult | null) => void;
}

type RunState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; result: ExplosionImpactResult }
  | { status: "error"; message: string };

const YIELD_PRESETS = [
  { label: "Small industrial cylinder (~50 kg)", value: 50 },
  { label: "Vehicle-borne (~500 kg)", value: 500 },
  { label: "Large industrial (~2000 kg)", value: 2000 },
] as const;

const BAND_COLOR: Record<string, string> = {
  severe: "#dc2626",
  moderate: "#f97316",
  light: "#facc15",
};

/**
 * Explosion Impact Simulation -- a real cube-root scaled-distance
 * structural-damage-radius safety-engineering approximation (same category
 * as ATF/OSHA/NFPA quantity-distance planning tables). Explicitly NOT a
 * weapons-effects or casualty/injury/lethality calculator -- never render a
 * casualty/death figure here.
 */
export function BombSimulationPanel({
  jobId,
  epicenterPx,
  pickModeActive,
  onRequestPick,
  onResult,
}: BombSimulationPanelProps) {
  const [yieldKg, setYieldKg] = useState(500);
  const [state, setState] = useState<RunState>({ status: "idle" });

  async function handleRun() {
    if (!epicenterPx) return;
    setState({ status: "loading" });
    try {
      const result = await runBombSimulationScenario(jobId, { epicenterPx, yieldKg });
      setState({ status: "ready", result });
      onResult?.(result);
    } catch (err) {
      setState({
        status: "error",
        message: err instanceof Error ? err.message : "Bomb simulation endpoint is not reachable.",
      });
      onResult?.(null);
    }
  }

  const ready = state.status === "ready" ? state.result : null;

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">Explosion Impact Simulation</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          A real cube-root scaled-distance structural-damage-radius approximation (the same category of safety-
          engineering tool as ATF/OSHA/NFPA quantity-distance planning tables): mark a point, and see the real
          buildings within each structural-damage severity band. Not a weapons-effects or casualty/injury/
          lethality calculation.
        </p>
      </div>

      <div className="glass-panel rounded-2xl p-5">
        <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/20 px-4 py-3">
          <div className="text-sm">
            <p className="font-medium text-foreground">
              {epicenterPx ? "Epicenter set" : "No epicenter picked yet"}
            </p>
            <p className="text-xs text-muted-foreground">
              {epicenterPx
                ? `Pixel (${epicenterPx[0].toFixed(0)}, ${epicenterPx[1].toFixed(0)}) on the 3D terrain below.`
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
            {pickModeActive ? "Click the terrain..." : epicenterPx ? "Re-pick Epicenter" : "Pick on Terrain"}
          </button>
        </div>

        <div className="space-y-3">
          <label htmlFor="yield-kg" className="mb-1 block text-sm font-medium text-foreground">
            Yield: {yieldKg.toLocaleString()} kg (TNT-equivalent)
          </label>
          <div className="flex flex-wrap gap-2">
            {YIELD_PRESETS.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => setYieldKg(preset.value)}
                className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-colors ${
                  yieldKg === preset.value
                    ? "bg-primary text-primary-foreground"
                    : "border border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
                }`}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <input
            id="yield-kg"
            type="range"
            min={1}
            max={5000}
            step={1}
            value={yieldKg}
            onChange={(e) => setYieldKg(Number(e.target.value))}
            className="w-full accent-primary"
          />
          <p className="text-xs text-muted-foreground">
            Illustrative TNT-equivalent yield -- an input assumption you choose, not a measured/real quantity.
          </p>

          <button
            type="button"
            disabled={!epicenterPx || state.status === "loading"}
            onClick={handleRun}
            className="w-full rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {state.status === "loading" ? "Simulating..." : "Run Impact Simulation"}
          </button>
          {!epicenterPx && (
            <p className="text-xs text-muted-foreground">Pick an epicenter on the 3D terrain first.</p>
          )}

          {state.status === "error" && (
            <p className="rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
              {state.message}
            </p>
          )}

          {ready?.status === "unavailable" && (
            <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-sm text-muted-foreground">
              {ready.note ?? "This job cannot run the explosion-impact scenario."}
            </p>
          )}

          {ready?.status === "simulated" && (
            <div className="space-y-3 rounded-lg border border-border bg-muted/20 p-4">
              {ready.spacingUnits === "pixels" && (
                <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  This job isn&apos;t georeferenced, so the rings below are an illustrative visualization only (not
                  calibrated to a real-world distance).
                </p>
              )}
              <div className="space-y-2">
                {ready.bands.map((band) => (
                  <div key={band.severity} className="flex items-center justify-between rounded-lg border border-border px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span
                        className="h-2.5 w-2.5 rounded-full"
                        style={{ backgroundColor: BAND_COLOR[band.severity] ?? "#94a3b8" }}
                      />
                      <span className="text-sm font-medium capitalize text-foreground">{band.severity}</span>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <p className="text-sm font-semibold text-foreground">{band.radiusM.toFixed(1)} m</p>
                      <p>{band.buildingIds.length} building{band.buildingIds.length === 1 ? "" : "s"} affected</p>
                    </div>
                  </div>
                ))}
              </div>
              {ready.note && (
                <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                  {ready.note}
                </p>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
