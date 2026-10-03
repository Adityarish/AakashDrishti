import type { Building } from "@/lib/types/results";
import { ResultPanel } from "./ResultPanel";
import type { FetchState } from "./ValidationPanel";

/**
 * Detected-building heights table. Extracted from ResultsScreen so the
 * history detail view can reuse the exact same table pattern instead of
 * re-implementing it.
 */
export function BuildingHeightsPanel({ state }: { state: FetchState<Building[]> }) {
  if (state.status === "loading") {
    return (
      <ResultPanel title="Building Heights" available={false} unavailableNote="Checking for detected buildings..." />
    );
  }

  const buildings = state.data ?? [];
  const available = state.status === "ready" && buildings.length > 0;

  return (
    <ResultPanel
      title="Building Heights"
      available={available}
      unavailableNote={
        state.status === "unavailable"
          ? "Building detection endpoint is not reachable yet for this job (backend may still be deploying this feature)."
          : "No buildings were detected for this job."
      }
    >
      {available && (
        <div className="w-full overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2">ID</th>
                <th className="px-3 py-2">Height</th>
                <th className="px-3 py-2">Confidence</th>
                <th className="px-3 py-2">Shadow Cross-Check</th>
              </tr>
            </thead>
            <tbody>
              {buildings.map((b) => (
                <tr key={b.id} className="border-b border-border/50 text-muted-foreground">
                  <td className="px-3 py-2 font-mono text-xs text-muted-foreground">{b.id}</td>
                  <td className="px-3 py-2 font-medium text-foreground">
                    {b.heightM.toFixed(1)} m {!b.isMetric && <span className="text-muted-foreground">(relative)</span>}
                  </td>
                  <td className="px-3 py-2">{(b.confidence * 100).toFixed(0)}%</td>
                  <td className="px-3 py-2">
                    {b.shadowEstimateM !== null ? (
                      <span>
                        {b.shadowEstimateM.toFixed(1)} m
                        {b.depthVsShadowDeltaM !== null && (
                          <span className="ml-1 text-muted-foreground">
                            (&Delta;{b.depthVsShadowDeltaM >= 0 ? "+" : ""}
                            {b.depthVsShadowDeltaM.toFixed(1)} m)
                          </span>
                        )}
                      </span>
                    ) : (
                      <span className="text-muted-foreground">n/a</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </ResultPanel>
  );
}
