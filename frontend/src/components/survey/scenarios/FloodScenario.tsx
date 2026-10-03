"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { PlusCircle, RotateCcw } from "lucide-react";

import { Button, ErrorNote, InfoNote, Slider } from "@/components/ui";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { jobFileUrl, runFlood } from "@/lib/api/survey";
import { areaParts, fmt, volumeParts } from "@/lib/format";
import type { FloodResult } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

import { errorText, Metric, MetricGrid, PanelTitle, Steps, type ScenarioCtx } from "./shared";

/** Highest water level the slider offers. */
const MAX_LEVEL = 100;
const PRESETS = [2, 5, 10, 25, 50, 100];

interface BuildingHeight {
  height_m: number | null;
}

export function FloodScenario({ ctx }: { ctx: ScenarioCtx }) {
  const { id, metadata, summary, send, record } = ctx;
  const metric = metadata.dsm_is_metric;
  const unit = metric ? "m" : "rel";
  const groundMin = metadata.mesh_elevation_min ?? summary.height_min ?? 0;

  const [heights, setHeights] = useState<number[]>([]);
  useEffect(() => {
    fetch(jobFileUrl(id, "buildings.json"))
      .then((r) => r.json())
      .then((d: { buildings: BuildingHeight[] }) => setHeights(d.buildings.map((b) => b.height_m).filter((v): v is number => v !== null && Number.isFinite(v))))
      .catch(() => setHeights([]));
  }, [id]);
  const tallest = heights.length ? Math.max(...heights) : 0;

  // Manual simulation: the slider is the water level, and the 3D water follows it directly.
  const [level, setLevel] = useState(0);
  const debounced = useDebouncedValue(level, 300);
  const [result, setResult] = useState<FloodResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);

  useEffect(() => {
    const mine = ++request.current;
    runFlood(id, debounced)
      .then((r) => mine === request.current && (setResult(r), setError(null)))
      .catch((e) => mine === request.current && setError(errorText(e, "Flood simulation failed.")));
  }, [id, debounced]);

  // Without a DEM every height is above local ground, so there is no relief to flood: model a uniform depth over flat ground.
  const uniform = result?.terrain_available === false;
  // The reference the level is measured from (terrain scenes only): fixed for a scene, so any result gives it.
  const reference = result?.reference_elevation ?? groundMin;
  const surface = uniform ? groundMin + level : reference + level;

  const lastSent = useRef<number | null>(null);
  useEffect(() => {
    if (lastSent.current !== null && Math.abs(surface - lastSent.current) < 1e-3) return;
    lastSent.current = surface;
    send({ cmd: "water", level: surface });
  }, [surface, send]);

  const submerged = useMemo(() => heights.filter((h) => h <= level).length, [heights, level]);
  const affectedShare = result && result.total_buildings > 0 ? (result.affected_buildings / result.total_buildings) * 100 : 0;

  return (
    <div className="space-y-4">
      <PanelTitle
        eyebrow="Scenario · Flood"
        title="Flood level simulation"
        text={uniform
          ? "Drag the level and the water rises or falls in the 3D view. This image has no ground relief, so the depth is uniform over flat land and buildings are judged by their height."
          : "Drag the level and the water rises or falls over the terrain in the 3D view. Every connected low area floods, and buildings count as flooded when their footprint is."}
      />
      <Steps steps={["Set the level", "Read the impact"]} current={level > 0 ? 1 : 0} />

      {error && <ErrorNote message={error} />}
      {uniform && <InfoNote>No DEM-calibrated ground here (a plain image), so this is a flat-ground what-if, not a hydrological model. Use a georeferenced GeoTIFF with a DEM for terrain-following flooding.</InfoNote>}

      <div className="card space-y-4 p-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="eyebrow !text-slate-ice">Water level</p>
            <p className="mono mt-1 text-4xl font-semibold leading-none text-[#2b7bd6]">
              {fmt(level, 1)}
              <span className="ml-1 text-base font-medium text-slate-ice">{unit}</span>
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => setLevel(0)} disabled={level === 0}>
            <RotateCcw className="h-4 w-4" strokeWidth={1.75} /> Reset
          </Button>
        </div>
        <Slider label={`Level above ${uniform ? "the ground" : "the reference"} (${unit})`} value={level} min={0} max={MAX_LEVEL} step={0.5} onChange={setLevel} format={(v) => `${fmt(v, 1)} ${unit}`} />
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setLevel(p)}
              className={cn(
                "rounded-lg border px-2.5 py-1 text-xs font-semibold transition-colors",
                level === p ? "border-station-orange bg-station-orange text-white" : "border-glacier-300 text-slate-ice hover:text-deep-ice",
              )}
            >
              {p} {unit}
            </button>
          ))}
        </div>
        {!uniform && (
          <p className="text-xs leading-snug text-slate-ice">
            Reference is {result?.reference_elevation != null ? `${fmt(result.reference_elevation, 1)} ${unit}` : "…"} (median of water bodies, else the lowest terrain). Water spreads from {result?.seed ?? "the seed"}.
          </p>
        )}
      </div>

      {uniform ? (
        <MetricGrid>
          <Metric label="Roofs under water" parts={{ value: submerged, unit: `/ ${heights.length}`, digits: 0 }} tone="krill" hint="buildings shorter than the water depth" />
          <Metric label="Tallest above water" parts={heights.length ? { value: Math.max(tallest - level, 0), unit, digits: 1 } : null} hint={heights.length ? `tallest building ${fmt(tallest, 1)} ${unit}` : undefined} />
          <Metric label="Storeys under water" parts={{ value: level / 3, unit: "", digits: 1 }} hint="at about 3 m per storey" />
          <Metric label="Ground flooded" parts={{ value: level > 0.05 ? 100 : 0, unit: "%", digits: 0 }} hint="flat land, uniform depth" tone="orange" />
        </MetricGrid>
      ) : (
        <MetricGrid>
          <Metric label="Inundated area" parts={result ? areaParts(result.area_km2) : null} tone="orange" hint={result ? `${fmt(result.area_fraction * 100, 1)}% of the scene` : undefined} />
          <Metric
            label="Buildings affected"
            parts={result ? { value: result.affected_buildings, unit: `/ ${result.total_buildings}`, digits: 0 } : null}
            tone="krill"
            hint={result ? `${fmt(affectedShare, 0)}% of detected buildings` : undefined}
          />
          <Metric label="Max depth" parts={result ? { value: result.max_depth, unit, digits: 1 } : null} hint={result ? `mean ${fmt(result.mean_depth, 1)} ${unit}` : undefined} />
          <Metric
            label="Water volume"
            parts={result && result.volume_m3 !== null ? volumeParts(result.volume_m3) : null}
            hint={result && result.affected_footprint_m2 ? `${fmt(result.affected_footprint_m2, 0)} m² of roofs affected` : undefined}
          />
        </MetricGrid>
      )}

      {!uniform && result && result.worst_hit_areas.length > 0 && (
        <div className="card space-y-2.5 p-4">
          <p className="eyebrow">Worst-hit areas</p>
          {result.worst_hit_areas.map((area) => (
            <div key={area.area}>
              <div className="flex justify-between text-xs">
                <span className="font-semibold capitalize text-deep-ice">{area.area}</span>
                <span className="mono text-slate-ice">{fmt(area.flooded_fraction * 100, 0)}% flooded · {fmt(area.mean_depth, 1)} {unit} deep</span>
              </div>
              <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-glacier-100">
                <div className="h-full rounded-full bg-station-orange" style={{ width: `${Math.min(100, area.flooded_fraction * 100)}%` }} />
              </div>
            </div>
          ))}
        </div>
      )}

      <Button
        variant="ghost"
        className="w-full"
        disabled={level === 0 || (!uniform && !result)}
        onClick={() => {
          if (uniform) {
            void record("flood", "Flood scenario", `A uniform flood depth of ${fmt(level, 1)} ${unit} over flat ground submerges the roofs of ${submerged} of ${heights.length} buildings.`, { depth: level });
          } else if (result) {
            const area = areaParts(result.area_km2);
            void record("flood", "Flood scenario", `A water level ${fmt(result.level, 1)} ${unit} above reference inundates ${fmt(area.value, area.digits)} ${area.unit} and affects ${result.affected_buildings} of ${result.total_buildings} buildings.`, { level: result.level, area_km2: result.area_km2, affected: result.affected_buildings });
          }
        }}
      >
        <PlusCircle className="h-4 w-4" strokeWidth={1.5} /> Add to findings
      </Button>
    </div>
  );
}
