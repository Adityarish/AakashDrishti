"use client";

import { useEffect, useState } from "react";

import type { UploadResult } from "@/lib/types/upload";
import type { Building, ProcessingResult, ValidationResult } from "@/lib/types/results";
import { getBuildings, getValidation } from "@/lib/api/pipeline";
import { findKnownHeights } from "@/lib/data/knownHeights";
import { OriginalImagePreview } from "./OriginalImagePreview";
import { ResultPanel } from "./ResultPanel";
import { ValidationPanel, type FetchState } from "./ValidationPanel";
import { BuildingHeightsPanel } from "./BuildingHeightsPanel";
import { ViewerSwitcher } from "@/components/viewer/ViewerSwitcher";

interface ResultsScreenProps {
  result: ProcessingResult;
  uploadResult: UploadResult | null;
  onStartOver: () => void;
}

export function ResultsScreen({ result, uploadResult, onStartOver }: ResultsScreenProps) {
  const [buildings, setBuildings] = useState<FetchState<Building[]>>({ status: "loading", data: null });
  const [validation, setValidation] = useState<FetchState<ValidationResult>>({ status: "loading", data: null });

  useEffect(() => {
    let cancelled = false;

    getBuildings(result.jobId)
      .then((data) => !cancelled && setBuildings({ status: "ready", data }))
      .catch(() => !cancelled && setBuildings({ status: "unavailable", data: null }));

    getValidation(result.jobId)
      .then((data) => !cancelled && setValidation({ status: "ready", data }))
      .catch(() => !cancelled && setValidation({ status: "unavailable", data: null }));

    return () => {
      cancelled = true;
    };
  }, [result.jobId]);

  const knownHeights = uploadResult ? findKnownHeights(uploadResult.filename) : null;
  const detectedBuildings = buildings.status === "ready" ? (buildings.data ?? []) : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-foreground">Results</h2>
          <p className="text-sm text-muted-foreground">Job {result.jobId}</p>
        </div>
        <div className="flex items-center gap-2">
        <a
          href={`/survey/${result.jobId}`}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
        >
          Open Full Survey
        </a>
        <button
          type="button"
          onClick={onStartOver}
          className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:border-primary/40 hover:text-foreground"
        >
          Process Another Image
        </button>
        </div>
      </div>

      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        <div className="glass-panel overflow-hidden rounded-2xl">
          <div className="flex items-center justify-between border-b border-border px-5 py-3">
            <p className="text-sm font-medium text-foreground">Original Image</p>
            <span className="rounded-full border border-secondary/30 bg-secondary/10 px-2.5 py-0.5 text-[11px] font-medium text-secondary">
              Real result
            </span>
          </div>
          <div className="flex h-64 items-center justify-center bg-black/30 p-3">
            <OriginalImagePreview src={result.originalImageUrl} />
          </div>
        </div>

        <ResultPanel
          title="Fused Depth Map"
          available={result.depth.available}
          unavailableNote="Depth Anything V2 + Depth Pro fusion has not been run for this job yet."
        >
          {result.depth.previewUrl && (
            <div className="flex h-full w-full flex-col gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={result.depth.previewUrl}
                alt="Fused depth map"
                className="max-h-52 w-full object-contain"
              />
              {result.depth.daV2Stats && result.depth.depthProStats && (
                <p className="text-center text-[11px] text-muted-foreground">
                  DA V2: {result.depth.daV2Stats.min.toFixed(2)}&ndash;{result.depth.daV2Stats.max.toFixed(2)} &middot;
                  {" "}Depth Pro: {result.depth.depthProStats.min.toFixed(3)}&ndash;{result.depth.depthProStats.max.toFixed(3)} m
                </p>
              )}
            </div>
          )}
        </ResultPanel>

        <ResultPanel
          title={result.dsm.isMetric ? "DSM (metric)" : "rDSM (relative)"}
          available={result.dsm.available}
          unavailableNote="DSM/rDSM generation (FR-6/FR-7) has not been implemented on the backend yet."
        >
          {result.dsm.previewUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={result.dsm.previewUrl} alt="DSM / rDSM elevation map" className="max-h-full max-w-full object-contain" />
          )}
        </ResultPanel>

        <ResultPanel
          title="Confidence / Uncertainty"
          available={result.confidence.available}
          unavailableNote="Confidence mapping (FR-5) has not been implemented on the backend yet."
        >
          {result.confidence.previewUrl && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={result.confidence.previewUrl} alt="Depth confidence map" className="max-h-full max-w-full object-contain" />
          )}
        </ResultPanel>
      </div>

      <ViewerSwitcher
        terrain={result.terrain}
        jobId={result.jobId}
        confidencePreviewUrl={result.confidence.previewUrl}
      />

      <ValidationPanel state={validation} />

      <BuildingHeightsPanel state={buildings} />

      {knownHeights && detectedBuildings.length > 0 && (
        <EstimatedVsActualCard knownHeights={knownHeights} detected={detectedBuildings} isMetric={result.dsm.isMetric} />
      )}

      {uploadResult?.geo && (
        <div className="glass-panel rounded-2xl px-5 py-4">
          <p className="mb-2 text-sm font-medium text-foreground">Geospatial Metadata (from backend)</p>
          <dl className="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-muted-foreground sm:grid-cols-4">
            <dt className="text-muted-foreground">CRS</dt>
            <dd className="col-span-3 text-muted-foreground">{uploadResult.geo.crs}</dd>
            <dt className="text-muted-foreground">Resolution</dt>
            <dd className="col-span-3 text-muted-foreground">
              {uploadResult.geo.resolution[0].toFixed(3)} x {uploadResult.geo.resolution[1].toFixed(3)}
            </dd>
            <dt className="text-muted-foreground">Bounds</dt>
            <dd className="col-span-3 text-muted-foreground">{uploadResult.geo.bounds.map((b) => b.toFixed(2)).join(", ")}</dd>
            <dt className="text-muted-foreground">NoData</dt>
            <dd className="col-span-3 text-muted-foreground">{uploadResult.geo.nodata ?? "none"}</dd>
          </dl>
        </div>
      )}
    </div>
  );
}

