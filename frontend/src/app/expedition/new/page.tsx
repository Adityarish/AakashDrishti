"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Check, FileImage, Rocket, UploadCloud } from "lucide-react";

import { HistoryPicker } from "@/components/expedition/HistoryPicker";
import { MetadataPanel } from "@/components/expedition/MetadataPanel";
import { OptionsForm, defaultDraft, draftToOptions, type OptionsDraft } from "@/components/expedition/OptionsForm";
import { PageShell } from "@/components/layout/PageShell";
import { Badge, Button, ErrorNote, PageHeader, ProgressBar, Reveal } from "@/components/ui";
import { ApiError, cloneProject, getProject, listSamples, loadSample, outputUrl, putGcps, runPipeline, sampleThumb, uploadGcpCsv, uploadImage, getGcps } from "@/lib/api/survey";
import { useAuth } from "@/lib/auth";
import { fmtBytes } from "@/lib/format";
import type { Gcp, JobSummary, Sample, UploadInfo } from "@/lib/sceneTypes";
import { cn } from "@/lib/utils";

const ACCEPT = [".png", ".jpg", ".jpeg", ".tif", ".tiff"];
const MAX_BYTES = 2 * 1024 ** 3;
const STEPS = ["Image", "Metadata", "Options", "Run"];

function messageOf(error: unknown): string {
  return error instanceof ApiError || error instanceof Error ? error.message : "Something went wrong.";
}

function Stepper({ step }: { step: number }) {
  return (
    <ol className="flex items-center gap-2" aria-label="Progress">
      {STEPS.map((label, index) => {
        const done = index < step;
        const active = index === step;
        return (
          <li key={label} className="flex items-center gap-2">
            <span
              className={cn(
                "flex h-8 items-center gap-2 rounded-full border px-3 text-xs font-semibold transition-colors",
                active && "border-station-orange bg-station-orange text-white shadow-[0_6px_16px_rgba(242,107,33,0.28)]",
                done && "border-aurora/40 bg-aurora/10 text-[#4d6b3f]",
                !active && !done && "border-glacier-300 bg-white/60 text-slate-ice",
              )}
            >
              {done ? <Check className="h-3.5 w-3.5" strokeWidth={2.5} /> : <span className="mono">{index + 1}</span>}
              <span className="hidden sm:inline">{label}</span>
            </span>
            {index < STEPS.length - 1 && <span className="h-px w-5 bg-glacier-300 sm:w-8" />}
          </li>
        );
      })}
    </ol>
  );
}

