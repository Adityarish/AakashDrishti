"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BadgeCheck, FileUp, FlaskConical } from "lucide-react";

import { GroupedBars, Histogram, ScatterPlot } from "@/components/charts";
import { MapView } from "@/components/survey/MapView";
import { SelfCheckPanel } from "@/components/survey/SelfCheckPanel";
import { kindLabel, useSurvey } from "@/components/survey/SurveyContext";
import { Badge, Button, ErrorNote, InfoNote, ProgressBar, Reveal, Segmented, Stat } from "@/components/ui";
import { benchmarks, getValidation, jobFileUrl, outputUrl, uploadReference, applySampleReference } from "@/lib/api/survey";
import { loadField, sample, type Field } from "@/lib/heightField";
import { fmt, titleCase } from "@/lib/format";
import type { BenchmarkTable, Metrics, ValidationLab } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

const LANDSCAPES = ["urban", "sparse", "hilly", "forested"] as const;

function MetricRow({ label, m, note }: { label: string; m?: Metrics; note?: string }) {
  return (
    <tr className="border-t border-glacier-300/40">
      <td className="px-4 py-3 text-sm font-semibold text-polar-night">
        {label}
        {note && <span className="ml-2 text-xs font-medium text-slate-ice">{note}</span>}
      </td>
      {m && m.rmse !== undefined ? (
        <>
          <td className="mono px-4 py-3 text-right text-sm font-semibold">{fmt(m.rmse, 2)}</td>
          <td className="mono px-4 py-3 text-right text-sm">{fmt(m.mae, 2)}</td>
          <td className="mono px-4 py-3 text-right text-sm">{m.pearson_r !== null && m.pearson_r !== undefined ? fmt(m.pearson_r, 2) : "n/a"}</td>
          <td className="mono px-4 py-3 text-right text-xs text-slate-ice">{m.n.toLocaleString()}</td>
        </>
      ) : (
        <td colSpan={4} className="px-4 py-3 text-right text-xs italic text-slate-ice">not present in this scene</td>
      )}
    </tr>
  );
}

function MetricsTable({ title, rows }: { title: string; rows: { label: string; m?: Metrics; note?: string }[] }) {
  return (
    <div className="card overflow-hidden">
      <p className="eyebrow px-4 pt-4">{title}</p>
      <table className="mt-2 w-full">
        <thead>
          <tr className="text-[0.66rem] font-semibold uppercase tracking-wider text-slate-ice">
            <th className="px-4 pb-2 text-left">Group</th>
            <th className="px-4 pb-2 text-right">RMSE</th>
            <th className="px-4 pb-2 text-right">MAE</th>
            <th className="px-4 pb-2 text-right">r</th>
            <th className="px-4 pb-2 text-right">pixels</th>
          </tr>
        </thead>
        <tbody>{rows.map((r) => <MetricRow key={r.label} {...r} />)}</tbody>
      </table>
    </div>
  );
}

