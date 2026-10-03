"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Bomb, Flame, Helicopter, Loader2, MousePointerClick, Waves } from "lucide-react";

import { useSurvey } from "@/components/survey/SurveyContext";
import { InfoNote } from "@/components/ui";
import { UnityViewer, type UnityViewerHandle } from "@/components/viewer/UnityViewer";
import { addFinding } from "@/lib/api/survey";
import { cn } from "@/lib/utils";

import { ExplosionScenario } from "./ExplosionScenario";
import { FloodScenario } from "./FloodScenario";
import { LandingScenario } from "./LandingScenario";
import { errorText, type ScenarioCtx } from "./shared";
import { WildfireScenario } from "./WildfireScenario";

const SCENARIOS = [
  { key: "flood", label: "Flood", blurb: "Watch the water rise from the ground and see which buildings it reaches.", icon: Waves },
  { key: "landing", label: "Emergency landing", blurb: "Ranked flat, clear ground, and a drone, helicopter or plane landing on it.", icon: Helicopter },
  { key: "explosion", label: "Explosion impact", blurb: "Pick a point, detonate, and see the blast and the damage rings.", icon: Bomb },
  { key: "wildfire", label: "Wildfire drone drop", blurb: "A fire catches, then a drone flies in and puts it out from a safe distance.", icon: Flame },
] as const;

type ScenarioKey = (typeof SCENARIOS)[number]["key"];

