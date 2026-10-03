"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { API_BASE_URL, apiFetch } from "@/lib/api/client";

interface FeaturedScene {
  id: string;
  title: string;
  blurb: string;
  /** Extra links shown after "Open full survey". */
  extra: { href: (id: string) => string; label: string }[];
  /** Metric shown when present: label for the validation RMSE is only meaningful for scored scenes. */
  scored: boolean;
}

const FEATURED_SCENES: FeaturedScene[] = [
  {
    id: "featured-washington-dc",
    title: "Washington DC courtyard block with rail corridor",
    blurb:
      "A real pipeline run on a GAMUS test tile, ready to explore instantly: 3D terrain, flood and landing tools, and a validation lab scored against the tile's reference heights.",
    extra: [{ href: (id) => `/survey/${id}/validate`, label: "See accuracy" }],
    scored: true,
  },
  {
    id: "site-denver-7",
    title: "Denver suburb, Colorado: hand-verified 3D scene (7.tif)",
    blurb:
      "A 0.8 km GeoTIFF analysed without any model: every building, tree and car identified and checked by eye, each building with a shadow-based height estimate, shown in 3D with the full survey, hazards, AI brief and PDF stored.",
    extra: [
      { href: (id) => `/site/${id}`, label: "3D scene and analysis" },
      { href: () => "/map", label: "Show on world map" },
    ],
    scored: false,
  },
];

interface FeaturedMetrics {
  rmse: number | null;
  pearson_r: number | null;
  buildings: number | null;
}

/** One-click entries to the pre-processed featured scenes (real runs, stored locally). */
export function FeaturedSceneCard() {
  return (
    <>
      {FEATURED_SCENES.map((scene) => (
        <FeaturedCard key={scene.id} scene={scene} />
      ))}
    </>
  );
}

function FeaturedCard({ scene }: { scene: FeaturedScene }) {
  const FEATURED_ID = scene.id;
  const [metrics, setMetrics] = useState<FeaturedMetrics | null>(null);
  const [available, setAvailable] = useState(false);

  useEffect(() => {
    apiFetch<{ stage: string; summary: Record<string, number | string | null> }>(`/api/pipeline/${FEATURED_ID}`)
      .then((job) => {
        if (job.stage !== "READY") return;
        setAvailable(true);
        setMetrics({
          rmse: typeof job.summary.rmse === "number" ? job.summary.rmse : null,
          pearson_r: typeof job.summary.pearson_r === "number" ? job.summary.pearson_r : null,
          buildings: typeof job.summary.buildings === "number" ? job.summary.buildings : null,
        });
      })
      .catch(() => setAvailable(false));
  }, [FEATURED_ID]);

  if (!available) return null;

  return (
    <div className="glass-panel overflow-hidden rounded-2xl">
      <div className="grid gap-0 sm:grid-cols-[minmax(0,15rem)_1fr]">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`${API_BASE_URL}/api/pipeline/output/${FEATURED_ID}/thumb.jpg`} alt="Featured scene preview" className="h-44 w-full object-cover sm:h-full" />
        <div className="space-y-3 px-6 py-5">
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary/80">Featured scene</p>
            <span className="rounded-full border border-border px-2.5 py-0.5 text-[11px] font-medium text-muted-foreground">Pre-processed</span>
          </div>
          <h2 className="text-lg font-semibold text-foreground">{scene.title}</h2>
          <p className="text-sm text-muted-foreground">{scene.blurb}</p>
          <dl className="flex flex-wrap gap-x-8 gap-y-1 text-xs text-muted-foreground">
            {scene.scored && metrics?.rmse != null && (
              <div>
                <dt className="uppercase tracking-wide">RMSE vs reference</dt>
                <dd className="font-mono text-sm text-foreground">{metrics.rmse.toFixed(2)} m</dd>
              </div>
            )}
            {scene.scored && metrics?.pearson_r != null && (
              <div>
                <dt className="uppercase tracking-wide">Correlation</dt>
                <dd className="font-mono text-sm text-foreground">{metrics.pearson_r.toFixed(3)}</dd>
              </div>
            )}
            {metrics?.buildings != null && (
              <div>
                <dt className="uppercase tracking-wide">Buildings</dt>
                <dd className="font-mono text-sm text-foreground">{metrics.buildings}</dd>
              </div>
            )}
          </dl>
          <div className="flex flex-wrap gap-2 pt-1">
            <Link href={`/survey/${FEATURED_ID}`} className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90">
              Open full survey
            </Link>
            {scene.extra.map((e) => (
              <Link key={e.label} href={e.href(FEATURED_ID)} className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:border-primary/40 hover:text-foreground">
                {e.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
