"use client";

import { Plus, Trash2, Upload } from "lucide-react";
import { useRef } from "react";

import { Button, Field, InfoNote, Segmented, Slider, Switch } from "@/components/ui";
import type { Gcp, RunOptions, UploadInfo } from "@/lib/sceneTypes";

export interface OptionsDraft extends RunOptions {
  gsd_text: string;
  sun_az_text: string;
  sun_el_text: string;
  crs_text: string;
  origin_x_text: string;
  origin_y_text: string;
}

export function defaultDraft(): OptionsDraft {
  return {
    dem_source: "auto",
    tta: true,
    ensemble: true,
    tile_size: 1024,
    overlap: 0.25,
    gsd_text: "",
    sun_az_text: "",
    sun_el_text: "",
    crs_text: "",
    origin_x_text: "",
    origin_y_text: "",
  };
}

function num(text: string): number | null {
  const value = Number.parseFloat(text);
  return Number.isFinite(value) ? value : null;
}

export function draftToOptions(draft: OptionsDraft): RunOptions {
  return {
    gsd_m: num(draft.gsd_text),
    crs: draft.crs_text.trim() || null,
    origin_x: num(draft.origin_x_text),
    origin_y: num(draft.origin_y_text),
    sun_azimuth_deg: num(draft.sun_az_text),
    sun_elevation_deg: num(draft.sun_el_text),
    dem_source: draft.dem_source,
    tta: draft.tta,
    ensemble: draft.ensemble,
    tile_size: draft.tile_size,
    overlap: draft.overlap,
  };
}

