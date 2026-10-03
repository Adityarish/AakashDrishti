"use client";

import { useEffect, useMemo, useState } from "react";
import { FileImage, History } from "lucide-react";

import { Badge, Spinner } from "@/components/ui";
import { fmtDate } from "@/lib/format";
import { listJobs, outputUrl } from "@/lib/api/survey";
import type { JobSummary } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

const INITIAL = 8;

interface Entry {
  job: JobSummary;
  /** Number of earlier runs of the same file (the newest one represents the image). */
  runs: number;
}

/** Previously uploaded images, newest first, one card per file name. Picking one starts a new job from that image. */
export function HistoryPicker({ onPick, busyId, disabled }: { onPick: (job: JobSummary) => void; busyId: string | null; disabled?: boolean }) {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    listJobs()
      .then(setJobs)
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load your history."));
  }, []);

  const entries = useMemo<Entry[]>(() => {
    const byName = new Map<string, Entry>();
    for (const job of jobs ?? []) {
      const key = job.source_filename;
      const seen = byName.get(key);
      if (seen) seen.runs += 1;
      else byName.set(key, { job, runs: 1 });
    }
    return [...byName.values()];
  }, [jobs]);

  if (error) return null;
  if (jobs === null) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-ice">
        <Spinner className="h-4 w-4" /> Loading your earlier images…
      </div>
    );
  }
  if (entries.length === 0) return null;

  const visible = showAll ? entries : entries.slice(0, INITIAL);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="eyebrow flex items-center gap-2">
            <History className="h-3.5 w-3.5" strokeWidth={1.75} /> Or pick an image from history
          </p>
          <p className="mt-1 text-sm text-slate-ice">Re-run an image you already uploaded with different options. Nothing is uploaded again and the earlier results stay as they are.</p>
        </div>
        {entries.length > INITIAL && (
          <button type="button" className="text-xs font-semibold text-deep-ice hover:underline" onClick={() => setShowAll((v) => !v)}>
            {showAll ? "Show fewer" : `Show all ${entries.length}`}
          </button>
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {visible.map(({ job, runs }) => {
          const busy = busyId === job.job_id;
          return (
            <button
              key={job.job_id}
              type="button"
              disabled={disabled || busyId !== null}
              onClick={() => onPick(job)}
              className={cn(
                "card card-lift group overflow-hidden text-left disabled:cursor-not-allowed disabled:opacity-60",
                busy && "border-station-orange",
              )}
            >
              <div className="relative flex aspect-[16/10] items-center justify-center bg-glacier-100">
                {job.thumbnail_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={outputUrl(job.thumbnail_url)} alt={job.source_filename} loading="lazy" className="h-full w-full object-cover" />
                ) : (
                  <FileImage className="h-8 w-8 text-slate-ice" strokeWidth={1.2} />
                )}
                {busy && (
                  <span className="absolute inset-0 flex items-center justify-center bg-white/70">
                    <Spinner />
                  </span>
                )}
                {runs > 1 && <Badge tone="muted" className="absolute right-2 top-2 !bg-white/90">{runs} runs</Badge>}
              </div>
              <div className="p-3">
                <p className="truncate text-sm font-semibold text-polar-night" title={job.source_filename}>
                  {job.source_filename}
                </p>
                <p className="mt-0.5 text-xs text-slate-ice">{fmtDate(job.updated_at)}</p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
