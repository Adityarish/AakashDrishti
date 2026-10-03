"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, ArrowRight, Check, Circle, Loader2, Minus, Play, RotateCcw, Square, X } from "lucide-react";

import { PageShell } from "@/components/layout/PageShell";
import { Badge, Button, ErrorNote, PageHeader, ProgressBar, Reveal, Spinner, useCountUp } from "@/components/ui";
import { cancelPipeline, runPipeline } from "@/lib/api/survey";
import { fmtDuration } from "@/lib/format";
import { useJobLive } from "@/lib/hooks";
import type { LogLine, Step } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

function StepIcon({ step }: { step: Step }) {
  if (step.status === "done") return <Check className="h-4 w-4 text-white" strokeWidth={3} />;
  if (step.status === "running") return <Loader2 className="h-4 w-4 animate-spin text-white" strokeWidth={2.5} />;
  if (step.status === "failed") return <X className="h-4 w-4 text-white" strokeWidth={3} />;
  if (step.status === "skipped") return <Minus className="h-4 w-4 text-slate-ice" strokeWidth={2.5} />;
  return <Circle className="h-2.5 w-2.5 text-glacier-300" fill="currentColor" strokeWidth={0} />;
}

function stepElapsed(step: Step, now: number): string | null {
  if (!step.started_at) return null;
  const end = step.ended_at ?? now / 1000;
  return fmtDuration(Math.max(0, end - step.started_at));
}

function LogView({ logs }: { logs: LogLine[] }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [logs.length]);
  const origin = logs[0]?.t ?? 0;
  return (
    <div className="terminal h-[26rem] overflow-auto p-4" role="log" aria-live="polite" aria-label="Pipeline log">
      {logs.length === 0 && <p className="text-[#6f8cab]">Waiting for the first log line…</p>}
      {logs.map((line, index) => (
        <div key={index} className="flex gap-3">
          <span className="w-12 shrink-0 text-right text-[#5d7898]">+{(line.t - origin).toFixed(1)}s</span>
          <span className={cn("w-[5.5rem] shrink-0 uppercase tracking-wider", line.level === "error" ? "text-[#ff8b80]" : line.level === "warn" ? "text-[#ffc078]" : "text-[#6fb6e6]")}>
            {line.step ?? "job"}
          </span>
          <span className={cn("min-w-0 break-words", line.level === "error" ? "text-[#ffb3ab]" : line.level === "warn" ? "text-[#ffd8a8]" : "text-[#d3e6f5]")}>{line.msg}</span>
        </div>
      ))}
      <div ref={end} />
    </div>
  );
}

