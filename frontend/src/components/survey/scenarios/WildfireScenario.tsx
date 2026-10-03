"use client";

import { useState } from "react";
import { Crosshair, Droplets, Flame, PlusCircle, RotateCcw } from "lucide-react";

import { Button, ErrorNote, InfoNote, Slider } from "@/components/ui";
import { runWildfire } from "@/lib/api/survey";
import { distanceParts, fmt, titleCase } from "@/lib/format";
import type { WildfireResult } from "@/lib/sceneTypes";

import { errorText, Metric, MetricGrid, PanelTitle, PickButton, Steps, type ScenarioCtx } from "./shared";

export function WildfireScenario({ ctx }: { ctx: ScenarioCtx }) {
  const { id, metadata, send, uv, toViewerM, record } = ctx;
  const [point, setPoint] = useState<{ col: number; row: number } | null>(null);
  const [hover, setHover] = useState(30);
  const [velocity, setVelocity] = useState(20);
  const [result, setResult] = useState<WildfireResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /** Light the fire at a spot (the ignition animation) and bring the camera to it. */
  function ignite(col: number, row: number) {
    const at = uv(col, row);
    send({ cmd: "fire", ...at });
    send({ cmd: "focus", ...at, distance: 0.3 });
  }

  function place(col: number, row: number) {
    setPoint({ col, row });
    setResult(null);
    ignite(col, row);
  }

  /** The drone flies in to the computed stand-off point and pours water on the fire. */
  function flyDrone(at: { col: number; row: number }, res: WildfireResult) {
    const p = uv(at.col, at.row);
    send({ cmd: "drop", ...p, hover: res.hover_altitude_agl_m ?? hover, reach: toViewerM(res.horizontal_reach_m ?? 0) });
    send({ cmd: "focus", ...p, distance: 0.42 });
  }

  async function drop() {
    if (!point) return;
    setBusy(true);
    setError(null);
    try {
      const res = await runWildfire(id, { col: point.col, row: point.row, hover_agl_m: hover, exit_velocity_mps: velocity });
      setResult(res);
      if (res.status === "computed") flyDrone(point, res);
    } catch (e) {
      setError(errorText(e, "Drop calculation failed."));
    } finally {
      setBusy(false);
    }
  }

  const computed = result?.status === "computed" ? result : null;
  const step = computed ? 3 : point ? 2 : 0;

  return (
    <div className="space-y-4">
      <PanelTitle
        eyebrow="Scenario · Wildfire"
        title="Drone water-drop"
        text="Mark where the fire starts and watch it catch. Then calculate the drop: a drone flies in from the sky, stands off at the computed distance and pours water on the fire along the true projectile arc."
      />
      <Steps steps={["Pick the spot", "Fire burns", "Calculate the drop", "Extinguished"]} current={step} />

      {error && <ErrorNote message={error} />}

      <div className="card space-y-4 p-4">
        <PickButton ctx={ctx} label="Pick the fire spot on the 3D terrain" onPick={place} done={!!point} />
        <div className="flex items-center justify-between gap-3 rounded-lg border border-glacier-300/70 bg-white/50 px-3.5 py-2">
          <p className="mono truncate text-xs text-slate-ice">{point ? `Fire · pixel ${Math.round(point.col)}, ${Math.round(point.row)}` : "No fire location yet"}</p>
          <div className="flex gap-1.5">
            <Button variant="ghost" size="sm" onClick={() => place(metadata.width / 2, metadata.height / 2)}>
              <Crosshair className="h-4 w-4" strokeWidth={1.5} /> Centre
            </Button>
            <Button variant="ghost" size="sm" disabled={!point} onClick={() => point && ignite(point.col, point.row)} aria-label="Light the fire again">
              <Flame className="h-4 w-4" strokeWidth={1.5} />
            </Button>
          </div>
        </div>

        <Slider label="Hover altitude above ground" value={hover} min={5} max={150} step={1} onChange={setHover} format={(v) => `${v} m`} />
        <Slider label="Water exit velocity" value={velocity} min={5} max={60} step={0.5} onChange={setVelocity} format={(v) => `${v} m/s`} />
        <p className="text-[0.7rem] leading-snug text-slate-ice">Illustrative assumptions, not product specifications. Match them to the drone you plan to use.</p>

        <Button className="w-full" size="lg" loading={busy} disabled={!point} onClick={() => void drop()}>
          <Droplets className="h-5 w-5" strokeWidth={1.75} /> {computed ? "Calculate and fly again" : "Calculate drop"}
        </Button>
        {computed && (
          <Button
            variant="ghost"
            className="w-full"
            onClick={() => point && flyDrone(point, computed)}
          >
            <RotateCcw className="h-4 w-4" strokeWidth={1.75} /> Replay the drop
          </Button>
        )}
      </div>

      {result?.status === "unavailable" && <InfoNote>{result.note}</InfoNote>}

      {computed && (
        <>
          <MetricGrid>
            <Metric label="Stand-off distance" parts={computed.horizontal_reach_m !== undefined ? distanceParts(computed.horizontal_reach_m) : null} tone="orange" hint="drop from this far and it reaches the fire" />
            <Metric label="Fall time" parts={computed.fall_time_s !== undefined ? { value: computed.fall_time_s, unit: "s", digits: 2 } : null} hint={`from ${fmt(computed.hover_altitude_agl_m, 0)} m up`} />
            {computed.elevation_kind === "absolute" ? (
              <Metric
                label="Ground elevation"
                parts={computed.ground_elevation_m != null ? { value: computed.ground_elevation_m, unit: "m", digits: 1 } : null}
                hint={computed.drone_absolute_altitude_m !== undefined ? `drone at ${fmt(computed.drone_absolute_altitude_m, 1)} m` : undefined}
              />
            ) : (
              <Metric
                label="Target height"
                parts={computed.target_elevation_m !== undefined ? { value: computed.target_elevation_m, unit: "m", digits: 1 } : null}
                hint="surface height above local ground"
              />
            )}
            <Metric label="Local slope" parts={computed.slope_deg != null ? { value: computed.slope_deg, unit: "°", digits: 1 } : null} hint={computed.land_cover ? `on ${titleCase(computed.land_cover).toLowerCase()}` : undefined} tone="aurora" />
          </MetricGrid>

          <DropDiagram hover={computed.hover_altitude_agl_m ?? hover} reach={computed.horizontal_reach_m ?? 0} />

          {computed.assumptions && (
            <p className="text-[0.7rem] leading-snug text-slate-ice">
              Assumes {computed.assumptions.caveats.join(", ")}. g = {computed.assumptions.g} m/s².
            </p>
          )}
        </>
      )}

      <Button
        variant="ghost"
        className="w-full"
        disabled={!computed}
        onClick={() =>
          computed &&
          void record(
            "wildfire",
            "Wildfire drone drop",
            `A drone hovering ${fmt(computed.hover_altitude_agl_m, 0)} m above ground releasing water at ${fmt(computed.exit_velocity_mps, 1)} m/s reaches ${fmt(computed.horizontal_reach_m, 1)} m horizontally (fall time ${fmt(computed.fall_time_s, 2)} s).`,
            { hover_m: computed.hover_altitude_agl_m, reach_m: computed.horizontal_reach_m },
          )
        }
      >
        <PlusCircle className="h-4 w-4" strokeWidth={1.5} /> Add to findings
      </Button>
    </div>
  );
}

