"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { AppHeader } from "@/components/common/AppHeader";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { JobStatusBadge, GeoreferencedBadge } from "@/components/history/JobStatusBadge";
import { deleteJob, listJobs, type JobSummary } from "@/lib/api/pipeline";
import { ApiError } from "@/lib/api/client";
import { formatRelativeTime } from "@/lib/time";

type ListState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; jobs: JobSummary[] };

export default function HistoryPage() {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    listJobs()
      .then((jobs) => {
        if (!cancelled) setState({ status: "ready", jobs });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof ApiError ? err.message : "Unexpected error while loading job history.";
        setState({ status: "error", message });
      });

    return () => {
      cancelled = true;
    };
  }, []);

  async function handleDelete(job: JobSummary) {
    if (!window.confirm(`Delete "${job.sourceFilename}" and all its results? This cannot be undone.`)) return;
    setDeletingId(job.jobId);
    setDeleteError(null);
    try {
      await deleteJob(job.jobId);
      setState((prev) =>
        prev.status === "ready" ? { status: "ready", jobs: prev.jobs.filter((j) => j.jobId !== job.jobId) } : prev,
      );
    } catch (err: unknown) {
      setDeleteError(err instanceof ApiError ? err.message : "Could not delete this job.");
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-10 xl:px-10">
        {deleteError && (
          <div className="mb-6">
            <ErrorBanner message={deleteError} />
          </div>
        )}
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Job History</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Every image processed through the AakashDrishti pipeline on this backend, most recent first.
            </p>
          </div>
          <Link
            href="/dashboard"
            className="inline-flex rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
          >
            Process New Image
          </Link>
        </div>

        {state.status === "loading" && <HistorySkeleton />}

        {state.status === "error" && (
          <div className="space-y-4">
            <ErrorBanner message={`Could not load job history: ${state.message}`} />
            <p className="text-sm text-muted-foreground">
              Check that the AakashDrishti backend is running and reachable, then reload this page. (If
              `GET /api/pipeline` hasn&apos;t been deployed on the backend yet, this is expected.)
            </p>
          </div>
        )}

        {state.status === "ready" && state.jobs.length === 0 && <EmptyState />}

        {state.status === "ready" && state.jobs.length > 0 && (
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {state.jobs.map((job) => (
              <JobCard key={job.jobId} job={job} onDelete={handleDelete} deleting={deletingId === job.jobId} />
            ))}
          </div>
        )}
      </main>
    </div>
  );
}

function JobCard({
  job,
  onDelete,
  deleting,
}: {
  job: JobSummary;
  onDelete: (job: JobSummary) => void;
  deleting: boolean;
}) {
  const inProgress = !["UPLOADED", "READY", "FAILED"].includes(job.stage);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => onDelete(job)}
        disabled={deleting || inProgress}
        title={inProgress ? "Still processing -- cancel it before deleting" : "Delete this job"}
        aria-label={`Delete ${job.sourceFilename}`}
        className="absolute right-2 top-2 z-10 flex h-8 w-8 items-center justify-center rounded-lg border border-white/60 bg-white/80 text-red-600 shadow-sm backdrop-blur transition hover:bg-red-600 hover:text-white disabled:cursor-not-allowed disabled:opacity-40"
      >
        <svg viewBox="0 0 24 24" fill="none" className="h-4 w-4" stroke="currentColor" strokeWidth={1.75}>
          <path
            d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 002 2h6a2 2 0 002-2l1-12M9 7V4h6v3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>
      <JobCardLink job={job} deleting={deleting} />
    </div>
  );
}

function JobCardLink({ job, deleting }: { job: JobSummary; deleting: boolean }) {
  return (
    <Link
      href={`/history/${job.jobId}`}
      className={`group glass-panel flex flex-col overflow-hidden rounded-2xl transition-all duration-200 hover:-translate-y-1 hover:ring-1 hover:ring-primary/50 hover:shadow-[0_16px_32px_-16px_color-mix(in_srgb,var(--primary)_45%,transparent)] ${deleting ? "pointer-events-none opacity-50" : ""}`}
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
    </Link>
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

function HistorySkeleton() {
  return (
    <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
      {Array.from({ length: 8 }).map((_, i) => (
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

function EmptyState() {
  return (
    <div className="glass-panel flex flex-col items-center justify-center gap-4 rounded-2xl px-6 py-20 text-center">
      <div className="flex h-14 w-14 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-primary">
        <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7" stroke="currentColor" strokeWidth={1.5}>
          <path d="M12 8v5l3 2" strokeLinecap="round" strokeLinejoin="round" />
          <circle cx="12" cy="12" r="9" />
        </svg>
      </div>
      <div>
        <p className="text-lg font-semibold text-foreground">No jobs yet</p>
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">
          Process your first single-view image to see it appear here with its depth, DSM, and 3D terrain
          results.
        </p>
      </div>
      <Link
        href="/dashboard"
        className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
      >
        Process an Image
      </Link>
    </div>
  );
}