export function OptionsForm({
  info,
  draft,
  onChange,
  gcps,
  onGcps,
  onGcpCsv,
}: {
  info: UploadInfo;
  draft: OptionsDraft;
  onChange: (draft: OptionsDraft) => void;
  gcps: Gcp[];
  onGcps: (gcps: Gcp[]) => void;
  onGcpCsv: (file: File) => void;
}) {
  const csv = useRef<HTMLInputElement>(null);
  const set = <K extends keyof OptionsDraft>(key: K, value: OptionsDraft[K]) => onChange({ ...draft, [key]: value });
  const georef = info.is_georeferenced;

  return (
    <div className="space-y-6">
      <div className="card p-5">
        <p className="eyebrow">Scene overrides</p>
        <p className="mt-1 text-sm text-slate-ice">Leave blank to use what was detected. Overrides win over file metadata.</p>
        <div className="mt-4 grid gap-4 sm:grid-cols-3">
          <Field label="GSD (m / pixel)" hint={info.gsd_m ? `Detected ${info.gsd_m.toFixed(3)}` : "Unknown, so ~0.5 m/px is assumed. Enter the real value for accurate building heights"}>
            <input className="ctl mono" inputMode="decimal" placeholder={info.gsd_m ? String(info.gsd_m) : "e.g. 0.5"} value={draft.gsd_text} onChange={(e) => set("gsd_text", e.target.value)} />
          </Field>
          <Field label="Sun azimuth (°)" hint={info.sun_azimuth_deg !== null ? `Detected ${info.sun_azimuth_deg.toFixed(1)}°` : "Estimated from shadows if blank"}>
            <input className="ctl mono" inputMode="decimal" placeholder="0 – 360" value={draft.sun_az_text} onChange={(e) => set("sun_az_text", e.target.value)} />
          </Field>
          <Field label="Sun elevation (°)" hint={info.sun_elevation_deg !== null ? `Detected ${info.sun_elevation_deg.toFixed(1)}°` : "Needed for the shadow cross-check"}>
            <input className="ctl mono" inputMode="decimal" placeholder="1 – 90" value={draft.sun_el_text} onChange={(e) => set("sun_el_text", e.target.value)} />
          </Field>
        </div>
        {!georef && (
          <details className="mt-4 rounded-lg border border-glacier-300/70 bg-white/50 px-4 py-3">
            <summary className="cursor-pointer text-sm font-semibold text-deep-ice">Georeference a plain image (CRS, GSD and origin)</summary>
            <div className="mt-4 grid gap-4 sm:grid-cols-3">
              <Field label="CRS" hint="EPSG code, e.g. EPSG:32643">
                <input className="ctl mono" placeholder="EPSG:32643" value={draft.crs_text} onChange={(e) => set("crs_text", e.target.value)} />
              </Field>
              <Field label="Origin X (upper-left)">
                <input className="ctl mono" inputMode="decimal" value={draft.origin_x_text} onChange={(e) => set("origin_x_text", e.target.value)} />
              </Field>
              <Field label="Origin Y (upper-left)">
                <input className="ctl mono" inputMode="decimal" value={draft.origin_y_text} onChange={(e) => set("origin_y_text", e.target.value)} />
              </Field>
            </div>
            <p className="mt-3 text-xs text-slate-ice">Needs a GSD above. With all four set, the image is treated as georeferenced (absolute mode).</p>
          </details>
        )}
      </div>

      <div className="card p-5">
        <p className="eyebrow">Processing</p>
        <div className="mt-4 grid gap-4 md:grid-cols-2">
          <div>
            <span className="mb-1.5 block text-xs font-semibold text-deep-ice">DEM source</span>
            <Segmented
              value={draft.dem_source}
              onChange={(value) => set("dem_source", value)}
              options={[
                { value: "auto", label: "Auto (SRTM)" },
                { value: "local", label: "Local only" },
                { value: "none", label: "None" },
              ]}
            />
            <p className="mt-2 text-xs leading-snug text-slate-ice">
              {georef
                ? "Terrain comes from a 30 m DEM (SRTM). Auto downloads the tile once and caches it; Local uses only tiles already on disk."
                : "Only used for georeferenced input."}
            </p>
          </div>
          <div className="space-y-3">
            <Switch checked={draft.tta} onChange={(v) => set("tta", v)} label="Test-time augmentation (8 views)" hint="Averages flips and rotations for accuracy and gives the per-pixel uncertainty map." />
            <Switch checked={draft.ensemble} onChange={(v) => set("ensemble", v)} label="Depth Pro edge ensemble" hint="Optional sharp-edge guide. Needs several GB of GPU memory; skipped automatically if unavailable." />
          </div>
          <Slider label="Tile size" value={draft.tile_size} min={512} max={1024} step={256} onChange={(v) => set("tile_size", v)} format={(v) => `${v} px`} />
          <Slider label="Tile overlap" value={draft.overlap} min={0.2} max={0.4} step={0.05} onChange={(v) => set("overlap", v)} format={(v) => `${Math.round(v * 100)}%`} />
        </div>
      </div>

      <div className="card p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="eyebrow">Ground control points (optional)</p>
            <p className="mt-1 text-sm text-slate-ice">
              Points with a known elevation refine the scale (10× weight). Give pixel col/row, or map x/y in the scene CRS.
            </p>
          </div>
          <div className="flex gap-2">
            <input ref={csv} type="file" accept=".csv,text/csv" hidden onChange={(e) => e.target.files?.[0] && onGcpCsv(e.target.files[0])} />
            <Button variant="ghost" size="sm" onClick={() => csv.current?.click()}>
              <Upload className="h-4 w-4" strokeWidth={1.5} /> CSV
            </Button>
            <Button variant="soft" size="sm" onClick={() => onGcps([...gcps, { label: `GCP ${gcps.length + 1}`, elevation_m: 0, col: 0, row: 0 }])}>
              <Plus className="h-4 w-4" strokeWidth={1.5} /> Add point
            </Button>
          </div>
        </div>
        {gcps.length > 0 ? (
          <div className="mt-4 space-y-2">
            {gcps.map((gcp, index) => (
              <div key={index} className="grid grid-cols-[1.3fr_repeat(3,1fr)_auto] items-center gap-2">
                <input className="ctl" value={gcp.label} onChange={(e) => onGcps(gcps.map((g, i) => (i === index ? { ...g, label: e.target.value } : g)))} aria-label="Label" />
                <input className="ctl mono" inputMode="decimal" value={gcp.col ?? ""} placeholder="col" aria-label="Column" onChange={(e) => onGcps(gcps.map((g, i) => (i === index ? { ...g, col: num(e.target.value) } : g)))} />
                <input className="ctl mono" inputMode="decimal" value={gcp.row ?? ""} placeholder="row" aria-label="Row" onChange={(e) => onGcps(gcps.map((g, i) => (i === index ? { ...g, row: num(e.target.value) } : g)))} />
                <input className="ctl mono" inputMode="decimal" value={gcp.elevation_m} placeholder="elev m" aria-label="Elevation" onChange={(e) => onGcps(gcps.map((g, i) => (i === index ? { ...g, elevation_m: num(e.target.value) ?? 0 } : g)))} />
                <button className="btn btn-ghost btn-sm" aria-label="Remove point" onClick={() => onGcps(gcps.filter((_, i) => i !== index))}>
                  <Trash2 className="h-4 w-4" strokeWidth={1.5} />
                </button>
              </div>
            ))}
          </div>
        ) : (
          <InfoNote className="mt-4">
            No control points: the scale then comes from the DEM, the shadow geometry and (for the fine-tuned network) its native output scale. CSV columns:{" "}
            <span className="mono">label, elevation_m, col, row</span> (or <span className="mono">x, y</span> / <span className="mono">lon, lat</span>).
          </InfoNote>
        )}
      </div>
    </div>
  );
}
