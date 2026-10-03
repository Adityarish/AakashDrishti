"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, MapPin, X } from "lucide-react";

import { Histogram, LandCoverBars } from "@/components/charts";
import { MapView } from "@/components/survey/MapView";
import { useSurvey } from "@/components/survey/SurveyContext";
import { Badge, InfoNote, Reveal, Segmented, Slider, Stat } from "@/components/ui";
import { detectedObjects, jobFileUrl, probe, type DetectedObjects } from "@/lib/api/survey";
import { fmt, fmtLonLat, titleCase } from "@/lib/format";
import { loadField, sample, type Field } from "@/lib/heightField";
import type { ProbeResult } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

const LAYERS = [
  { key: "optical", label: "Optical", file: "ortho.jpg", swatch: "linear-gradient(135deg,#6b7f5a,#b9a888)" },
  { key: "height", label: "Height", file: "height_color.png", swatch: "linear-gradient(90deg,#0b2545,#1f5f8b,#5b9bc8,#a9cde6,#fff,#f7d9b5)" },
  { key: "hillshade", label: "Hillshade", file: "hillshade.png", swatch: "linear-gradient(135deg,#f2f2f2,#7a7a7a)" },
  { key: "slope", label: "Slope", file: "slope_color.png", swatch: "linear-gradient(90deg,#f2c94c,#e4574b)" },
  { key: "uncertainty", label: "Uncertainty", file: "uncertainty_color.png", swatch: "linear-gradient(90deg,#fafcfe,#f26b21)" },
  { key: "landcover", label: "Land cover", file: "landcover.png", swatch: "linear-gradient(90deg,#b0a692,#8cc878,#e7604e,#4682c8,#6e7682,#1e7846)" },
] as const;

type LayerKey = (typeof LAYERS)[number]["key"];

/** Each map marker is a DOM node, so a dense urban scene's full detection list is capped here. */
const OBJECT_MARKER_CAP = 400;

interface BuildingRow {
  id: number;
  height_m: number | null;
}

