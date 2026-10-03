import type { ValidationResult } from "@/lib/types/results";
import { ResultPanel } from "./ResultPanel";

export type FetchState<T> = { status: "loading" | "unavailable" | "ready"; data: T | null };

/**
 * Reference validation (RMSE/MAE/correlation) panel. Extracted from
 * ResultsScreen so the history detail view can reuse the exact same
 * FR-11 display pattern instead of re-implementing it.
 */
export function ValidationPanel({ state }: { state: FetchState<ValidationResult> }) {
  if (state.status === "loading") {
    return (
      <ResultPanel title="Reference Validation (RMSE / MAE / Correlation)" available={false} unavailableNote="Checking for reference data...">
      </ResultPanel>
    );
  }

  const validation = state.data;
  const available = state.status === "ready" && Boolean(validation?.available);

  return (
    <ResultPanel
      title="Reference Validation (RMSE / MAE / Correlation)"
      available={available}
      unavailableNote={
        state.status === "unavailable"
          ? "Validation endpoint is not reachable yet for this job (backend may still be deploying FR-11)."
          : "No reference DEM/LiDAR data is available for this job, so no accuracy metrics can be computed."
      }
    >
      {available && validation && (
        <dl className="grid w-full grid-cols-2 gap-x-6 gap-y-3 text-sm sm:grid-cols-4">
          <StatCell label="RMSE" value={validation.rmse !== null ? `${validation.rmse.toFixed(2)} m` : "-"} />
          <StatCell label="MAE" value={validation.mae !== null ? `${validation.mae.toFixed(2)} m` : "-"} />
          <StatCell
            label="Correlation"
            value={validation.correlation !== null ? validation.correlation.toFixed(3) : "-"}
          />
          <StatCell
            label="Valid Pixels"
            value={validation.validPixelCount !== null ? validation.validPixelCount.toLocaleString() : "-"}
          />
        </dl>
      )}
    </ResultPanel>
  );
}

export function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="text-center">
      <p className="text-lg font-semibold text-primary">{value}</p>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
    </div>
  );
}
