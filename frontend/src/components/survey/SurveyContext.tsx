"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext } from "react";
import { BarChart3, Download, FileText, LifeBuoy, Map as MapIcon, Ruler } from "lucide-react";

import { Badge, Spinner } from "@/components/ui";
import { useJobLive, useScene } from "@/lib/hooks";
import type { JobStatus, SceneManifest, SceneMetadata, SceneSummary } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

interface Survey {
  id: string;
  job: JobStatus;
  metadata: SceneMetadata;
  manifest: SceneManifest;
  summary: SceneSummary;
}

const SurveyCtx = createContext<Survey | null>(null);

export function useSurvey(): Survey {
  const value = useContext(SurveyCtx);
  if (!value) throw new Error("useSurvey must be used inside a survey route");
  return value;
}

const TABS = [
  { slug: "", label: "Workspace", icon: MapIcon },
  { slug: "validate", label: "Validation lab", icon: Ruler },
  { slug: "hazards", label: "Hazards", icon: LifeBuoy },
  { slug: "brief", label: "AI brief", icon: FileText },
  { slug: "downloads", label: "Downloads", icon: Download },
];

export function kindLabel(kind: string): { text: string; tone: "orange" | "ice" | "aurora" } {
  if (kind === "absolute_dsm") return { text: "ABSOLUTE DSM · metres", tone: "orange" };
  if (kind === "pseudo_metric") return { text: "PSEUDO-METRIC · metres above ground", tone: "aurora" };
  return { text: "RELATIVE DSM · no units", tone: "ice" };
}

export function SurveyProvider({ id, children }: { id: string; children: React.ReactNode }) {
  const pathname = usePathname();
  const { job, error: jobError } = useJobLive(id);
  const ready = job?.stage === "READY";
  const { metadata, manifest, summary, error: sceneError, loading } = useScene(ready ? id : null);

  const base = `/survey/${id}`;
  const active = TABS.find((tab) => tab.slug && pathname.startsWith(`${base}/${tab.slug}`))?.slug ?? "";

  const header = (
    <div className="sticky top-[72px] z-30 border-b border-glacier-300/50 bg-white/75 backdrop-blur-xl">
      <div className="mx-auto flex max-w-[1500px] flex-col gap-3 px-5 py-3 sm:flex-row sm:items-center sm:justify-between sm:px-8">
        <div className="flex min-w-0 items-center gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-polar-night">{job?.source_filename ?? "Loading scene…"}</p>
            <div className="mt-0.5 flex flex-wrap items-center gap-2">
              {metadata && <Badge tone={kindLabel(metadata.dsm_kind).tone}>{kindLabel(metadata.dsm_kind).text}</Badge>}
              {metadata && (
                <span className="mono text-[0.7rem] text-slate-ice">
                  {metadata.width}×{metadata.height} px{metadata.pixel_size_m && metadata.dsm_is_metric ? ` · ${metadata.pixel_size_m.toFixed(2)} m/px` : ""}
                </span>
              )}
            </div>
          </div>
        </div>
        <nav className="-mx-1 flex gap-1 overflow-x-auto px-1" aria-label="Survey sections">
          {TABS.map((tab) => (
            <Link
              key={tab.slug}
              href={tab.slug ? `${base}/${tab.slug}` : base}
              className={cn(
                "flex items-center gap-2 whitespace-nowrap rounded-lg px-3.5 py-2 text-sm font-semibold transition-colors",
                active === tab.slug ? "bg-deep-ice text-white shadow-sm" : "text-slate-ice hover:bg-glacier-100 hover:text-deep-ice",
              )}
            >
              <tab.icon className="h-4 w-4" strokeWidth={1.5} />
              {tab.label}
            </Link>
          ))}
        </nav>
      </div>
    </div>
  );

  let body: React.ReactNode;
  if (jobError) {
    body = <Notice title="Could not load this scene" text={jobError} id={id} />;
  } else if (!job) {
    body = (
      <div className="flex items-center justify-center gap-3 py-32 text-slate-ice">
        <Spinner /> Loading scene…
      </div>
    );
  } else if (!ready) {
    body = (
      <Notice
        title={job.stage === "FAILED" ? "This run failed" : "This scene is still being built"}
        text={job.stage === "FAILED" ? (job.error ?? "The pipeline stopped with an error.") : `Current stage: ${job.stage}. Follow the live progress page.`}
        id={id}
      />
    );
  } else if (loading) {
    body = (
      <div className="flex items-center justify-center gap-3 py-32 text-slate-ice">
        <Spinner /> Loading rasters and statistics…
      </div>
    );
  } else if (sceneError || !metadata || !manifest || !summary) {
    body = <Notice title="Scene data unavailable" text={sceneError ?? "Metadata could not be loaded."} id={id} />;
  } else {
    body = <SurveyCtx.Provider value={{ id, job, metadata, manifest, summary }}>{children}</SurveyCtx.Provider>;
  }

  return (
    <div className="flex min-h-[calc(100vh-4rem)] flex-col">
      {header}
      <div className="flex flex-1 flex-col">{body}</div>
    </div>
  );
}

function Notice({ title, text, id }: { title: string; text: string; id: string }) {
  return (
    <div className="mx-auto max-w-lg px-6 py-24 text-center">
      <BarChart3 className="mx-auto h-10 w-10 text-glacier-500" strokeWidth={1.2} />
      <h2 className="mt-4 text-xl font-semibold text-polar-night">{title}</h2>
      <p className="mt-2 text-sm leading-relaxed text-slate-ice">{text}</p>
      <Link href={`/expedition/${id}/progress`} className="btn btn-primary mt-6">
        Open progress page
      </Link>
    </div>
  );
}