/** The four disaster scenarios, run on the uploaded scene and played out in the Unity 3D viewer. */
export function ScenarioLab() {
  const { id, metadata, summary } = useSurvey();
  const [active, setActive] = useState<ScenarioKey | null>(null);
  const [picking, setPicking] = useState(false);
  const [loading3d, setLoading3d] = useState(false);
  const [saved, setSaved] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const viewer = useRef<UnityViewerHandle>(null);
  const pickHandler = useRef<((col: number, row: number) => void) | null>(null);

  const send = useCallback((command: Record<string, unknown>) => viewer.current?.run(command), []);

  // The viewer's world is metres; the analysis grid has its own metres-per-pixel. They match for scenes made by the
  // current pipeline, and this keeps radii and distances right for older scenes that were scaled differently.
  const viewerMetresPerPixel = metadata.unity_world_size_m ? metadata.unity_world_size_m.x / metadata.width : summary.pixel_size_m;
  const toViewerM = useCallback((metres: number) => (metres * viewerMetresPerPixel) / Math.max(summary.pixel_size_m, 1e-9), [viewerMetresPerPixel, summary.pixel_size_m]);
  const uv = useCallback((col: number, row: number) => ({ u: col / metadata.width, v: 1 - row / metadata.height }), [metadata.width, metadata.height]);

  const startPick = useCallback(
    (handler: (col: number, row: number) => void) => {
      pickHandler.current = handler;
      setPicking(true);
      send({ cmd: "pick", on: true });
    },
    [send],
  );
  const cancelPick = useCallback(() => {
    pickHandler.current = null;
    setPicking(false);
    send({ cmd: "pick", on: false });
  }, [send]);

  const handlePicked = useCallback(
    (u: number, v: number) => {
      const handler = pickHandler.current;
      pickHandler.current = null;
      setPicking(false);
      handler?.(u * metadata.width, (1 - v) * metadata.height);
    },
    [metadata.width, metadata.height],
  );

  const record = useCallback(
    async (tool: string, title: string, text: string, data: Record<string, unknown>) => {
      setSaveError(null);
      try {
        await addFinding(id, { tool, title, text, data });
        setSaved(title);
      } catch (e) {
        setSaved(null);
        setSaveError(errorText(e, "Could not save the finding."));
      }
    },
    [id],
  );

  const ctx: ScenarioCtx = useMemo(
    () => ({ id, metadata, summary, send, uv, toViewerM, startPick, cancelPick, picking, record }),
    [id, metadata, summary, send, uv, toViewerM, startPick, cancelPick, picking, record],
  );

  // leaving a scenario clears whatever it left on the terrain
  useEffect(() => () => viewer.current?.run({ cmd: "clear" }), []);

  function choose(key: ScenarioKey) {
    if (key === active) return;
    cancelPick();
    send({ cmd: "clear" });
    setSaved(null);
    setActive(key);
  }

  return (
    <div className="mx-auto w-full max-w-[1920px] flex-1 space-y-4 px-4 pb-6 sm:px-6">
      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4">
        {SCENARIOS.map((item) => (
          <button
            key={item.key}
            type="button"
            onClick={() => choose(item.key)}
            aria-pressed={active === item.key}
            className={cn(
              "card card-lift flex items-center gap-3 p-3 text-left",
              active === item.key && "border-station-orange shadow-[0_0_0_3px_rgba(242,107,33,0.15)]",
            )}
          >
            <span className={cn("flex h-10 w-10 shrink-0 items-center justify-center rounded-lg", active === item.key ? "bg-station-orange text-white" : "bg-glacier-100 text-deep-ice")}>
              <item.icon className="h-6 w-6" strokeWidth={1.5} />
            </span>
            <span className="min-w-0">
              <span className="block text-[0.95rem] font-semibold text-polar-night">{item.label}</span>
              <span className="mt-0.5 hidden text-xs leading-snug text-slate-ice 2xl:block">{item.blurb}</span>
            </span>
          </button>
        ))}
      </div>

      {metadata.gsd_assumed && (
        <InfoNote>
          This image has no pixel size, so the pipeline assumed {metadata.pixel_size_m.toFixed(2)} m per pixel. Areas, distances and heights below are approximate; run it again from Advanced Run with the real GSD for true values.
        </InfoNote>
      )}

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_24rem]">
        {/* ---------------- Unity 3D view ---------------- */}
        <div className="min-w-0 space-y-3 xl:sticky xl:top-32 xl:self-start">
          <div className="flex flex-wrap items-center gap-2">
            <p className="eyebrow">Unity 3D view</p>
            {loading3d && (
              <span className="flex items-center gap-1.5 text-xs text-slate-ice">
                <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} /> Loading 3D scene…
              </span>
            )}
          </div>
          {picking && (
            <div className="flex items-center gap-2 rounded-lg border border-station-orange/40 bg-station-orange/10 px-3.5 py-2 text-sm font-semibold text-deep-ice">
              <MousePointerClick className="h-4 w-4" strokeWidth={1.75} /> Click a point on the 3D terrain to place it.
            </div>
          )}
          <UnityViewer ref={viewer} key={id} jobId={id} frameClassName="h-[calc(100vh-15rem)] min-h-[560px]" onLoading={setLoading3d} onPicked={handlePicked} />
        </div>

        {/* ---------------- scenario panel ---------------- */}
        <div className="min-w-0 space-y-4">
          {saved && <InfoNote>Added “{saved}” to the findings. The AI brief will include it.</InfoNote>}
          {saveError && <InfoNote className="!border-krill/30 !bg-krill/5 !text-krill">{saveError}</InfoNote>}

          {active === null && (
            <div className="card contour-bg relative overflow-hidden px-6 py-14 text-center">
              <div className="absolute inset-0 bg-gradient-to-b from-frost/70 to-frost" />
              <div className="relative mx-auto max-w-xs">
                <span className="mx-auto flex h-12 w-12 items-center justify-center rounded-lg bg-glacier-100 text-deep-ice">
                  <MousePointerClick className="h-6 w-6" strokeWidth={1.5} />
                </span>
                <h3 className="mt-4 text-lg font-semibold text-polar-night">Pick a scenario</h3>
                <p className="mt-2 text-sm leading-relaxed text-slate-ice">Choose one of the four above. It runs on your uploaded image and plays out on the 3D terrain.</p>
              </div>
            </div>
          )}
          {active === "flood" && <FloodScenario key="flood" ctx={ctx} />}
          {active === "landing" && <LandingScenario key="landing" ctx={ctx} />}
          {active === "explosion" && <ExplosionScenario key="explosion" ctx={ctx} />}
          {active === "wildfire" && <WildfireScenario key="wildfire" ctx={ctx} />}
        </div>
      </div>
    </div>
  );
}
