"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Helicopter, Plane, PlusCircle, RotateCcw, Zap } from "lucide-react";

import { Button, ErrorNote, InfoNote, Slider } from "@/components/ui";
import { runLanding } from "@/lib/api/survey";
import { areaParts, fmt } from "@/lib/format";
import type { LandingResult, LandingSite } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

import { errorText, Metric, MetricGrid, PanelTitle, Steps, type ScenarioCtx } from "./shared";

type Aircraft = "drone" | "helicopter" | "plane";

/** Illustrative planning presets (clear radius, steepest acceptable ground, clear radius needed), not aircraft specifications. */
const AIRCRAFT: Record<Aircraft, { label: string; icon: typeof Plane; radius: number; slope: number; needs: string; fits: (site: LandingSite) => boolean }> = {
  drone: { label: "Drone / UAV", icon: Zap, radius: 5, slope: 8, needs: "about 5 m clear radius", fits: (s) => s.clear_radius_m >= 2.5 },
  helicopter: { label: "Helicopter", icon: Helicopter, radius: 15, slope: 5, needs: "about 15 m clear radius", fits: (s) => s.clear_radius_m >= 8 },
  plane: { label: "Light plane", icon: Plane, radius: 15, slope: 3, needs: "a straight strip of about 250 m", fits: (s) => s.clear_radius_m * 2 >= 250 },
};

