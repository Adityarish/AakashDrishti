"use client";

import { useEffect, useState } from "react";

import { JobStatusBadge, GeoreferencedBadge } from "@/components/history/JobStatusBadge";
import { listJobs, type JobSummary } from "@/lib/api/pipeline";
import { formatRelativeTime } from "@/lib/time";

interface JobPickerProps {
  selectedJobId: string | null;
  onSelect: (jobId: string) => void;
}

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; jobs: JobSummary[] };

/**
 * Job picker for the Scenarios page -- same card-grid presentation as
 * history/page.tsx's JobCard (thumbnail, status badge, filename, building
 * count), but a click selects the job in-place instead of navigating.
 */
export function JobPicker({ selectedJobId, onSelect }: JobPickerProps) {
  const [state, setState] = useState<ListState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    listJobs()
      .then((jobs) => !cancelled && setState({ status: "ready", jobs }))
      .catch((err: unknown) => {
        if (cancelled) return;
        setState({
          status: "error",
          message: err instanceof Error ? err.message : "Could not load job history.",
        });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <p className="mb-1 text-sm font-medium text-foreground">Select a Processed Job</p>
      <p className="mb-4 text-xs text-muted-foreground">
        Scenarios run against an existing job&apos;s DSM and detected buildings -- process an image on the{" "}
        <a href="/dashboard" className="text-primary underline underline-offset-2">
          Dashboard
        </a>{" "}
        first if you don&apos;t have one yet.
      </p>

      {state.status === "loading" && <JobPickerSkeleton />}

      {state.status === "error" && (
        <p className="glass-panel rounded-2xl px-5 py-4 text-sm text-destructive">
          Could not load job history: {state.message}
        </p>
      )}

      {state.status === "ready" && state.jobs.length === 0 && (
        <p className="glass-panel rounded-2xl px-5 py-8 text-center text-sm text-muted-foreground">
          No processed jobs found yet.
        </p>
      )}

      {state.status === "ready" && state.jobs.length > 0 && (
        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {state.jobs.map((job) => (
            <JobCard
              key={job.jobId}
              job={job}
              selected={job.jobId === selectedJobId}
              onClick={() => onSelect(job.jobId)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function JobCard({ job, selected, onClick }: { job: JobSummary; selected: boolean; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group glass-panel flex flex-col overflow-hidden rounded-2xl text-left transition-all duration-200 hover:-translate-y-1 hover:ring-1 hover:ring-primary/50 hover:shadow-[0_16px_32px_-16px_color-mix(in_srgb,var(--primary)_45%,transparent)] ${
        selected ? "ring-2 ring-primary" : ""
      }`}
    >
      <div className="relative flex aspect-video items-center justify-center overflow-hidden bg-muted/40">
        {job.thumbnailUrl ? (
          // eslint-disable-next-line @next/next/no-img-element -- backend-served preview, dimensions vary per job
          <img
            src={job.thumbnailUrl}
            alt={job.sourceFilename}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        ) : (
          <PlaceholderThumb />
        )}
        <div className="absolute left-2 top-2">
          <JobStatusBadge stage={job.stage} />
        </div>
      </div>

      <div className="flex flex-1 flex-col gap-2 px-4 py-3.5">
        <p className="truncate text-sm font-medium text-foreground" title={job.sourceFilename}>
          {job.sourceFilename}
        </p>
        <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>{formatRelativeTime(job.updatedAt)}</span>
          <GeoreferencedBadge isGeoreferenced={job.isGeoreferenced} />
        </div>
        {job.buildingCount !== null && (
          <p className="text-xs text-muted-foreground">
            {job.buildingCount} building{job.buildingCount === 1 ? "" : "s"} detected
          </p>
        )}
      </div>
    </button>
  );
}

function PlaceholderThumb() {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      className="h-10 w-10 text-muted-foreground/50"
      stroke="currentColor"
      strokeWidth={1.5}
    >
      <rect x="3" y="4" width="18" height="16" rx="1.5" />
      <circle cx="8.5" cy="9.5" r="1.5" />
      <path d="M21 16l-5.5-5.5a1.5 1.5 0 00-2.12 0L4 19" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function JobPickerSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <div key={i} className="glass-panel animate-pulse overflow-hidden rounded-2xl">
          <div className="aspect-video bg-muted/40" />
          <div className="space-y-2 px-4 py-3.5">
            <div className="h-3.5 w-3/4 rounded bg-muted/50" />
            <div className="h-3 w-1/2 rounded bg-muted/40" />
          </div>
        </div>
      ))}
    </div>
  );
}