export default function ProgressPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { job, logs, error, refresh, setJob } = useJobLive(id);
  const [now, setNow] = useState(() => Date.now());
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const running = job !== null && job.stage !== "READY" && job.stage !== "FAILED" && job.stage !== "UPLOADED";
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(timer);
  }, [running]);

  const progress = useCountUp(job?.progress ?? 0, 400);
  const started = useMemo(() => job?.steps.find((s) => s.started_at)?.started_at ?? null, [job]);
  const finished = job?.stage === "READY" || job?.stage === "FAILED";
  const lastEnd = useMemo(() => Math.max(0, ...(job?.steps.map((s) => s.ended_at ?? 0) ?? [0])), [job]);
  const elapsed = started ? (finished && lastEnd ? lastEnd : now / 1000) - started : 0;

  async function act(fn: () => Promise<unknown>) {
    setBusy(true);
    setActionError(null);
    try {
      await fn();
      await refresh();
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Action failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageShell wide>
      <PageHeader
        eyebrow="Expedition"
        title={job?.stage === "READY" ? "Your scene is ready" : job?.stage === "FAILED" ? "The run stopped" : "Building your terrain"}
        description={job?.source_filename ?? undefined}
        actions={
          job && (
            <>
              <Badge tone={job.mode === "absolute" ? "orange" : "ice"}>{job.mode === "absolute" ? "ABSOLUTE · metres" : "RELATIVE"}</Badge>
              {job.is_sample && <Badge tone="muted">Sample scene</Badge>}
              {job.attempts > 1 && <Badge tone="krill">Retry {job.attempts}</Badge>}
            </>
          )
        }
      />

      {(error || actionError) && <ErrorNote className="mt-6" message={error ?? actionError ?? ""} />}

      {!job && !error && (
        <div className="mt-10 flex items-center gap-3 text-slate-ice">
          <Spinner /> Loading job…
        </div>
      )}

      {job && (
        <div className="mt-8 space-y-6">
          <Reveal>
            <div className="card p-5">
              <div className="flex flex-wrap items-end justify-between gap-4">
                <div>
                  <p className="eyebrow">Overall progress</p>
                  <p className="mono mt-1 text-4xl font-semibold text-polar-night">
                    {Math.round(progress)}
                    <span className="text-xl text-slate-ice">%</span>
                  </p>
                </div>
                <div className="flex items-center gap-6">
                  <div className="text-right">
                    <p className="eyebrow !text-slate-ice">Elapsed</p>
                    <p className="mono text-lg font-semibold text-polar-night">{started ? fmtDuration(elapsed) : "-"}</p>
                  </div>
                  <div className="flex gap-2">
                    {running && (
                      <Button variant="danger" loading={busy} onClick={() => act(() => cancelPipeline(id))}>
                        <Square className="h-4 w-4" strokeWidth={1.75} /> Cancel
                      </Button>
                    )}
                    {job.stage === "FAILED" && (
                      <Button loading={busy} onClick={() => act(() => runPipeline(id).then(setJob))}>
                        <RotateCcw className="h-4 w-4" strokeWidth={1.75} /> Retry
                      </Button>
                    )}
                    {job.stage === "UPLOADED" && (
                      <Button loading={busy} onClick={() => act(() => runPipeline(id).then(setJob))}>
                        <Play className="h-4 w-4" strokeWidth={1.75} /> Start run
                      </Button>
                    )}
                  </div>
                </div>
              </div>
              <ProgressBar value={progress} className="mt-4 !h-2.5" tone={job.stage === "READY" ? "aurora" : "orange"} />
            </div>
          </Reveal>

          {job.stage === "FAILED" && (
            <div className="card border-krill/40 p-5">
              <div className="flex gap-3">
                <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-krill" strokeWidth={1.75} />
                <div>
                  <p className="font-semibold text-krill">{job.cancel_requested ? "Cancelled" : "This run failed"}</p>
                  <p className="mt-1 text-sm leading-relaxed text-polar-night">{job.error ?? "Unknown error."}</p>
                  {/memory|paging/i.test(job.error ?? "") && (
                    <p className="mt-2 text-xs leading-relaxed text-slate-ice">
                      Tip: this machine is low on memory. Close other applications, or lower the tile size and disable the Depth Pro ensemble in the options.
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          <div className="grid gap-6 lg:grid-cols-[minmax(0,26rem)_1fr]">
            <Reveal delay={0.05}>
              <ol className="card divide-y divide-glacier-300/40 p-2">
                {job.steps.map((step) => (
                  <li key={step.key} className="flex gap-3 px-3 py-3">
                    <span
                      className={cn(
                        "mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full transition-colors",
                        step.status === "done" && "bg-aurora",
                        step.status === "running" && "bg-station-orange",
                        step.status === "failed" && "bg-krill",
                        step.status === "skipped" && "bg-glacier-100",
                        step.status === "pending" && "bg-glacier-100",
                      )}
                    >
                      <StepIcon step={step} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-baseline justify-between gap-3">
                        <p className={cn("text-sm font-semibold", step.status === "pending" ? "text-slate-ice" : "text-polar-night")}>{step.label}</p>
                        <span className="mono shrink-0 text-xs text-slate-ice">
                          {step.status === "running" ? `${Math.round(step.progress)}%` : step.status === "skipped" ? "skipped" : (stepElapsed(step, now) ?? "")}
                        </span>
                      </div>
                      {step.status === "running" && <ProgressBar value={step.progress} className="mt-2 !h-1.5" />}
                      {step.detail && step.status !== "pending" && <p className="mt-1 text-xs leading-snug text-slate-ice">{step.detail}</p>}
                    </div>
                  </li>
                ))}
              </ol>
            </Reveal>

            <Reveal delay={0.1}>
              <div>
                <div className="mb-2 flex items-center justify-between">
                  <p className="eyebrow">Live pipeline log</p>
                  <span className="text-[0.7rem] font-semibold text-slate-ice">Real events from the running job</span>
                </div>
                <LogView logs={logs} />
              </div>
            </Reveal>
          </div>

          {job.stage === "READY" && (
            <Reveal>
              <div className="frost flex flex-col gap-4 rounded-lg p-6 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-lg font-semibold text-polar-night">Done in {fmtDuration(elapsed)}.</p>
                  <p className="mt-1 text-sm text-slate-ice">
                    {job.summary.buildings ?? 0} buildings detected · {job.summary.width}×{job.summary.height} px · open the scene to inspect and analyse it.
                  </p>
                </div>
                <div className="flex flex-wrap gap-3">
                  <Link href={`/survey/${id}`} className="btn btn-ghost">
                    2D workspace
                  </Link>
                  <button className="btn btn-primary btn-lg" onClick={() => router.push(`/survey/${id}/hazards`)}>
                    Run hazard analysis <ArrowRight className="h-5 w-5" strokeWidth={1.75} />
                  </button>
                </div>
              </div>
            </Reveal>
          )}
        </div>
      )}
    </PageShell>
  );
}
