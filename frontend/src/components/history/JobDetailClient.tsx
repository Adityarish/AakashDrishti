"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import { ErrorBanner } from "@/components/common/ErrorBanner";
import { ResultPanel } from "@/components/results/ResultPanel";
import { OriginalImagePreview } from "@/components/results/OriginalImagePreview";
import { ValidationPanel, type FetchState } from "@/components/results/ValidationPanel";
import { BuildingHeightsPanel } from "@/components/results/BuildingHeightsPanel";
import { ViewerSwitcher } from "@/components/viewer/ViewerSwitcher";
import { JobStatusBadge, GeoreferencedBadge } from "@/components/history/JobStatusBadge";
import { getJobStatus, getBuildings, getValidation, getResultMetadata, outputUrl } from "@/lib/api/pipeline";
import { buildResultFromOutputs } from "@/hooks/useDepthWizardWorkflow";
import { ApiError } from "@/lib/api/client";
import { STAGE_LABEL } from "@/lib/types/processing";
import type { ProcessingStatus } from "@/lib/types/processing";
import type { Building, ProcessingResult, ValidationResult } from "@/lib/types/results";

const POLL_INTERVAL_MS = 3000;

type LoadState =
  | { phase: "loading" }
  | { phase: "not-found"; message: string }
  | { phase: "in-progress"; job: ProcessingStatus }
  | { phase: "failed"; job: ProcessingStatus }
  | { phase: "ready"; job: ProcessingStatus; result: ProcessingResult };

function filenameFromOutputs(outputs: Record<string, string>): string {
  const original = outputs.original;
  if (!original) return "Untitled image";
  const parts = original.split("/");
  return parts[parts.length - 1] || "Untitled image";
}

