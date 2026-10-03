"use client";

import { useEffect, useRef, useState } from "react";

import { runFloodScenario, type FloodScenarioResult } from "@/lib/api/pipeline";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";

interface FloodPanelProps {
  jobId: string;
  isMetric: boolean;
  originalImageUrl: string | null;
  /** Lifted to the parent scenarios page so the same value can drive the
   * live 3D water-plane overlay in TerrainViewer, not just this panel's own
   * stats request. */
  waterLevel: number;
  onWaterLevelChange: (level: number) => void;
}

type FetchState =
  | { status: "idle" }
  | { status: "loading"; stale: FloodScenarioResult | null }
  | { status: "ready"; result: FloodScenarioResult }
  | { status: "error"; message: string; stale: FloodScenarioResult | null };

const MAX_LEVEL = 20; // meters, or relative units when not metric -- see label below

export function FloodPanel({ jobId, isMetric, originalImageUrl, waterLevel, onWaterLevelChange }: FloodPanelProps) {
  const debouncedLevel = useDebouncedValue(waterLevel, 400);
  const [state, setState] = useState<FetchState>({ status: "idle" });
  const requestIdRef = useRef(0);

  // Transition to "loading" synchronously during render (React's documented pattern for resetting
  // state when a derived key changes -- a second useState tracking the previous key, not a ref, since
  // this project's stricter lint config forbids reading/writing refs during render) rather than via a
  // direct setState call at the top of the effect body, which the project's lint config also flags
  // (react-hooks/set-state-in-effect).
  const requestKey = `${jobId}:${debouncedLevel}`;
  const [lastKey, setLastKey] = useState<string | null>(null);
  if (lastKey !== requestKey) {
    setLastKey(requestKey);
    const stale = state.status === "ready" ? state.result : state.status === "error" || state.status === "loading" ? state.stale : null;
    setState({ status: "loading", stale });
  }

  useEffect(() => {
    const requestId = ++requestIdRef.current;

    runFloodScenario(jobId, debouncedLevel)
      .then((result) => {
        if (requestIdRef.current !== requestId) return;
        setState({ status: "ready", result });
      })
      .catch((err) => {
        if (requestIdRef.current !== requestId) return;
        setState((prev) => ({
          status: "error",
          message: err instanceof Error ? err.message : "Flood scenario endpoint is not reachable.",
          stale: prev.status === "loading" ? prev.stale : null,
        }));
      });
  }, [jobId, debouncedLevel]);

  const unitLabel = isMetric ? "meters" : "relative units";
  const displayResult =
    state.status === "ready" ? state.result : state.status === "loading" || state.status === "error" ? state.stale : null;
  const isBusy = state.status === "loading";

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">Flood &mdash; Bathtub Model</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Simulates uniform water rise from the job&apos;s DSM. {isMetric ? "This job is metrically calibrated, so the water level is in real meters." : "This job has no metric calibration, so the water level is in the DSM's own relative units, not real meters."}
        </p>
      </div>

      <div className="glass-panel rounded-2xl p-5">
        <div className="mb-4 flex items-center justify-between">
          <label htmlFor="water-level" className="text-sm font-medium text-foreground">
            Water level: {waterLevel.toFixed(1)} {unitLabel}
          </label>
          {isBusy && (
            <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
              Simulating...
            </span>
          )}
        </div>
        <input
          id="water-level"
          type="range"
          min={0}
          max={MAX_LEVEL}
          step={0.1}
          value={waterLevel}
          onChange={(e) => onWaterLevelChange(Number(e.target.value))}
          className="w-full accent-primary"
        />
        <div className="mt-1 flex justify-between text-[11px] text-muted-foreground">
          <span>0</span>
          <span>{MAX_LEVEL}</span>
        </div>

        {state.status === "error" && (
          <p className="mt-3 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            {state.message} {state.stale && "Showing the last successful result below."}
          </p>
        )}

        <div
          className={`mt-5 grid gap-5 transition-opacity duration-200 md:grid-cols-2 ${isBusy ? "opacity-60" : "opacity-100"}`}
        >
          <div className="overflow-hidden rounded-lg border border-border bg-black/30">
            {displayResult?.previewUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={displayResult.previewUrl} alt="Flood preview overlay" className="max-h-72 w-full object-contain" />
            ) : originalImageUrl ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={originalImageUrl} alt="Original image" className="max-h-72 w-full object-contain opacity-70" />
            ) : (
              <div className="flex h-56 items-center justify-center text-sm text-muted-foreground">
                No preview available yet.
              </div>
            )}
          </div>

          <div className="space-y-3">
            {displayResult?.status === "unavailable" ? (
              <p className="text-sm text-muted-foreground">
                {displayResult.note ?? "This job cannot run the flood scenario (e.g. no DSM available)."}
              </p>
            ) : displayResult ? (
              <>
                <Stat
                  label="Submerged area"
                  value={
                    displayResult.submergedAreaM2 !== null
                      ? `${displayResult.submergedAreaM2.toFixed(1)} m²`
                      : displayResult.submergedPixelFraction !== null
                        ? `${(displayResult.submergedPixelFraction * 100).toFixed(1)}% of scene`
                        : "n/a"
                  }
                />
                {displayResult.areaNote && (
                  <p className="text-[11px] text-muted-foreground">{displayResult.areaNote}</p>
                )}
                <Stat label="Affected buildings" value={String(displayResult.affectedBuildingIds.length)} />
                {displayResult.affectedBuildingIds.length > 0 && (
                  <div>
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Affected building IDs
                    </p>
                    <div className="flex max-h-24 flex-wrap gap-1 overflow-y-auto">
                      {displayResult.affectedBuildingIds.map((id) => (
                        <span
                          key={id}
                          className="rounded-full border border-border bg-muted/40 px-2 py-0.5 font-mono text-[11px] text-muted-foreground"
                        >
                          {id}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
                {displayResult.note && (
                  <p className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                    {displayResult.note}
                  </p>
                )}
              </>
            ) : (
              <p className="text-sm text-muted-foreground">Move the slider to run the simulation.</p>
            )}
          </div>
        </div>
      </div>
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