function Wizard() {
  const router = useRouter();
  const params = useSearchParams();
  const { user, authRequired, authenticated } = useAuth();
  const [step, setStep] = useState(0);
  const [info, setInfo] = useState<UploadInfo | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [samples, setSamples] = useState<Sample[]>([]);
  const [busySample, setBusySample] = useState<string | null>(null);
  const [busyHistory, setBusyHistory] = useState<string | null>(null);
  const [draft, setDraft] = useState<OptionsDraft>(defaultDraft());
  const [gcps, setGcps] = useState<Gcp[]>([]);
  const [starting, setStarting] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const objectUrl = useRef<string | null>(null);

  const jobParam = params.get("job");

  useEffect(() => {
    listSamples().then(setSamples).catch(() => setSamples([]));
  }, []);

  useEffect(() => {
    if (!jobParam || info?.job_id === jobParam) return;
    getProject(jobParam)
      .then((loaded) => {
        setInfo(loaded);
        if (loaded.sample_id) setPreviewUrl(sampleThumb(loaded.sample_id));
        setStep(1);
      })
      .catch((err) => setError(messageOf(err)));
  }, [jobParam, info?.job_id]);

  useEffect(
    () => () => {
      if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    },
    [],
  );

  const onFile = useCallback(async (file: File) => {
    setError(null);
    const lower = file.name.toLowerCase();
    if (!ACCEPT.some((ext) => lower.endsWith(ext))) {
      setError(`"${file.name}" is not a supported image. Use PNG, JPG, TIFF or GeoTIFF.`);
      return;
    }
    if (file.size > MAX_BYTES) {
      setError("That file is larger than the 2 GB limit.");
      return;
    }
    if (objectUrl.current) URL.revokeObjectURL(objectUrl.current);
    objectUrl.current = null;
    if (/\.(png|jpe?g)$/.test(lower)) {
      objectUrl.current = URL.createObjectURL(file);
      setPreviewUrl(objectUrl.current);
    } else {
      setPreviewUrl(null);
    }
    setProgress(0);
    try {
      const uploaded = await uploadImage(file, setProgress);
      setInfo(uploaded);
      router.replace(`/expedition/new?job=${uploaded.job_id}`);
      setStep(1);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setProgress(null);
    }
  }, [router]);

  async function openSample(sample: Sample, variant: "png" | "geotiff") {
    setBusySample(`${sample.id}:${variant}`);
    setError(null);
    try {
      const loaded = await loadSample(sample.id, variant);
      setInfo(loaded);
      setPreviewUrl(sampleThumb(sample.id));
      router.replace(`/expedition/new?job=${loaded.job_id}`);
      setStep(1);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusySample(null);
    }
  }

  async function openFromHistory(job: JobSummary) {
    setBusyHistory(job.job_id);
    setError(null);
    try {
      const cloned = await cloneProject(job.job_id);
      setInfo(cloned);
      setPreviewUrl(job.thumbnail_url ? outputUrl(job.thumbnail_url) : cloned.sample_id ? sampleThumb(cloned.sample_id) : null);
      router.replace(`/expedition/new?job=${cloned.job_id}`);
      setStep(1);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusyHistory(null);
    }
  }

  async function importCsv(file: File) {
    if (!info) return;
    try {
      await uploadGcpCsv(info.job_id, file);
      setGcps(await getGcps(info.job_id));
    } catch (err) {
      setError(messageOf(err));
    }
  }

  async function start() {
    if (!info) return;
    setStarting(true);
    setError(null);
    try {
      if (gcps.length > 0) await putGcps(info.job_id, gcps);
      await runPipeline(info.job_id, draftToOptions(draft));
      router.push(`/expedition/${info.job_id}/progress`);
    } catch (err) {
      setError(messageOf(err));
      setStarting(false);
    }
  }

  const locked = authRequired && (!authenticated || user?.role !== "analyst");

  return (
    <PageShell>
      <PageHeader
        eyebrow="New expedition"
        title={step === 0 ? "Bring in a satellite image" : step === 1 ? "What we found in your file" : "Tune the run"}
        description={
          step === 0
            ? "Drop any single-view optical image. GeoTIFFs give absolute heights in metres; plain PNG or JPG gives a relative DSM."
            : step === 1
              ? "Format, georeferencing, pixel size and sun geometry are read from the file. The mode decides what kind of DSM you get."
              : "Sensible defaults are pre-selected. Change only what you know."
        }
        actions={<Stepper step={step} />}
      />

      {locked && (
        <ErrorNote className="mt-6" message="Uploading needs an analyst account. Sign in from the top right (the first account created is an analyst)." />
      )}
      {error && <ErrorNote className="mt-6" message={error} />}

      {step === 0 && (
        <div className="mt-8 space-y-8">
          <Reveal>
            <label
              className={cn(
                "card contour-bg relative block cursor-pointer overflow-hidden px-6 py-16 text-center transition-all",
                dragging ? "border-station-orange bg-glacier-100 shadow-[0_0_0_4px_rgba(242,107,33,0.15)]" : "hover:border-glacier-500",
              )}
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                const file = e.dataTransfer.files?.[0];
                if (file) void onFile(file);
              }}
            >
              <input ref={input} type="file" className="sr-only" accept={ACCEPT.join(",")} onChange={(e) => e.target.files?.[0] && void onFile(e.target.files[0])} disabled={locked} />
              <div className="absolute inset-0 bg-gradient-to-b from-frost/60 to-frost/95" />
              <div className="relative">
                <span className="mx-auto flex h-16 w-16 items-center justify-center rounded-lg bg-white text-deep-ice shadow-[var(--card-shadow)]">
                  <UploadCloud className="h-8 w-8" strokeWidth={1.4} />
                </span>
                <p className="mt-5 text-lg font-semibold text-polar-night">{progress !== null ? "Uploading…" : "Drag and drop your image here"}</p>
                <p className="mt-1 text-sm text-slate-ice">or click to browse · PNG, JPG, TIFF, BigTIFF, GeoTIFF · up to 2 GB · validated by magic bytes</p>
                {progress !== null && <ProgressBar value={progress * 100} className="mx-auto mt-6 max-w-sm" />}
              </div>
            </label>
          </Reveal>

          <Reveal delay={0.05}>
            <HistoryPicker onPick={openFromHistory} busyId={busyHistory} disabled={locked} />
          </Reveal>

          {samples.length > 0 && (
            <Reveal delay={0.08}>
              <div className="flex items-end justify-between">
                <div>
                  <p className="eyebrow">Or start from a sample</p>
                  <p className="mt-1 text-sm text-slate-ice">Real GAMUS test tiles that ship with a reference height map for the validation lab.</p>
                </div>
              </div>
              <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
                {samples.filter((s) => s.featured).map((sample) => (
                  <div key={sample.id} className="card card-lift overflow-hidden">
                    <div className="relative aspect-[16/9] bg-glacier-100">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={sampleThumb(sample.id)} alt={sample.title} className="h-full w-full object-cover" loading="lazy" />
                      <Badge tone="muted" className="absolute left-3 top-3 !bg-white/90">
                        {sample.id.replace("_", " ")}
                      </Badge>
                    </div>
                    <div className="p-4">
                      <p className="font-semibold text-polar-night">{sample.title}</p>
                      <div className="mt-3 flex gap-2">
                        <Button size="sm" variant="primary" className="flex-1" loading={busySample === `${sample.id}:geotiff`} disabled={busySample !== null || locked} onClick={() => openSample(sample, "geotiff")}>
                          GeoTIFF
                        </Button>
                        <Button size="sm" variant="soft" className="flex-1" loading={busySample === `${sample.id}:png`} disabled={busySample !== null || locked} onClick={() => openSample(sample, "png")}>
                          PNG
                        </Button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </Reveal>
          )}
        </div>
      )}

      {step >= 1 && info && (
        <div className="mt-8 grid gap-6 lg:grid-cols-[minmax(0,320px)_1fr]">
          <Reveal>
            <div className="card overflow-hidden lg:sticky lg:top-24">
              <div className="flex aspect-square items-center justify-center bg-glacier-100">
                {previewUrl ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={previewUrl} alt="Preview of the selected image" className="h-full w-full object-cover" />
                ) : (
                  <div className="px-6 text-center text-slate-ice">
                    <FileImage className="mx-auto h-10 w-10" strokeWidth={1.2} />
                    <p className="mt-2 text-xs">Browsers cannot preview TIFF. The full-colour preview appears after processing.</p>
                  </div>
                )}
              </div>
              <div className="p-4">
                <p className="truncate text-sm font-semibold text-polar-night" title={info.filename}>
                  {info.filename}
                </p>
                <p className="mono mt-1 text-xs text-slate-ice">
                  {info.width}×{info.height} · {fmtBytes(info.size_bytes)}
                </p>
              </div>
            </div>
          </Reveal>

          <div className="space-y-6">
            {step === 1 && (
              <>
                <MetadataPanel info={info} />
                <div className="flex items-center justify-between">
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setInfo(null);
                      setStep(0);
                      router.replace("/expedition/new");
                    }}
                  >
                    <ArrowLeft className="h-4 w-4" strokeWidth={1.75} /> Choose another image
                  </Button>
                  <Button onClick={() => setStep(2)}>
                    Continue <ArrowRight className="h-4 w-4" strokeWidth={1.75} />
                  </Button>
                </div>
              </>
            )}
            {step >= 2 && (
              <>
                <OptionsForm info={info} draft={draft} onChange={setDraft} gcps={gcps} onGcps={setGcps} onGcpCsv={importCsv} />
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <Button variant="ghost" onClick={() => setStep(1)}>
                    <ArrowLeft className="h-4 w-4" strokeWidth={1.75} /> Back
                  </Button>
                  <Button size="lg" loading={starting} disabled={locked} onClick={start}>
                    <Rocket className="h-5 w-5" strokeWidth={1.75} /> Run elevation extraction
                  </Button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </PageShell>
  );
}

export default function NewExpedition() {
  return (
    <Suspense fallback={null}>
      <Wizard />
    </Suspense>
  );
}
