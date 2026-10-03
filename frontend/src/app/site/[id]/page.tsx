"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { AppHeader } from "@/components/common/AppHeader";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { UnityViewer } from "@/components/viewer/UnityViewer";
import { API_BASE_URL, ApiError, apiFetch } from "@/lib/api/client";

interface Stats {
  count: number;
  mean: number;
  median: number;
  p10: number;
  p90: number;
  min: number;
  max: number;
}
interface Bin {
  from: number;
  to: number;
  count: number;
}
interface BuildingRow {
  id: number;
  kind: string;
  label: string;
  area_m2: number;
  height_m: number;
  eave_m: number;
  ridge_m: number;
  uncertainty_m: number;
  height_method: string;
  floors_est: number;
  length_m: number;
  width_m: number;
  lon: number;
  lat: number;
}
interface Analysis {
  title: string;
  generated_by: string;
  location: { centre_lon_lat: [number, number]; bounds_wgs84: number[]; crs: string; pixel_size_m: number; size_m: number; area_ha: number; area_km2: number };
  sun: { shadow_azimuth_deg: number; sun_azimuth_deg: number; sun_elevation_deg: number; method: string };
  terrain: { source: string; min_m: number; max_m: number; mean_m: number; relief_m: number; note: string };
  landcover_percent: Record<string, number>;
  impervious_percent: number;
  buildings: {
    count: number;
    by_kind: Record<string, number>;
    footprint_total_m2: number;
    coverage_percent: number;
    density_per_km2: number;
    height_m: Stats;
    house_height_m: Stats;
    commercial_height_m: Stats;
    height_histogram: Bin[];
    footprint_histogram: Bin[];
    heights_from_shadow: number;
    heights_assumed: number;
    floors: Record<string, number>;
    tallest: BuildingRow[];
    largest: BuildingRow[];
  };
  trees: { count: number; density_per_ha: number; canopy_cover_percent: number; canopy_area_ha: number; height_m: Stats; height_histogram: Bin[]; heights_from_shadow: number; heights_assumed: number };
  vehicles: { count: number; note: string };
  pavement: { area_ha: number; percent: number };
  rocks: { count: number; note: string };
  mountains: { count: number; note: string };
  method: Record<string, string>;
  limits: string[];
  buildings_table: BuildingRow[];
}

const COVER_COLOURS: Record<string, string> = {
  "open ground / lawn": "#809c5c",
  pavement: "#707076",
  "tree canopy": "#20702c",
  buildings: "#d64638",
  vehicles: "#ffdc28",
};

function Bars({ bins, unit, colour }: { bins: Bin[]; unit: string; colour: string }) {
  const max = Math.max(1, ...bins.map((b) => b.count));
  return (
    <div className="space-y-1.5">
      {bins.map((b) => (
        <div key={`${b.from}-${b.to}`} className="flex items-center gap-2 text-xs">
          <span className="w-24 shrink-0 text-right text-muted-foreground">
            {b.from}–{b.to} {unit}
          </span>
          <div className="h-4 flex-1 rounded bg-muted/40">
            <div className="h-4 rounded" style={{ width: `${(b.count / max) * 100}%`, background: colour }} />
          </div>
          <span className="w-10 shrink-0 tabular-nums text-foreground">{b.count}</span>
        </div>
      ))}
    </div>
  );
}

