"use client";

import { Crosshair, Loader2 } from "lucide-react";

import { Stat } from "@/components/ui";
import type { UnitValue } from "@/lib/format";
import type { SceneMetadata, SceneSummary } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

/** What every scenario panel receives from the lab. */
export interface ScenarioCtx {
  id: string;
  metadata: SceneMetadata;
  summary: SceneSummary;
  /** Send a command to the Unity viewer (water, pin, explosion, fire, drop, landing, focus). */
  send: (command: Record<string, unknown>) => void;
  /** Image pixel -> the viewer's position fractions (u east, v north). */
  uv: (col: number, row: number) => { u: number; v: number };
  /** Metres measured on the analysis grid -> metres in the viewer's world (they agree unless the scene was re-scaled). */
  toViewerM: (metres: number) => number;
  /** Wait for the next click on the 3D terrain and hand its image pixel position to `onPick`. */
  startPick: (onPick: (col: number, row: number) => void) => void;
  cancelPick: () => void;
  picking: boolean;
  /** Save a one-line result to the findings list the AI brief reads. */
  record: (tool: string, title: string, text: string, data: Record<string, unknown>) => Promise<void>;
}

/** Metric tile whose unit was chosen for the magnitude (see areaParts / distanceParts / volumeParts). */
export function Metric({
  label,
  parts,
  hint,
  tone,
  className,
}: {
  label: string;
  parts: UnitValue | null;
  hint?: string;
  tone?: "default" | "orange" | "aurora" | "krill";
  className?: string;
}) {
  return <Stat label={label} value={parts?.value ?? null} unit={parts?.unit} digits={parts?.digits ?? 0} hint={hint} tone={tone} className={cn("!p-3.5", className)} />;
}

export function MetricGrid({ children, cols = 2 }: { children: React.ReactNode; cols?: 2 | 3 }) {
  return <div className={cn("grid gap-3", cols === 3 ? "grid-cols-3" : "grid-cols-2")}>{children}</div>;
}

export function PanelTitle({ eyebrow, title, text }: { eyebrow: string; title: string; text: string }) {
  return (
    <div>
      <p className="eyebrow">{eyebrow}</p>
      <h3 className="mt-1 text-lg font-semibold text-polar-night">{title}</h3>
      <p className="mt-1 text-[0.82rem] leading-relaxed text-slate-ice">{text}</p>
    </div>
  );
}

/** Numbered progress through a scenario: done steps are filled, the current one is highlighted. */
export function Steps({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
      {steps.map((label, index) => {
        const done = index < current;
        const active = index === current;
        return (
          <li key={label} className="flex items-center gap-1.5">
            <span
              className={cn(
                "flex h-5 w-5 items-center justify-center rounded-full text-[0.65rem] font-semibold",
                done && "bg-aurora text-white",
                active && "bg-station-orange text-white",
                !done && !active && "bg-glacier-100 text-slate-ice",
              )}
            >
              {index + 1}
            </span>
            <span className={cn("text-xs font-semibold", active ? "text-polar-night" : "text-slate-ice")}>{label}</span>
            {index < steps.length - 1 && <span className="mx-1 h-px w-4 bg-glacier-300" />}
          </li>
        );
      })}
    </ol>
  );
}

/** Button that arms "click a point on the 3D terrain". */
export function PickButton({ ctx, label, onPick, done }: { ctx: ScenarioCtx; label: string; onPick: (col: number, row: number) => void; done?: boolean }) {
  return (
    <button
      type="button"
      onClick={() => (ctx.picking ? ctx.cancelPick() : ctx.startPick(onPick))}
      className={cn(
        "flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-semibold transition-colors",
        ctx.picking ? "border-station-orange bg-station-orange text-white" : "border-glacier-300 bg-white/60 text-deep-ice hover:border-station-orange/60",
      )}
    >
      {ctx.picking ? <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} /> : <Crosshair className="h-4 w-4" strokeWidth={1.75} />}
      {ctx.picking ? "Click the 3D terrain…" : done ? `Re-pick: ${label}` : label}
    </button>
  );
}

export function errorText(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}