/** Schematic side view; only the drone height and the reach are to scale relative to each other. */
function DropDiagram({ hover, reach }: { hover: number; reach: number }) {
  const width = 360;
  const height = 150;
  const ground = height - 24;
  const droneX = 44;
  const targetX = width - 36;
  const scaleY = Math.min(1, (ground - 24) / Math.max(hover, 1));
  const droneY = ground - hover * scaleY;
  const arc = `M ${droneX} ${droneY} Q ${droneX + (targetX - droneX) * 0.62} ${droneY} ${targetX} ${ground}`;
  return (
    <div className="card p-3">
      <svg viewBox={`0 0 ${width} ${height}`} className="w-full" role="img" aria-label="Side view of the drone water drop">
        <line x1={0} y1={ground} x2={width} y2={ground} stroke="#8a7b66" strokeWidth={1.5} />
        <line x1={droneX} y1={droneY} x2={droneX} y2={ground} stroke="#8a7b66" strokeWidth={1} strokeDasharray="4 4" />
        <path d={arc} fill="none" stroke="#3f7fbf" strokeWidth={2.5} strokeLinecap="round" />
        <circle cx={droneX} cy={droneY} r={7} fill="#3c5a33" />
        <circle cx={targetX} cy={ground} r={6} fill="#e61a1a" />
        <text x={droneX + 10} y={droneY - 8} fontSize={10} fill="#6b6553">Drone</text>
        <text x={targetX} y={ground + 15} textAnchor="middle" fontSize={10} fill="#6b6553">Fire</text>
        <text x={droneX - 6} y={(droneY + ground) / 2} textAnchor="end" fontSize={10} fill="#3d3a2f" style={{ fontFamily: "var(--font-mono)" }}>{fmt(hover, 0)} m</text>
        <text x={(droneX + targetX) / 2} y={ground + 15} textAnchor="middle" fontSize={10} fill="#3d3a2f" style={{ fontFamily: "var(--font-mono)" }}>{fmt(reach, 1)} m reach</text>
      </svg>
    </div>
  );
}