function Kpi({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="glass-panel rounded-xl p-4">
      <p className="text-2xl font-semibold text-foreground">{value}</p>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      {note && <p className="mt-1 text-[11px] text-muted-foreground">{note}</p>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="glass-panel rounded-2xl p-5">
      <h2 className="mb-3 text-lg font-semibold text-foreground">{title}</h2>
      {children}
    </section>
  );
}

const fmt = (n: number | undefined | null, d = 1) => (n === undefined || n === null || Number.isNaN(n) ? "n/a" : n.toLocaleString(undefined, { maximumFractionDigits: d }));

export default function SitePage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<Analysis | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<string>("all");
  const [sort, setSort] = useState<"height_m" | "area_m2">("height_m");

  useEffect(() => {
    let cancelled = false;
    apiFetch<Analysis>(`/api/pipeline/${id}/site-analysis`)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load the analysis.");
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.buildings_table
      .filter((r) => kind === "all" || r.kind === kind)
      .sort((a, b) => b[sort] - a[sort])
      .slice(0, 60);
  }, [data, kind, sort]);

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1600px] flex-1 space-y-6 px-6 py-8 xl:px-10">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">{data?.title ?? "Site analysis"}</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Buildings, trees and vehicles identified in the GeoTIFF with classical image analysis (no machine-learning model), shown in 3D with an estimated height for every building.
            </p>
          </div>
          <Link href="/map" className="rounded-lg border border-border px-3 py-1.5 text-sm font-semibold text-foreground">
            Back to world map
          </Link>
        </div>

        {error && <ErrorBanner message={error} />}

        <div className="overflow-hidden rounded-2xl border border-border">
          <UnityViewer key={id} jobId={id} frameClassName="h-[68vh] min-h-[460px]" />
        </div>
        <p className="text-xs text-muted-foreground">Drag to orbit, right-drag to pan, wheel to zoom, C for the first-person fly-through. Click a building to read its height.</p>

        {data && (
          <>
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-6">
              <Kpi label="Area covered" value={`${fmt(data.location.area_ha)} ha`} note={`${fmt(data.location.size_m, 0)} m square`} />
              <Kpi label="Buildings" value={fmt(data.buildings.count, 0)} note={`${fmt(data.buildings.coverage_percent)}% of the ground`} />
              <Kpi label="Median building height" value={`${fmt(data.buildings.height_m.median)} m`} note={`${fmt(data.buildings.height_m.p10)}–${fmt(data.buildings.height_m.p90)} m (10th–90th pct)`} />
              <Kpi label="Trees" value={fmt(data.trees.count, 0)} note={`${fmt(data.trees.canopy_cover_percent)}% canopy`} />
              <Kpi label="Vehicles" value={fmt(data.vehicles.count, 0)} note="parking areas, lower bound" />
              <Kpi label="Hard surface" value={`${fmt(data.impervious_percent)}%`} note="roads, roofs, lots" />
            </div>

            <div className="grid gap-5 lg:grid-cols-2">
              <Section title="Land cover">
                <div className="mb-3 flex h-6 overflow-hidden rounded">
                  {Object.entries(data.landcover_percent).map(([name, pct]) => (
                    <div key={name} title={`${name}: ${pct}%`} style={{ width: `${pct}%`, background: COVER_COLOURS[name] ?? "#999" }} />
                  ))}
                </div>
                <ul className="grid grid-cols-2 gap-1.5 text-sm">
                  {Object.entries(data.landcover_percent).map(([name, pct]) => (
                    <li key={name} className="flex items-center gap-2">
                      <span className="h-3 w-3 rounded-sm" style={{ background: COVER_COLOURS[name] ?? "#999" }} />
                      <span className="text-muted-foreground">{name}</span>
                      <span className="ml-auto tabular-nums text-foreground">{pct}%</span>
                    </li>
                  ))}
                </ul>
              </Section>

              <Section title="Where and when">
                <dl className="grid grid-cols-[9rem_1fr] gap-y-1.5 text-sm">
                  <dt className="text-muted-foreground">Centre (lat, lon)</dt>
                  <dd>{data.location.centre_lon_lat[1].toFixed(5)}, {data.location.centre_lon_lat[0].toFixed(5)}</dd>
                  <dt className="text-muted-foreground">Coordinate system</dt>
                  <dd>{data.location.crs} (US survey feet)</dd>
                  <dt className="text-muted-foreground">Pixel size</dt>
                  <dd>{fmt(data.location.pixel_size_m * 100, 1)} cm</dd>
                  <dt className="text-muted-foreground">Sun azimuth</dt>
                  <dd>{fmt(data.sun.sun_azimuth_deg)}° (measured from shadows)</dd>
                  <dt className="text-muted-foreground">Sun elevation</dt>
                  <dd>{fmt(data.sun.sun_elevation_deg)}°</dd>
                  <dt className="text-muted-foreground">Terrain</dt>
                  <dd>{fmt(data.terrain.min_m, 0)}–{fmt(data.terrain.max_m, 0)} m above sea level, relief {fmt(data.terrain.relief_m, 0)} m</dd>
                </dl>
                <p className="mt-3 text-xs text-muted-foreground">{data.terrain.note}</p>
              </Section>

              <Section title="Building heights">
                <Bars bins={data.buildings.height_histogram} unit="m" colour="#d64638" />
                <p className="mt-3 text-xs text-muted-foreground">
                  {data.buildings.heights_from_shadow} heights come from measured shadow length; {data.buildings.heights_assumed} had no usable shadow and use a typical value for their type.
                  Houses: median {fmt(data.buildings.house_height_m.median)} m. Commercial: median {fmt(data.buildings.commercial_height_m.median)} m.
                </p>
              </Section>

              <Section title="Building footprints">
                <Bars bins={data.buildings.footprint_histogram} unit="m²" colour="#1f5f8b" />
                <p className="mt-3 text-xs text-muted-foreground">
                  Total roof area {fmt(data.buildings.footprint_total_m2, 0)} m². Types: {Object.entries(data.buildings.by_kind).map(([k, v]) => `${v} ${k}`).join(", ")}.
                </p>
              </Section>

              <Section title="Trees">
                <Bars bins={data.trees.height_histogram} unit="m" colour="#20702c" />
                <p className="mt-3 text-xs text-muted-foreground">
                  Median height {fmt(data.trees.height_m.median)} m, {fmt(data.trees.density_per_ha)} trees per hectare, {fmt(data.trees.canopy_area_ha)} ha of canopy.
                </p>
              </Section>

              <Section title="Other features">
                <ul className="space-y-2 text-sm text-muted-foreground">
                  <li><b className="text-foreground">Vehicles:</b> {data.vehicles.note}</li>
                  <li><b className="text-foreground">Rocks:</b> {data.rocks.note}</li>
                  <li><b className="text-foreground">Mountains:</b> {data.mountains.note}</li>
                  <li><b className="text-foreground">Pavement:</b> {fmt(data.pavement.area_ha)} ha ({fmt(data.pavement.percent)}%).</li>
                </ul>
              </Section>
            </div>

            <Section title="Every building">
              <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
                <label className="flex items-center gap-2">
                  Type
                  <select value={kind} onChange={(e) => setKind(e.target.value)} className="rounded border border-border bg-background px-2 py-1">
                    <option value="all">all</option>
                    {Object.keys(data.buildings.by_kind).map((k) => (
                      <option key={k} value={k}>{k}</option>
                    ))}
                  </select>
                </label>
                <label className="flex items-center gap-2">
                  Sort by
                  <select value={sort} onChange={(e) => setSort(e.target.value as "height_m" | "area_m2")} className="rounded border border-border bg-background px-2 py-1">
                    <option value="height_m">height</option>
                    <option value="area_m2">footprint</option>
                  </select>
                </label>
                <span className="text-xs text-muted-foreground">Top 60 shown of {data.buildings.count}.</span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="py-1.5 pr-3">#</th><th className="pr-3">Type</th><th className="pr-3">Height</th><th className="pr-3">±</th><th className="pr-3">Eave</th>
                      <th className="pr-3">Floors</th><th className="pr-3">Footprint</th><th className="pr-3">Size</th><th className="pr-3">Basis</th><th>Location</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.id} className="border-t border-border/60">
                        <td className="py-1.5 pr-3 tabular-nums">{r.id}</td>
                        <td className="pr-3">{r.kind}</td>
                        <td className="pr-3 font-semibold tabular-nums">{fmt(r.height_m)} m</td>
                        <td className="pr-3 tabular-nums text-muted-foreground">{fmt(r.uncertainty_m)}</td>
                        <td className="pr-3 tabular-nums">{fmt(r.eave_m)} m</td>
                        <td className="pr-3 tabular-nums">{r.floors_est}</td>
                        <td className="pr-3 tabular-nums">{fmt(r.area_m2, 0)} m²</td>
                        <td className="pr-3 tabular-nums">{fmt(r.length_m)}×{fmt(r.width_m)} m</td>
                        <td className="pr-3">{r.height_method === "shadow" ? "shadow" : "typical"}</td>
                        <td className="tabular-nums text-muted-foreground">{r.lat.toFixed(5)}, {r.lon.toFixed(5)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Section>

            <Section title="How this was made, and its limits">
              <ul className="space-y-2 text-sm text-muted-foreground">
                {Object.entries(data.method).map(([k, v]) => (
                  <li key={k}><b className="text-foreground">{k}:</b> {v}</li>
                ))}
              </ul>
              <ul className="mt-4 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
                {data.limits.map((l) => (
                  <li key={l}>{l}</li>
                ))}
              </ul>
              <p className="mt-3 text-xs text-muted-foreground">
                Raw data: <a className="underline" href={`${API_BASE_URL}/api/pipeline/${id}/site-analysis`}>analysis.json</a>
              </p>
            </Section>
          </>
        )}
      </main>
    </div>
  );
}
