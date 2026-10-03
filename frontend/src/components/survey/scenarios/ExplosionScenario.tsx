"use client";

import { useState } from "react";
import { Bomb, Crosshair, PlusCircle, RotateCcw } from "lucide-react";

import { Button, ErrorNote, InfoNote, Slider } from "@/components/ui";
import { runExplosion } from "@/lib/api/survey";
import { areaParts, distanceParts, fmt } from "@/lib/format";
import type { ExplosionBand, ExplosionResult } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

import { errorText, Metric, MetricGrid, PanelTitle, PickButton, Steps, type ScenarioCtx } from "./shared";

const PRESETS = [
  { label: "Small cylinder · 50 kg", value: 50 },
  { label: "Vehicle-borne · 500 kg", value: 500 },
  { label: "Large industrial · 2,000 kg", value: 2000 },
];

const BAND_COLOR: Record<ExplosionBand["severity"], string> = { severe: "#e61a1a", moderate: "#ff8c1a", light: "#ffeb33" };
/** Text-safe versions of the band colours (pale yellow is unreadable on the card background). */
const BAND_TEXT: Record<ExplosionBand["severity"], string> = { severe: "#e61a1a", moderate: "#d97706", light: "#a88a2c" };

export function ExplosionScenario({ ctx }: { ctx: ScenarioCtx }) {
  const { id, metadata, send, uv, toViewerM, record } = ctx;
  const [point, setPoint] = useState<{ col: number; row: number } | null>(null);
  const [yieldKg, setYieldKg] = useState(500);
  const [result, setResult] = useState<ExplosionResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Play the explosion: the viewer wants the radii from the light band out to the severe one. */
  function show(res: ExplosionResult) {
    const at = uv(res.epicentre.col, res.epicentre.row);
    const byBand = (s: ExplosionBand["severity"]) => toViewerM(res.bands.find((b) => b.severity === s)?.radius_m ?? 0);
    send({ cmd: "explosion", ...at, radii: [byBand("light"), byBand("moderate"), byBand("severe")] });
    send({ cmd: "focus", ...at, distance: 0.34 });
  }

  async function detonate(at = point, kg = yieldKg) {
    if (!at) return;
    setBusy(true);
    setError(null);
    try {
      const res = await runExplosion(id, { col: at.col, row: at.row, yield_kg: kg });
      setResult(res);
      show(res);
    } catch (e) {
      setError(errorText(e, "Impact simulation failed."));
    } finally {
      setBusy(false);
    }
  }

  function place(col: number, row: number) {
    setPoint({ col, row });
    setResult(null);
    const at = uv(col, row);
    send({ cmd: "clear" });
    send({ cmd: "pin", ...at });
    send({ cmd: "focus", ...at, distance: 0.45 });
  }

  const nearestBuildings = result?.nearest.filter((b) => b.band !== null) ?? [];
  const step = result ? 2 : point ? 1 : 0;

  return (
    <div className="space-y-4">
      <PanelTitle
        eyebrow="Scenario · Explosion impact"
        title="Blast and damage radii"
        text="Pick a point on the 3D terrain and set the yield. The blast plays out with its structural-damage rings, and the detected buildings inside each ring are counted. It reports damage to buildings only, never casualties."
      />
      <Steps steps={["Pick the epicentre", "Set the yield", "Detonate"]} current={step} />

      {error && <ErrorNote message={error} />}

      <div className="card space-y-4 p-4">
        <PickButton ctx={ctx} label="Pick epicentre on the 3D terrain" onPick={place} done={!!point} />
        <div className="flex items-center justify-between gap-3 rounded-lg border border-glacier-300/70 bg-white/50 px-3.5 py-2">
          <p className="mono truncate text-xs text-slate-ice">{point ? `Epicentre · pixel ${Math.round(point.col)}, ${Math.round(point.row)}` : "No epicentre yet"}</p>
          <Button variant="ghost" size="sm" onClick={() => place(metadata.width / 2, metadata.height / 2)}>
            <Crosshair className="h-4 w-4" strokeWidth={1.5} /> Centre
          </Button>
        </div>

        <div>
          <div className="flex flex-wrap gap-1.5">
            {PRESETS.map((preset) => (
              <button
                key={preset.value}
                type="button"
                onClick={() => setYieldKg(preset.value)}
                className={cn(
                  "rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors",
                  yieldKg === preset.value ? "border-station-orange bg-station-orange text-white" : "border-glacier-300 text-slate-ice hover:text-deep-ice",
                )}
              >
                {preset.label}
              </button>
            ))}
          </div>
          <div className="mt-4">
            <Slider label="TNT-equivalent yield" value={yieldKg} min={1} max={5000} step={1} onChange={setYieldKg} format={(v) => `${v.toLocaleString("en-US")} kg`} />
          </div>
          <p className="mt-2 text-[0.7rem] leading-snug text-slate-ice">An illustrative input you choose, not a measured quantity.</p>
        </div>

        <Button className="w-full" size="lg" loading={busy} disabled={!point} onClick={() => void detonate()}>
          <Bomb className="h-5 w-5" strokeWidth={1.75} /> {result ? "Detonate again" : "Detonate"}
        </Button>
        {result && (
          <Button variant="ghost" className="w-full" onClick={() => show(result)}>
            <RotateCcw className="h-4 w-4" strokeWidth={1.75} /> Replay the animation
          </Button>
        )}
      </div>

      {metadata.gsd_assumed && <InfoNote>Ground distances assume {fmt(metadata.pixel_size_m, 2)} m per pixel because the image has no scale. Enter its real GSD in Advanced Run for true distances.</InfoNote>}

      {result && (
        <>
          <div className="space-y-2">
            {result.bands.map((band) => {
              const radius = distanceParts(band.radius_m);
              const area = areaParts(band.area_km2);
              return (
                <div key={band.severity} className="card flex items-stretch gap-3 overflow-hidden p-0">
                  <span className="w-1.5 shrink-0" style={{ background: BAND_COLOR[band.severity] }} />
                  <div className="min-w-0 flex-1 py-3">
                    <p className="text-sm font-semibold text-polar-night">{band.label}</p>
                    <p className="mono text-xs text-slate-ice">
                      Z = {band.scaled_distance} · radius {fmt(radius.value, radius.digits)} {radius.unit} · {fmt(area.value, area.digits)} {area.unit}
                    </p>
                  </div>
                  <div className="shrink-0 py-3 pr-4 text-right">
                    <p className="mono text-2xl font-semibold leading-none text-polar-night">{band.buildings}</p>
                    <p className="mt-1 text-[0.68rem] font-semibold uppercase tracking-wider text-slate-ice">buildings</p>
                  </div>
                </div>
              );
            })}
          </div>

          <MetricGrid>
            <Metric label="Severe zone radius" parts={distanceParts(result.bands[0].radius_m)} tone="krill" hint={`${result.bands[0].buildings} building(s) inside`} />
            <Metric label="Light-damage reach" parts={distanceParts(result.bands[2].radius_m)} tone="orange" hint={`${result.bands[2].buildings} of ${result.total_buildings} buildings`} />
            <Metric label="Roof area in range" parts={areaParts(result.bands[2].footprint_m2 / 1e6)} hint="footprints inside the outer band" />
            <Metric label="Tallest in range" parts={result.bands[2].tallest_m !== null ? { value: result.bands[2].tallest_m, unit: "m", digits: 1 } : null} />
          </MetricGrid>

          {nearestBuildings.length > 0 && (
            <div className="card overflow-hidden">
              <p className="eyebrow px-4 pt-4">Nearest buildings in range</p>
              <table className="mt-2 w-full">
                <thead>
                  <tr className="text-[0.66rem] font-semibold uppercase tracking-wider text-slate-ice">
                    <th className="px-4 pb-2 text-left">Building</th>
                    <th className="pb-2 text-right">Distance</th>
                    <th className="pb-2 text-right">Height</th>
                    <th className="px-4 pb-2 text-right">Band</th>
                  </tr>
                </thead>
                <tbody>
                  {nearestBuildings.map((b) => (
                    <tr key={b.id} className="border-t border-glacier-300/40">
                      <td className="mono px-4 py-2 text-sm">#{b.id}</td>
                      <td className="mono py-2 text-right text-sm">{fmt(b.distance_m, 0)} m</td>
                      <td className="mono py-2 text-right text-sm">{b.height_m !== null ? `${fmt(b.height_m, 1)} m` : "n/a"}</td>
                      <td className="px-4 py-2 text-right text-xs font-semibold capitalize" style={{ color: b.band ? BAND_TEXT[b.band] : undefined }}>{b.band}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="text-[0.7rem] leading-snug text-slate-ice">{result.note}</p>
        </>
      )}

      <Button
        variant="ghost"
        className="w-full"
        disabled={!result}
        onClick={() =>
          result &&
          void record(
            "explosion",
            "Explosion impact scenario",
            `A ${result.yield_kg.toLocaleString("en-US")} kg TNT-equivalent event at pixel (${Math.round(result.epicentre.col)}, ${Math.round(result.epicentre.row)}) has structural-damage radii of ${result.bands.map((b) => `${fmt(b.radius_m, 0)} m ${b.severity}`).join(", ")}; ${result.bands[2].buildings} of ${result.total_buildings} buildings fall within the outer band.`,
            { yield_kg: result.yield_kg, buildings_in_range: result.bands[2].buildings },
          )
        }
      >
        <PlusCircle className="h-4 w-4" strokeWidth={1.5} /> Add to findings
      </Button>
    </div>
  );
}