export function JobDetailClient({ jobId }: { jobId: string }) {
  const [state, setState] = useState<LoadState>({ phase: "loading" });
  const [buildings, setBuildings] = useState<FetchState<Building[]>>({ status: "loading", data: null });
  const [validation, setValidation] = useState<FetchState<ValidationResult>>({ status: "loading", data: null });
  const pollTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function settle(job: ProcessingStatus) {
      if (cancelled) return;
      if (job.stage === "READY") {
        // ProcessingStatus (from GET /api/pipeline/{job_id}) doesn't carry
        // is_georeferenced -- read it from metadata.json instead, the same
        // real artifact buildResultFromOutputs itself reads.
        let isGeoreferenced = false;
        if (job.outputs.metadata_json) {
          try {
            const meta = await getResultMetadata(job.outputs.metadata_json);
            isGeoreferenced = meta.is_georeferenced;
          } catch {
            // Leave isGeoreferenced false rather than guessing.
          }
        }
        const result = await buildResultFromOutputs(
          jobId,
          job.outputs,
          job.outputs.original ? outputUrl(job.outputs.original) : "",
          isGeoreferenced,
        );
        if (!cancelled) setState({ phase: "ready", job, result });
      } else if (job.stage === "FAILED") {
        if (!cancelled) setState({ phase: "failed", job });
      } else {
        if (!cancelled) setState({ phase: "in-progress", job });
      }
    }

    async function poll() {
      try {
        const job = await getJobStatus(jobId);
        await settle(job);
        if (job.stage !== "READY" && job.stage !== "FAILED" && !pollTimer.current) {
          pollTimer.current = setInterval(async () => {
            try {
              const polled = await getJobStatus(jobId);
              await settle(polled);
              if (polled.stage === "READY" || polled.stage === "FAILED") {
                if (pollTimer.current) {
                  clearInterval(pollTimer.current);
                  pollTimer.current = null;
                }
              }
            } catch {
              if (pollTimer.current) {
                clearInterval(pollTimer.current);
                pollTimer.current = null;
              }
            }
          }, POLL_INTERVAL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof ApiError ? err.message : "Unexpected error while loading this job.";
        setState({ phase: "not-found", message });
      }
    }

    poll();

    return () => {
      cancelled = true;
      if (pollTimer.current) {
        clearInterval(pollTimer.current);
        pollTimer.current = null;
      }
    };
  }, [jobId]);

  useEffect(() => {
    if (state.phase !== "ready") return;
    let cancelled = false;

    getBuildings(jobId)
      .then((data) => !cancelled && setBuildings({ status: "ready", data }))
      .catch(() => !cancelled && setBuildings({ status: "unavailable", data: null }));

    getValidation(jobId)
      .then((data) => !cancelled && setValidation({ status: "ready", data }))
      .catch(() => !cancelled && setValidation({ status: "unavailable", data: null }));

    return () => {
      cancelled = true;
    };
  }, [state.phase, jobId]);

  if (state.phase === "loading") {
    return <DetailSkeleton />;
  }

  if (state.phase === "not-found") {
    return (
      <div className="space-y-4">
        <ErrorBanner message={`Could not load job ${jobId}: ${state.message}`} />
        <Link href="/history" className="text-sm font-medium text-primary hover:underline">
          Back to Job History
        </Link>
      </div>
    );
  }

  const filename = filenameFromOutputs(state.job.outputs);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <Link href="/history" className="text-xs font-medium text-muted-foreground hover:text-primary">
            &larr; Back to Job History
          </Link>
          <h1 className="mt-1 text-xl font-semibold text-foreground">{filename}</h1>
          <p className="mt-0.5 font-mono text-xs text-muted-foreground">Job {jobId}</p>
        </div>
        <div className="flex items-center gap-2">
          {state.phase === "ready" && (
            <Link href={`/survey/${jobId}`} className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90">
              Open Full Survey
            </Link>
          )}
          {state.phase === "ready" && <GeoreferencedBadge isGeoreferenced={state.result.isGeoreferenced} />}
          <JobStatusBadge stage={state.job.stage} />
        </div>
      </div>

      {state.phase === "in-progress" && (
        <div className="glass-panel rounded-2xl px-6 py-10 text-center">
          <p className="text-sm font-medium text-foreground">
            {STAGE_LABEL[state.job.stage] ?? state.job.stage}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            This job is still running on the backend ({state.job.progress}%). This page refreshes
            automatically -- results, buildings, and validation will appear here once it reaches Ready.
          </p>
          <div className="mx-auto mt-4 h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-muted/50">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${Math.max(4, state.job.progress)}%` }}
            />
          </div>
        </div>
      )}

      {state.phase === "failed" && (
        <ErrorBanner message={state.job.error ?? "This job failed on the backend, and no error detail was recorded."} />
      )}

      {state.phase === "ready" && (
        <>
          <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
            <div className="glass-panel overflow-hidden rounded-2xl">
              <div className="flex items-center justify-between border-b border-border px-5 py-3">
                <p className="text-sm font-medium text-foreground">Original Image</p>
              </div>
              <div className="flex h-64 items-center justify-center bg-black/30 p-3">
                {state.result.originalImageUrl ? (
                  <OriginalImagePreview src={state.result.originalImageUrl} />
                ) : (
                  <p className="max-w-xs text-center text-sm text-muted-foreground">
                    The original image is not available for this job.
                  </p>
                )}
              </div>
            </div>

            <ResultPanel
              title="Fused Depth Map"
              available={state.result.depth.available}
              unavailableNote="Depth Anything V2 + Depth Pro fusion has not been run for this job yet."
            >
              {state.result.depth.previewUrl && (
                <div className="flex h-full w-full flex-col gap-2">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={state.result.depth.previewUrl}
                    alt="Fused depth map"
                    className="max-h-52 w-full object-contain"
                  />
                </div>
              )}
            </ResultPanel>

            <ResultPanel
              title={state.result.dsm.isMetric ? "DSM (metric)" : "rDSM (relative)"}
              available={state.result.dsm.available}
              unavailableNote="DSM/rDSM generation has not been implemented on the backend yet."
            >
              {state.result.dsm.previewUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={state.result.dsm.previewUrl} alt="DSM / rDSM elevation map" className="max-h-full max-w-full object-contain" />
              )}
            </ResultPanel>

            <ResultPanel
              title="Confidence / Uncertainty"
              available={state.result.confidence.available}
              unavailableNote="Confidence mapping has not been implemented on the backend yet."
            >
              {state.result.confidence.previewUrl && (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={state.result.confidence.previewUrl} alt="Depth confidence map" className="max-h-full max-w-full object-contain" />
              )}
            </ResultPanel>
          </div>

          <ViewerSwitcher
            terrain={state.result.terrain}
            jobId={jobId}
            confidencePreviewUrl={state.result.confidence.previewUrl}
          />

          <ValidationPanel state={validation} />

          <BuildingHeightsPanel state={buildings} />
        </>
      )}
    </div>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-6">
      <div className="h-6 w-64 animate-pulse rounded bg-muted/50" />
      <div className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="glass-panel h-64 animate-pulse rounded-2xl bg-muted/30" />
        ))}
      </div>
    </div>
  );
}