function EstimatedVsActualCard({
  knownHeights,
  detected,
  isMetric,
}: {
  knownHeights: NonNullable<ReturnType<typeof findKnownHeights>>;
  detected: Building[];
  isMetric: boolean;
}) {
  const rankedKnown = [...knownHeights.buildings].sort((a, b) => b.heightM - a.heightM);
  const rankedDetected = [...detected].sort((a, b) => b.heightM - a.heightM);
  const pairCount = Math.min(rankedKnown.length, rankedDetected.length);
  if (pairCount === 0) return null;

  // Detected heights are only in meters when the DSM was metrically calibrated (GeoTIFF + SRTM/GCP).
  // Without that, `heightM` is a relative depth value in arbitrary units -- comparing it against a
  // real-world meter figure (e.g. Burj Khalifa's 828m) would produce a meaningless "% error" that looks
  // like a fabricated/broken measurement rather than an honest "not calibrated" state. Never show that.
  if (!isMetric) {
    return (
      <div className="glass-panel rounded-2xl px-5 py-4">
        <div className="mb-1 flex items-center justify-between">
          <p className="text-sm font-medium text-foreground">Estimated vs. Actual &mdash; {knownHeights.location}</p>
          <span className="rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
            Not calibrated
          </span>
        </div>
        <p className="text-xs text-muted-foreground">
          This image has no georeferencing/DEM calibration, so building heights are relative (arbitrary
          units), not meters. A comparison against {knownHeights.buildings[0]?.name ?? "known"} landmark
          heights in meters would not be meaningful &mdash; upload a calibrated GeoTIFF to see this
          comparison.
        </p>
      </div>
    );
  }

  return (
    <div className="glass-panel rounded-2xl px-5 py-4">
      <div className="mb-1 flex items-center justify-between">
        <p className="text-sm font-medium text-foreground">Estimated vs. Actual &mdash; {knownHeights.location}</p>
        <span className="rounded-full border border-muted-foreground/30 bg-muted-foreground/10 px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">
          Curated demo comparison
        </span>
      </div>
      <p className="mb-3 text-xs text-muted-foreground">
        Matched by descending height rank against publicly cited landmark heights for this image. Not an
        identity match &mdash; treat as an approximate sanity check, not ground truth per-building.
      </p>
      <div className="overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2">Landmark</th>
              <th className="px-3 py-2">Known Height</th>
              <th className="px-3 py-2">Estimated</th>
              <th className="px-3 py-2">% Error</th>
            </tr>
          </thead>
          <tbody>
            {rankedKnown.slice(0, pairCount).map((known, i) => {
              const est = rankedDetected[i];
              const pctError = (Math.abs(est.heightM - known.heightM) / known.heightM) * 100;
              return (
                <tr key={known.name} className="border-b border-border/50 text-muted-foreground">
                  <td className="px-3 py-2 font-medium text-foreground">{known.name}</td>
                  <td className="px-3 py-2">
                    {known.heightM.toFixed(1)} m
                    {known.heightMAlt !== null && (
                      <span className="ml-1 text-muted-foreground">(alt {known.heightMAlt.toFixed(1)} m)</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{est.heightM.toFixed(1)} m</td>
                  <td className="px-3 py-2">{pctError.toFixed(1)}%</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