export default function Workspace() {
  const { id, metadata, manifest, summary } = useSurvey();
  const [layer, setLayer] = useState<LayerKey>("height");
  const [mode, setMode] = useState<"blend" | "swipe">("swipe");
  const [opacity, setOpacity] = useState(0.7);
  const [fields, setFields] = useState<{ dsm: Field; ndsm: Field; unc: Field } | null>(null);
  const [hover, setHover] = useState<{ col: number; row: number; x: number; y: number } | null>(null);
  const [pinned, setPinned] = useState<ProbeResult | null>(null);
  const [buildings, setBuildings] = useState<BuildingRow[]>([]);
  const [objects, setObjects] = useState<DetectedObjects | null>(null);
  const [showObjects, setShowObjects] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);

  const metric = metadata.dsm_is_metric;
  const unit = metric ? "m" : "";
  const layerFile = LAYERS.find((l) => l.key === layer)!.file;
  const layerUrl = jobFileUrl(id, layerFile);
  const baseUrl = jobFileUrl(id, "ortho.jpg");

  useEffect(() => {
    Promise.all([
      loadField(id, "height.f32", metadata.width, metadata.height),
      loadField(id, "ndsm.f32", metadata.width, metadata.height),
      loadField(id, "uncertainty.f32", metadata.width, metadata.height),
    ])
      .then(([dsm, ndsm, unc]) => setFields({ dsm, ndsm, unc }))
      .catch(() => setFields(null));
    fetch(jobFileUrl(id, "buildings.json"))
      .then((r) => r.json())
      .then((d: { buildings: BuildingRow[] }) => setBuildings(d.buildings))
      .catch(() => setBuildings([]));
    detectedObjects(id, OBJECT_MARKER_CAP)
      .then(setObjects)
      .catch(() => setObjects(null));
  }, [id, metadata.width, metadata.height]);

  // One DOM marker per object, so the map stays responsive on a scene with hundreds of vehicles.
  const objectMarkers = useMemo(
    () =>
      !showObjects || !objects
        ? []
        : objects.objects.slice(0, OBJECT_MARKER_CAP).map((o) => ({
            col: o.center_px[0],
            row: o.center_px[1],
            tone: (o.label.includes("vehicle") ? "aurora" : "krill") as "aurora" | "krill",
            radiusPx: 3,
          })),
    [showObjects, objects],
  );

  const readout = useMemo(() => {
    if (!hover || !fields) return null;
    return {
      elevation: sample(fields.dsm, hover.col, hover.row),
      above: sample(fields.ndsm, hover.col, hover.row),
      unc: sample(fields.unc, hover.col, hover.row),
    };
  }, [hover, fields]);

  const classData = Object.entries(metadata.land_cover_fractions)
    .filter(([, value]) => value > 0.002)
    .sort((a, b) => b[1] - a[1])
    .map(([name, value]) => ({ name: titleCase(name), value: value * 100 }));

  const bins = useMemo(() => {
    const values = buildings.map((b) => b.height_m).filter((v): v is number => v !== null && Number.isFinite(v));
    if (values.length < 3) return null;
    const max = Math.max(...values);
    const count = 12;
    const width = max / count || 1;
    const counts = Array.from({ length: count }, (_, i) => ({ label: `${Math.round(i * width)}`, count: 0 }));
    for (const v of values) counts[Math.min(count - 1, Math.floor(v / width))].count += 1;
    return { counts, tallest: [...buildings].filter((b) => b.height_m !== null).sort((a, b) => (b.height_m ?? 0) - (a.height_m ?? 0)).slice(0, 5) };
  }, [buildings]);

  async function pin(col: number, row: number) {
    try {
      setPinned(await probe(id, col, row));
    } catch {
      setPinned(null);
    }
  }

  const source = metadata.calibration_sources;
  const totalWeight = source.reduce((sum, s) => sum + s.weight, 0) || 1;

  return (
    <div className="mx-auto grid w-full max-w-[1500px] flex-1 gap-5 px-5 py-6 sm:px-8 xl:grid-cols-[15rem_minmax(0,1fr)_22rem]">
      {/* ---------------- layers ---------------- */}
      <Reveal className="space-y-4">
        <div className="card p-4">
          <p className="eyebrow">Layers</p>
          <div className="mt-3 space-y-1.5">
            {LAYERS.map((item) => (
              <button
                key={item.key}
                onClick={() => setLayer(item.key)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left text-sm font-semibold transition-all",
                  layer === item.key ? "border-station-orange bg-white text-polar-night shadow-sm" : "border-transparent text-slate-ice hover:bg-glacier-100",
                )}
              >
                <span className="h-5 w-9 shrink-0 rounded-md border border-white shadow-sm" style={{ background: item.swatch }} />
                {item.label}
              </button>
            ))}
          </div>
          <div className="ice-divider my-4" />
          <p className="eyebrow">Compare</p>
          <Segmented className="mt-2 w-full" value={mode} onChange={setMode} options={[{ value: "swipe", label: "Swipe" }, { value: "blend", label: "Blend" }]} />
          {mode === "blend" && <div className="mt-4"><Slider label="Opacity" value={opacity} min={0.1} max={1} step={0.05} onChange={setOpacity} format={(v) => `${Math.round(v * 100)}%`} /></div>}
          {layer === "optical" && <p className="mt-3 text-xs text-slate-ice">Pick another layer to compare against the optical image.</p>}
        </div>
        <InfoNote>Scroll to zoom, drag to pan, double-click to fit. Click any point to pin its details.</InfoNote>
      </Reveal>

      {/* ---------------- map ---------------- */}
      <Reveal delay={0.05} className="min-w-0">
        <div ref={wrapper} className="relative h-[68vh] min-h-[460px]">
          <MapView
            className="h-full"
            width={metadata.width}
            height={metadata.height}
            base={baseUrl}
            compare={mode === "swipe" && layer !== "optical" ? layerUrl : null}
            compareLabels={["Optical", LAYERS.find((l) => l.key === layer)!.label]}
            overlays={mode === "blend" && layer !== "optical" ? [{ src: layerUrl, opacity }] : []}
            markers={[...objectMarkers, ...(pinned ? [{ col: pinned.col, row: pinned.row, tone: "orange" as const }] : [])]}
            onHover={(point, event) => {
              if (!point) return setHover(null);
              const rect = wrapper.current!.getBoundingClientRect();
              setHover({ col: point.col, row: point.row, x: event.clientX - rect.left, y: event.clientY - rect.top });
            }}
            onPick={pin}
          />
          {hover && readout && !pinned && (
            <div className="hud pointer-events-none absolute z-20 px-3 py-2" style={{ left: Math.min(hover.x + 16, (wrapper.current?.clientWidth ?? 600) - 190), top: Math.min(hover.y + 16, (wrapper.current?.clientHeight ?? 400) - 96) }}>
              <p className="mono text-[0.7rem] text-slate-ice">px {Math.round(hover.col)}, {Math.round(hover.row)}</p>
              <p className="mono text-sm font-semibold">{fmt(readout.elevation, 1)}{unit} <span className="text-[0.7rem] font-medium text-slate-ice">elevation</span></p>
              <p className="mono text-xs">{fmt(readout.above, 1)}{unit} above ground · ±{fmt(readout.unc, 2)}</p>
            </div>
          )}
          {pinned && (
            <div className="hud absolute bottom-3 left-3 z-20 w-72 p-4">
              <div className="flex items-start justify-between">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-station-orange">
                  <MapPin className="h-3.5 w-3.5" strokeWidth={2} /> Pinned point
                </p>
                <button onClick={() => setPinned(null)} aria-label="Close" className="text-slate-ice hover:text-polar-night">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <dl className="mono mt-2 space-y-1 text-xs">
                <div className="flex justify-between"><dt className="text-slate-ice">Elevation</dt><dd className="font-semibold">{fmt(pinned.elevation, 2)} {unit}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-ice">Above ground</dt><dd className="font-semibold">{fmt(pinned.height_above_ground, 2)} {unit}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-ice">Uncertainty</dt><dd className="font-semibold">±{fmt(pinned.uncertainty, 2)} {unit}</dd></div>
                <div className="flex justify-between"><dt className="text-slate-ice">Slope</dt><dd className="font-semibold">{fmt(pinned.slope_deg, 1)}°</dd></div>
                <div className="flex justify-between"><dt className="text-slate-ice">Surface</dt><dd className="font-semibold">{titleCase(pinned.land_cover)}</dd></div>
                <div className="flex justify-between gap-3"><dt className="text-slate-ice">Position</dt><dd className="text-right font-semibold">{fmtLonLat(pinned.lon, pinned.lat)}</dd></div>
              </dl>
            </div>
          )}
        </div>
      </Reveal>

      {/* ---------------- stats ---------------- */}
      <div className="space-y-4">
        <Reveal delay={0.08}>
          <div className="grid grid-cols-2 gap-3">
            <Stat label="Height range" value={metadata.height_range[1] - metadata.height_range[0]} unit={unit} digits={metric ? 1 : 0} hint={metric ? `${fmt(metadata.height_range[0], 0)} to ${fmt(metadata.height_range[1], 0)} m` : "relative units"} />
            <Stat label="Mean height" value={metadata.mean_height} unit={unit} digits={1} hint="above local ground" />
            <Stat label="Buildings" value={metadata.buildings_count} digits={0} tone="orange" />
            <Stat label="Scene area" value={(metadata.width * metadata.height * summary.pixel_size_m ** 2) / 1e6} unit="km²" digits={3} />
          </div>
        </Reveal>

        <Reveal delay={0.1}>
          <div className="card p-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="eyebrow">Detected objects</p>
                <p className="mt-1 text-xs text-slate-ice">
                  {objects?.status === "ok"
                    ? `${objects.count} found by ${objects.model}, each sampled against this scene's height field.`
                    : objects
                      ? objects.note
                      : "Loading…"}
                </p>
              </div>
              {objects?.status === "ok" && objects.count > 0 && (
                <button
                  type="button"
                  onClick={() => setShowObjects((v) => !v)}
                  className={cn(
                    "shrink-0 rounded-full border px-2.5 py-1 text-[0.7rem] font-semibold transition-colors",
                    showObjects ? "border-station-orange bg-station-orange/10 text-station-orange" : "border-glacier-300/70 text-slate-ice hover:bg-glacier-100",
                  )}
                >
                  {showObjects ? "Hide on map" : "Show on map"}
                </button>
              )}
            </div>
            {objects?.status === "ok" && objects.count > 0 && (
              <>
                <ul className="mt-3 space-y-1.5">
                  {Object.entries(objects.counts_by_class)
                    .sort((a, b) => b[1] - a[1])
                    .slice(0, 6)
                    .map(([name, count]) => (
                      <li key={name} className="flex items-center justify-between text-xs">
                        <span className="flex items-center gap-2 text-polar-night">
                          <span className={cn("h-2 w-2 rounded-full", name.includes("vehicle") ? "bg-aurora" : "bg-krill")} />
                          {titleCase(name)}
                        </span>
                        <span className="mono font-semibold text-deep-ice">{count}</span>
                      </li>
                    ))}
                </ul>
                {objects.count > OBJECT_MARKER_CAP && (
                  <p className="mt-2 text-[0.7rem] text-slate-ice">Map shows the {OBJECT_MARKER_CAP} highest-confidence objects.</p>
                )}
                <p className="mt-2 text-[0.7rem] leading-snug text-slate-ice">
                  Heights are only reported for objects above this single-view model&apos;s metre-scale noise floor — a car sits below it.
                </p>
              </>
            )}
          </div>
        </Reveal>

        <Reveal delay={0.12}>
          <div className="card p-4">
            <p className="eyebrow">Land cover</p>
            <p className="mb-1 mt-1 text-xs text-slate-ice">Heuristic classes from colour and height (no learned segmentation head).</p>
            <LandCoverBars data={classData} />
          </div>
        </Reveal>

        <Reveal delay={0.16}>
          <div className="card p-4">
            <div className="flex items-center justify-between">
              <p className="eyebrow">Calibration</p>
              <Badge tone={metadata.dsm_kind === "relative" ? "muted" : "aurora"}>{metadata.dsm_kind.replace("_", " ")}</Badge>
            </div>
            {source.length > 0 ? (
              <>
                <div className="mono mt-3 flex items-baseline gap-2">
                  <span className="text-2xl font-semibold text-polar-night">s = {metadata.calibration_scale?.toFixed(3)}</span>
                  {metadata.calibration_scale_log_sigma !== null && <span className="text-xs text-slate-ice">σ(log s) {metadata.calibration_scale_log_sigma.toFixed(2)}</span>}
                </div>
                <ul className="mt-3 space-y-2.5">
                  {source.map((s) => (
                    <li key={s.name}>
                      <div className="flex justify-between text-xs">
                        <span className="font-semibold capitalize text-deep-ice">{s.name.replace("_", " ")}</span>
                        <span className="mono text-slate-ice">×{s.scale.toFixed(2)} · w {((s.weight / totalWeight) * 100).toFixed(0)}%</span>
                      </div>
                      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-glacier-100"><div className="h-full rounded-full bg-station-orange" style={{ width: `${(s.weight / totalWeight) * 100}%` }} /></div>
                      <p className="mt-1 text-[0.7rem] leading-snug text-slate-ice">{s.detail}</p>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="mt-3 text-xs leading-relaxed text-slate-ice">{metadata.calibration_note || "No scale evidence: output stays a relative DSM."}</p>
            )}
            {metadata.shadow_summary && <p className="mt-3 text-[0.7rem] leading-snug text-slate-ice"><b className="text-deep-ice">Shadow check:</b> {metadata.shadow_summary}</p>}
          </div>
        </Reveal>

        {bins && (
          <Reveal delay={0.2}>
            <div className="card p-4">
              <p className="eyebrow">Building heights</p>
              <Histogram bins={bins.counts} xLabel={metric ? "height (m)" : "relative height"} color="#a3392c" height={170} />
              <ul className="mono mt-1 space-y-1 text-xs">
                {bins.tallest.map((b) => (
                  <li key={b.id} className="flex justify-between"><span className="text-slate-ice">Building #{b.id}</span><span className="font-semibold">{fmt(b.height_m, 1)}{unit}</span></li>
                ))}
              </ul>
            </div>
          </Reveal>
        )}

        <Reveal delay={0.24}>
          <div className="card p-4">
            <p className="eyebrow">Run</p>
            <dl className="mono mt-2 space-y-1.5 text-xs">
              <div className="flex justify-between"><dt className="text-slate-ice">Tiles × TTA views</dt><dd className="font-semibold">{metadata.tiles} × {metadata.tta_variants}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-ice">Inference</dt><dd className="font-semibold">{fmt(metadata.timings.inference_s, 1)} s</dd></div>
              <div className="flex justify-between"><dt className="text-slate-ice">Throughput</dt><dd className="font-semibold">{fmt(metadata.pixels_per_second / 1000, 0)} kpx/s</dd></div>
              <div className="flex justify-between"><dt className="text-slate-ice">Mean uncertainty</dt><dd className="font-semibold">±{fmt(summary.mean_uncertainty, 2)} {unit}</dd></div>
              <div className="flex justify-between"><dt className="text-slate-ice">Model</dt><dd className="max-w-[10rem] truncate font-semibold" title={metadata.da_v2_checkpoint}>{metadata.da_v2_checkpoint.replace("depth_anything_v2_", "").replace(".pth", "")}</dd></div>
            </dl>
          </div>
        </Reveal>

        <Link href={`/survey/${id}/hazards`} className="btn btn-primary btn-lg w-full">
          Run hazard analysis <ArrowRight className="h-5 w-5" strokeWidth={1.75} />
        </Link>
      </div>
    </div>
  );
}