function ErrorMapPanel({ id, width, height, lab, fields, unit }: { id: string; width: number; height: number; lab: ValidationLab; fields: { pred: Field; ref: Field } | null; unit: string }) {
  const [view, setView] = useState<"pred" | "ref" | "error">("pred");
  const [hover, setHover] = useState<{ col: number; row: number; x: number; y: number } | null>(null);
  const mapBox = useRef<HTMLDivElement>(null);
  const frame = useRef(0);

  // Hover state lives here (not in the page) so moving the mouse only re-renders this panel, not the charts,
  // and updates are coalesced to one per animation frame.
  const handleHover = useCallback((point: { col: number; row: number } | null, event: React.PointerEvent) => {
    cancelAnimationFrame(frame.current);
    if (!point) return setHover(null);
    const { clientX, clientY } = event;
    frame.current = requestAnimationFrame(() => {
      const rect = mapBox.current?.getBoundingClientRect();
      if (rect) setHover({ col: point.col, row: point.row, x: Math.min(clientX - rect.left + 16, rect.width - 200), y: Math.min(clientY - rect.top + 16, rect.height - 100) });
    });
  }, []);
  useEffect(() => () => cancelAnimationFrame(frame.current), []);

  const readout = useMemo(() => {
    if (!hover || !fields) return null;
    const pred = sample(fields.pred, hover.col, hover.row);
    const ref = sample(fields.ref, hover.col, hover.row);
    if (!Number.isFinite(pred) || !Number.isFinite(ref)) return null;
    return { pred, ref, err: pred - ref };
  }, [hover, fields]);

  const compareUrl = lab.image_urls
    ? `${outputUrl(lab.image_urls[view === "pred" ? "compare_pred" : view === "ref" ? "compare_reference" : "error_map"])}?v=${encodeURIComponent(lab.reference_name ?? "")}`
    : null;

  return (
    <div className="card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Live error map</p>
          <p className="mt-1 text-sm text-slate-ice">Drag the divider to reveal the predicted height, the reference height or the diverging error map over the real optical image. The same error map can be draped on the 3D mesh.</p>
        </div>
        <Segmented value={view} onChange={setView} options={[{ value: "pred", label: "Optical vs Predicted" }, { value: "ref", label: "Optical vs Reference" }, { value: "error", label: "Optical vs Error" }]} />
      </div>
      <div ref={mapBox} className="relative h-[520px]">
        {compareUrl && (
          <MapView
            className="h-full"
            width={width}
            height={height}
            base={jobFileUrl(id, "ortho.jpg")}
            compare={compareUrl}
            compareLabels={["Optical", view === "pred" ? "Predicted" : view === "ref" ? "Reference" : "Error"]}
            onHover={handleHover}
          />
        )}
        {hover && readout && (
          <div className="hud pointer-events-none absolute z-20 px-3 py-2" style={{ left: hover.x, top: hover.y }}>
            <p className="mono text-[0.7rem] text-slate-ice">px {Math.round(hover.col)}, {Math.round(hover.row)}</p>
            <p className="mono text-sm font-semibold">{fmt(readout.pred, 1)}{unit} <span className="text-[0.7rem] font-medium text-slate-ice">predicted</span></p>
            <p className="mono text-xs">{fmt(readout.ref, 1)}{unit} reference · {readout.err >= 0 ? "+" : ""}{fmt(readout.err, 2)} error</p>
          </div>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3 text-xs text-slate-ice">
        <span className="font-semibold text-deep-ice">Under-predicted</span>
        <span className="h-2 flex-1 rounded-full" style={{ background: "linear-gradient(90deg,#3c5a33,#fbf6e7,#a3392c)" }} />
        <span className="font-semibold text-krill">Over-predicted</span>
        <span className="mono">±{fmt(lab.error_scale_m, 1)} {unit} (95th pct)</span>
      </div>
    </div>
  );
}

export default function ValidationLabPage() {
  const { id, metadata, job } = useSurvey();
  const [lab, setLab] = useState<ValidationLab | null>(null);
  const [bench, setBench] = useState<BenchmarkTable | null>(null);
  const [kind, setKind] = useState<"auto" | "dsm" | "ndsm">("auto");
  const [progress, setProgress] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const [fields, setFields] = useState<{ pred: Field; ref: Field } | null>(null);
  const unit = metadata.dsm_is_metric ? "m" : "rel";

  const refresh = useCallback(async () => {
    try {
      setLab(await getValidation(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load validation results.");
    }
  }, [id]);

  useEffect(() => {
    void refresh();
    benchmarks().then(setBench).catch(() => setBench(null));
  }, [refresh]);

  async function submit(file: File) {
    setBusy(true);
    setError(null);
    setProgress(0);
    try {
      setLab(await uploadReference(id, file, kind, setProgress));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not score that file.");
    } finally {
      setBusy(false);
      setProgress(null);
    }
  }

  async function bundled() {
    setBusy(true);
    setError(null);
    try {
      setLab(await applySampleReference(id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not use the bundled reference.");
    } finally {
      setBusy(false);
    }
  }

  const labStamp = lab?.reference_name;
  useEffect(() => {
    setFields(null);
    if (lab?.status !== "ok") return;
    Promise.all([
      loadField(id, `lab_pred.f32?v=${encodeURIComponent(labStamp ?? "")}`, metadata.width, metadata.height),
      loadField(id, `lab_reference.f32?v=${encodeURIComponent(labStamp ?? "")}`, metadata.width, metadata.height),
    ])
      .then(([pred, ref]) => setFields({ pred, ref }))
      .catch(() => setFields(null));
  }, [id, lab?.status, labStamp, metadata.width, metadata.height]);

  const scored = lab?.status === "ok" && lab.global;
  const g = lab?.global;
  const errorBins = lab?.error_histogram
    ? lab.error_histogram.counts.map((count, i) => ({ label: fmt((lab.error_histogram!.edges[i] + lab.error_histogram!.edges[i + 1]) / 2, 1), count }))
    : [];

  const chartRows = (bench?.rows ?? [])
    .filter((row) => row.measured && row.overall)
    .map((row) => ({
      name: row.label.replace("Zero-shot DA-V2 + per-tile affine", "Zero-shot").replace("Fine-tuned + per-tile affine", "Fine-tuned (fit)").replace("Fine-tuned, production formula", "Production"),
      Urban: row.urban?.rmse ?? null,
      Sparse: row.sparse?.rmse ?? null,
      Forest: row.forested?.rmse ?? null,
      Mixed: row.mixed?.rmse ?? null,
    }));

  return (
    <div className="mx-auto w-full max-w-[1500px] flex-1 space-y-7 px-5 py-8 sm:px-8">
      <div className="max-w-3xl">
        <p className="eyebrow">Validation lab</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-polar-night">How far can you trust this height map?</h1>
        <p className="mt-2 text-[0.95rem] leading-relaxed text-slate-ice">
          Your image is already loaded, so there is nothing to upload for a first check: the automatic self-check below runs on this scene straight away.
          For a true accuracy score, add reference elevation data further down.
        </p>
      </div>

      <Reveal>
        <div className="card flex flex-wrap items-center gap-4 p-3 pr-5">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={jobFileUrl(id, "thumb.jpg")} alt="The image being validated" className="h-20 w-28 rounded-md border border-glacier-300/60 object-cover" />
          <div className="min-w-0 flex-1">
            <p className="eyebrow">Scene under test</p>
            <p className="truncate text-base font-semibold text-polar-night" title={job.source_filename ?? undefined}>{job.source_filename ?? "Uploaded image"}</p>
            <p className="mono text-xs text-slate-ice">{metadata.width}×{metadata.height} px · {metadata.dsm_is_metric ? `${fmt(metadata.pixel_size_m, 2)} m/px${metadata.gsd_assumed ? " (assumed)" : ""}` : "no scale"}</p>
          </div>
          <Badge tone={kindLabel(metadata.dsm_kind).tone}>{kindLabel(metadata.dsm_kind).text}</Badge>
        </div>
      </Reveal>

      <Reveal>
        <div className="space-y-3">
          <div>
            <p className="eyebrow">Step 1 · Automatic self-check</p>
            <p className="mt-1 text-sm text-slate-ice">Uses only this scene&apos;s own image and outputs. No upload needed.</p>
          </div>
          <SelfCheckPanel jobId={id} />
        </div>
      </Reveal>

      <div className="max-w-3xl pt-2">
        <p className="eyebrow">Step 2 · Score against ground truth (optional)</p>
        <h2 className="mt-1 text-2xl font-semibold tracking-tight text-polar-night">Add reference elevation data for a real accuracy score.</h2>
        <p className="mt-2 text-[0.95rem] leading-relaxed text-slate-ice">
          This is <b>not</b> the image again: it is a separate <b>height raster</b> covering the same place (a LiDAR DSM or nDSM as GeoTIFF, PNG or NPY), because an optical image contains no measured heights to score against.
          It is reprojected onto this scene and scored: RMSE, MAE, bias, NMAD, Pearson r and δ1, globally, per land-cover class and per landscape type.
        </p>
      </div>

      {error && <ErrorNote message={error} />}

      <Reveal>
        <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
          <label
            className={cn(
              "card contour-bg relative flex cursor-pointer flex-col items-center justify-center overflow-hidden px-6 py-10 text-center transition-all",
              dragging ? "border-station-orange shadow-[0_0_0_4px_rgba(242,107,33,0.15)]" : "hover:border-glacier-500",
            )}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); const f = e.dataTransfer.files?.[0]; if (f) void submit(f); }}
          >
            <input ref={input} type="file" className="sr-only" accept=".tif,.tiff,.png,.npy" onChange={(e) => e.target.files?.[0] && void submit(e.target.files[0])} disabled={busy} />
            <div className="absolute inset-0 bg-gradient-to-b from-frost/60 to-frost/95" />
            <div className="relative">
              <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-lg bg-white text-deep-ice shadow-[var(--card-shadow)]"><FileUp className="h-7 w-7" strokeWidth={1.4} /></span>
              <p className="mt-4 text-base font-semibold text-polar-night">{busy ? "Scoring…" : "Drop a reference raster here"}</p>
              <p className="mt-1 text-sm text-slate-ice">GeoTIFF · PNG · NPY (float metres)</p>
              {progress !== null && <ProgressBar value={progress * 100} className="mx-auto mt-4 max-w-xs" />}
            </div>
          </label>
          <div className="card space-y-4 p-5">
            <div>
              <span className="mb-1.5 block text-xs font-semibold text-deep-ice">Reference contains</span>
              <Segmented value={kind} onChange={setKind} options={[{ value: "auto", label: "Auto" }, { value: "dsm", label: "Surface (DSM)" }, { value: "ndsm", label: "Height above ground" }]} />
              <p className="mt-2 text-xs leading-snug text-slate-ice">A DSM is compared with this scene&apos;s DSM; an nDSM with its height above ground.</p>
            </div>
            {lab?.has_sample_reference && (
              <Button variant="soft" className="w-full" loading={busy} onClick={bundled}>
                <BadgeCheck className="h-4 w-4" strokeWidth={1.5} /> Use the bundled GAMUS reference
              </Button>
            )}
            <InfoNote>Your reference is processed locally and never leaves this machine.</InfoNote>
          </div>
        </div>
      </Reveal>

      {scored && g && (
        <>
          <Reveal>
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="aurora">{lab.reference_source === "bundled" ? "Bundled reference scene" : "Uploaded reference"}</Badge>
              <Badge tone="muted">{lab.reference_kind === "ndsm" ? "nDSM (height above ground)" : "DSM (surface)"}</Badge>
              <span className="text-xs text-slate-ice">{lab.reference_name} · {lab.alignment}</span>
            </div>
            {lab.caveats?.map((c) => <InfoNote key={c} className="mt-3">{c}</InfoNote>)}
            <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
              <Stat label="RMSE" value={g.rmse} unit={unit} digits={2} tone="orange" />
              <Stat label="MAE" value={g.mae} unit={unit} digits={2} />
              <Stat label="Pearson r" value={g.pearson_r ?? null} digits={3} tone="aurora" />
              <Stat label="Bias" value={g.bias} unit={unit} digits={2} hint={`NMAD ${fmt(g.nmad, 2)} · δ1 ${g.delta1 !== null && g.delta1 !== undefined ? fmt(g.delta1, 2) : "n/a"}`} />
            </div>
          </Reveal>

          <div className="grid gap-5 lg:grid-cols-2">
            <Reveal>
              <MetricsTable
                title="Per landscape type"
                rows={LANDSCAPES.map((name) => ({ label: titleCase(name), m: lab.per_landscape?.[name], note: lab.per_landscape?.[name]?.blocks ? `${lab.per_landscape[name].blocks} blocks` : undefined }))}
              />
            </Reveal>
            <Reveal delay={0.05}>
              <MetricsTable title="Per land-cover class" rows={Object.entries(lab.per_class ?? {}).map(([name, m]) => ({ label: titleCase(name), m }))} />
            </Reveal>
          </div>

          <div className="grid gap-5 lg:grid-cols-2">
            <Reveal>
              <div className="card p-5">
                <p className="eyebrow">Predicted vs reference</p>
                <ScatterPlot data={lab.scatter ?? []} unit={unit} range={lab.value_range ?? [0, 1]} />
              </div>
            </Reveal>
            <Reveal delay={0.05}>
              <div className="card p-5">
                <p className="eyebrow">Error distribution (predicted − reference)</p>
                <Histogram bins={errorBins} xLabel={`error (${unit})`} color="#a88a2c" height={300} marker="0.0" />
              </div>
            </Reveal>
          </div>

          <Reveal>
            <ErrorMapPanel id={id} width={metadata.width} height={metadata.height} lab={lab} fields={fields} unit={unit} />
          </Reveal>
        </>
      )}

      {!scored && lab && (
        <Reveal>
          <InfoNote>
            <span className="flex items-center gap-2 font-semibold"><FlaskConical className="h-4 w-4" strokeWidth={1.5} /> No reference scored yet.</span>
            <span className="mt-1 block">Upload LiDAR or use the bundled reference to see metrics, per-landscape breakdown, the scatter plot and a live error map.</span>
          </InfoNote>
        </Reveal>
      )}

      {/* ---------------- benchmark ---------------- */}
      <Reveal>
        <div className="card p-5 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="max-w-3xl">
              <p className="eyebrow">Benchmark: does retraining help?</p>
              <h2 className="mt-1 text-xl font-semibold text-polar-night">Off-the-shelf vs fine-tuned, per landscape.</h2>
              {bench?.measured ? (
                <p className="mt-1 text-sm leading-relaxed text-slate-ice">
                  Measured on {bench.tiles} real tiles of the {bench.dataset}. {bench.protocol} {bench.hilly && <span className="font-semibold text-deep-ice">Hilly: {bench.hilly}.</span>}
                </p>
              ) : (
                <p className="mt-1 text-sm text-slate-ice">{bench?.note ?? "Benchmark not available."}</p>
              )}
            </div>
            {bench?.measured && <Badge tone="aurora">Measured{bench.device ? ` on ${bench.device.toUpperCase()}` : ""}</Badge>}
          </div>

          {bench?.measured && (
            <div className="mt-5 grid gap-6 xl:grid-cols-[1.1fr_1fr]">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[520px]">
                  <thead>
                    <tr className="text-[0.66rem] font-semibold uppercase tracking-wider text-slate-ice">
                      <th className="pb-2 text-left">Configuration</th>
                      <th className="pb-2 text-right">Urban</th>
                      <th className="pb-2 text-right">Sparse</th>
                      <th className="pb-2 text-right">Hilly</th>
                      <th className="pb-2 text-right">Forest</th>
                      <th className="pb-2 text-right">Mixed</th>
                      <th className="pb-2 text-right">MAE</th>
                      <th className="pb-2 text-right">r</th>
                    </tr>
                  </thead>
                  <tbody>
                    {bench.rows.map((row) => (
                      <tr key={row.key} className="border-t border-glacier-300/40">
                        <td className="py-3 pr-3">
                          <p className="text-sm font-semibold text-polar-night">{row.label}</p>
                          <p className="text-xs text-slate-ice">{row.note}</p>
                        </td>
                        {row.measured && row.overall ? (
                          <>
                            <td className="mono py-3 text-right text-sm">{row.urban ? fmt(row.urban.rmse, 2) : "-"}</td>
                            <td className="mono py-3 text-right text-sm">{row.sparse ? fmt(row.sparse.rmse, 2) : "-"}</td>
                            <td className="mono py-3 text-right text-xs italic text-slate-ice">n/a</td>
                            <td className="mono py-3 text-right text-sm">{row.forested ? fmt(row.forested.rmse, 2) : "-"}</td>
                            <td className="mono py-3 text-right text-sm">{row.mixed ? fmt(row.mixed.rmse, 2) : "-"}</td>
                            <td className="mono py-3 text-right text-sm">{fmt(row.overall.mae, 2)}</td>
                            <td className="mono py-3 text-right text-sm">{fmt(row.overall.r, 2)}</td>
                          </>
                        ) : (
                          <td colSpan={7} className="py-3 text-right"><Badge tone="muted">sample run · not measured</Badge></td>
                        )}
                      </tr>
                    ))}
                    {lab?.dem_only?.rmse !== undefined && (
                      <tr className="border-t border-glacier-300/40">
                        <td className="py-3 text-sm font-semibold text-polar-night">DEM only (30 m upsampled)<p className="text-xs font-medium text-slate-ice">This scene, against your reference</p></td>
                        <td colSpan={5} className="mono py-3 text-right text-sm">{fmt(lab.dem_only.rmse, 2)} RMSE</td>
                        <td className="mono py-3 text-right text-sm">{fmt(lab.dem_only.mae, 2)}</td>
                        <td className="mono py-3 text-right text-sm">{lab.dem_only.pearson_r !== null && lab.dem_only.pearson_r !== undefined ? fmt(lab.dem_only.pearson_r, 2) : "n/a"}</td>
                      </tr>
                    )}
                  </tbody>
                </table>
                <p className="mt-3 text-xs text-slate-ice">RMSE in metres. The DEM-only baseline appears once this scene is scored against your own reference (there is no DEM at GAMUS tile locations).</p>
              </div>
              <GroupedBars data={chartRows} keys={["Urban", "Sparse", "Forest", "Mixed"]} colors={["#4d6b3f", "#a89a4a", "#3f7f6b", "#8a7b66"]} unit="m" />
            </div>
          )}
        </div>
      </Reveal>
    </div>
  );
}