export function LandingScenario({ ctx }: { ctx: ScenarioCtx }) {
  const { id, metadata, send, uv, toViewerM, record } = ctx;
  const [aircraft, setAircraft] = useState<Aircraft>("helicopter");
  const [radius, setRadius] = useState(15);
  const [slope, setSlope] = useState(5);
  const [result, setResult] = useState<LandingResult | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  const [applied, setApplied] = useState({ radius: 15, slope: 5 });

  /** Put the aircraft on the 3D terrain over a site: a fresh object each time replays the landing. */
  const land = useCallback(
    (site: LandingSite, kind: Aircraft) => {
      const at = uv(site.col, site.row);
      send({ cmd: "landing", kind, ...at, radius: toViewerM(site.clear_radius_m), bearing: site.approach_heading_deg, fits: AIRCRAFT[kind].fits(site) });
      send({ cmd: "focus", ...at, distance: 0.24 });
    },
    [send, uv, toViewerM],
  );

  const find = useCallback(
    async (minRadius: number, maxSlope: number, kind: Aircraft) => {
      const mine = ++request.current;
      setBusy(true);
      setError(null);
      try {
        const found = await runLanding(id, { min_radius_m: minRadius, max_slope_deg: maxSlope, top_n: 8 });
        if (mine !== request.current) return;
        setResult(found);
        setApplied({ radius: minRadius, slope: maxSlope });
        const best = found.sites[0];
        setSelected(best ? best.rank : null);
        if (best) land(best, kind);
        else send({ cmd: "clear" });
      } catch (e) {
        if (mine === request.current) setError(errorText(e, "Landing-zone search failed."));
      } finally {
        if (mine === request.current) setBusy(false);
      }
    },
    [id, land, send],
  );

  useEffect(() => {
    void find(15, 5, "helicopter");
  }, [find]);

  function pickAircraft(kind: Aircraft) {
    const preset = AIRCRAFT[kind];
    setAircraft(kind);
    setRadius(preset.radius);
    setSlope(preset.slope);
    void find(preset.radius, preset.slope, kind);
  }

  function select(site: LandingSite) {
    setSelected(site.rank);
    land(site, aircraft);
  }

  const chosen = result?.sites.find((s) => s.rank === selected) ?? null;
  const best = result?.sites[0];
  const flattest = result && result.sites.length ? Math.min(...result.sites.map((s) => s.mean_slope_deg)) : null;
  const spec = AIRCRAFT[aircraft];
  const fitsChosen = chosen ? spec.fits(chosen) : null;

  return (
    <div className="space-y-4">
      <PanelTitle
        eyebrow="Scenario · Emergency landing"
        title="Landing-zone finder"
        text="Ranks flat, obstacle-free ground with a clear radius and an open approach, then lands the chosen aircraft on the selected site. Candidates for operator confirmation, not a landing clearance."
      />
      <Steps steps={["Pick an aircraft", "Choose a site", "Watch it land"]} current={chosen ? 2 : 1} />

      {error && <ErrorNote message={error} />}

      <div className="card space-y-4 p-4">
        <div className="grid grid-cols-3 gap-1.5">
          {(Object.keys(AIRCRAFT) as Aircraft[]).map((kind) => {
            const item = AIRCRAFT[kind];
            return (
              <button
                key={kind}
                type="button"
                onClick={() => pickAircraft(kind)}
                className={cn(
                  "flex flex-col items-center gap-1.5 rounded-lg border px-2 py-3 text-xs font-semibold transition-colors",
                  aircraft === kind ? "border-station-orange bg-station-orange text-white" : "border-glacier-300 text-slate-ice hover:text-deep-ice",
                )}
              >
                <item.icon className="h-5 w-5" strokeWidth={1.6} />
                {item.label}
              </button>
            );
          })}
        </div>
        <p className="text-xs leading-snug text-slate-ice">Needs {spec.needs}. Illustrative planning values, not aircraft specifications.</p>
        <Slider label="Minimum clear radius" value={radius} min={3} max={40} step={1} onChange={setRadius} format={(v) => `${v} m`} />
        <Slider label="Maximum slope" value={slope} min={1} max={15} step={0.5} onChange={setSlope} format={(v) => `${v}°`} />
        <Button className="w-full" loading={busy} onClick={() => void find(radius, slope, aircraft)}>
          Find candidate sites
        </Button>
      </div>

      <MetricGrid>
        <Metric label="Candidate sites" parts={result ? { value: result.sites.length, unit: "", digits: 0 } : null} tone="aurora" hint={result ? `radius ≥ ${applied.radius} m · slope ≤ ${applied.slope}°` : undefined} />
        <Metric label="Largest clear area" parts={best ? { value: best.clear_radius_m * 2, unit: "m Ø", digits: 0 } : null} tone="orange" hint={best ? `score ${fmt(best.score, 2)}` : undefined} />
        <Metric label="Flattest site" parts={flattest !== null ? { value: flattest, unit: "°", digits: 1 } : null} hint="mean slope under the site" />
        <Metric label="Usable ground" parts={result ? areaParts(result.candidate_area_km2) : null} hint="meets slope and clearance limits" />
      </MetricGrid>

      {chosen && (
        <div className={cn("card flex items-center justify-between gap-3 p-3.5", fitsChosen ? "border-aurora/50" : "border-krill/40")}>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-polar-night">Site {chosen.rank} · {spec.label}</p>
            <p className="text-xs leading-snug text-slate-ice">
              {fitsChosen
                ? "Fits: the clear area covers what this aircraft needs."
                : aircraft === "plane"
                  ? "Too short for a fixed-wing landing (about 250 m needed): the plane flies the approach and goes around."
                  : "Too small for this aircraft."}
            </p>
          </div>
          <Button variant="soft" size="sm" onClick={() => land(chosen, aircraft)}>
            <RotateCcw className="h-4 w-4" strokeWidth={1.75} /> Replay
          </Button>
        </div>
      )}

      {metadata.gsd_assumed && <InfoNote>Distances assume {fmt(metadata.pixel_size_m, 2)} m per pixel because the image has no scale.</InfoNote>}
      {result && result.sites.length === 0 && <InfoNote>No site met the criteria. Reduce the clear radius or allow a steeper slope.</InfoNote>}

      {result && result.sites.length > 0 && (
        <ul className="space-y-2">
          {result.sites.map((site) => (
            <li key={site.rank}>
              <button
                type="button"
                onClick={() => select(site)}
                className={cn("card flex w-full items-center gap-3 p-3 text-left transition-all", selected === site.rank && "border-station-orange shadow-[0_0_0_3px_rgba(242,107,33,0.15)]")}
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-aurora text-sm font-semibold text-white">{site.rank}</span>
                <span className="min-w-0 flex-1">
                  <span className="mono block text-sm font-semibold text-polar-night">Ø {fmt(site.clear_radius_m * 2, 0)} m · score {fmt(site.score, 2)}</span>
                  <span className="mono block truncate text-xs text-slate-ice">
                    {fmt(site.mean_slope_deg, 1)}° slope · {fmt(site.approach_clearance * 100, 0)}% approach clear
                    {site.nearest_road_m !== null ? ` · ${fmt(site.nearest_road_m, 0)} m to road` : ""}
                  </span>
                </span>
                <span className={cn("shrink-0 rounded-full px-2 py-0.5 text-[0.65rem] font-semibold", spec.fits(site) ? "bg-aurora/15 text-[#4d6b3f]" : "bg-krill/10 text-krill")}>{spec.fits(site) ? "Fits" : "Too small"}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {result && <p className="text-[0.7rem] leading-snug text-slate-ice">{result.disclaimer}</p>}

      <Button
        variant="ghost"
        className="w-full"
        disabled={!best}
        onClick={() =>
          best &&
          result &&
          void record(
            "landing",
            "Landing zones",
            `${result.sites.length} candidate sites (for operator confirmation); best has a ${fmt(best.clear_radius_m, 1)} m clear radius, ${fmt(best.mean_slope_deg, 1)}° slope, score ${fmt(best.score, 2)}.`,
            { count: result.sites.length },
          )
        }
      >
        <PlusCircle className="h-4 w-4" strokeWidth={1.5} /> Add to findings
      </Button>
    </div>
  );
}
