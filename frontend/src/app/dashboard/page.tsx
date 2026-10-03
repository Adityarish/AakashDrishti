"use client";

import { AppHeader } from "@/components/common/AppHeader";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { UploadDropzone } from "@/components/upload/UploadDropzone";
import { ImagePreviewCard } from "@/components/upload/ImagePreviewCard";
import { ProcessingStages } from "@/components/processing/ProcessingStages";
import { ResultsScreen } from "@/components/results/ResultsScreen";
import { FeaturedSceneCard } from "@/components/upload/FeaturedSceneCard";
import { useDepthWizardWorkflow } from "@/hooks/useDepthWizardWorkflow";
import type { UploadResult } from "@/lib/types/upload";

const PIPELINE_STEPS = [
  { label: "Image", detail: "PNG / JPG / GeoTIFF" },
  { label: "Depth Models", detail: "Depth Anything V2 (height) + Depth Pro (reference)" },
  { label: "Height Field", detail: "Tiled, TTA, per-pixel uncertainty" },
  { label: "Calibration", detail: "SRTM / DEM / GCP" },
  { label: "3D Terrain", detail: "DSM mesh + RGB texture" },
  { label: "Flythrough", detail: "First-person + measurement" },
];

export default function Dashboard() {
  const {
    status,
    uploadedFile,
    validationError,
    uploadResult,
    processingStatus,
    result,
    errorMessage,
    selectFile,
    clearFile,
    startProcessing,
  } = useDepthWizardWorkflow();

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-10 xl:px-10">
        {status === "idle" && (
          <div className="mx-auto max-w-4xl space-y-10">
            <PipelineDiagram />
            <FeaturedSceneCard />
            <div id="upload-section" className="scroll-mt-24 space-y-6">
              <div>
                <h1 className="text-2xl font-semibold text-foreground">Upload Your Own Image</h1>
                <p className="mt-1 text-sm text-muted-foreground">
                  Start by uploading a single-view remote-sensing image (PNG, JPG, TIFF, or GeoTIFF). AakashDrishti
                  runs real Depth Anything V2 + Depth Pro inference, calibrated elevation, and 3D terrain
                  reconstruction on it -- there is no sample data preloaded.
                </p>
              </div>
              <UploadDropzone onFileSelected={selectFile} validationError={validationError} />
            </div>
          </div>
        )}

        {status === "selected" && uploadedFile && (
          <div className="mx-auto max-w-4xl space-y-6">
            <div>
              <h1 className="text-2xl font-semibold text-foreground">Review Your Image</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                Confirm this is the correct image, then process it. Nothing is sent to the backend until you click
                Process Image.
              </p>
            </div>
            <ImagePreviewCard
              uploadedFile={uploadedFile}
              uploadResult={uploadResult}
              isCheckingGeo={false}
              onChangeImage={clearFile}
              onProcess={startProcessing}
              processDisabled={false}
              processLabel="Process Image"
            />
          </div>
        )}

        {(status === "uploading" || status === "processing") && uploadedFile && (
          <div className="mx-auto max-w-4xl space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-foreground">Processing</h1>
                <p className="mt-1 text-sm text-muted-foreground">{uploadedFile.name}</p>
              </div>
              {uploadResult && (
                <ImagePreviewGeoInline uploadResult={uploadResult} />
              )}
            </div>
            <ProcessingStages processingStatus={processingStatus} isUploading={status === "uploading"} />
          </div>
        )}

        {status === "error" && (
          <div className="mx-auto max-w-4xl space-y-6">
            <div className="flex items-center justify-between">
              <div>
                <h1 className="text-2xl font-semibold text-foreground">Processing</h1>
                <p className="mt-1 text-sm text-muted-foreground">{uploadedFile?.name}</p>
              </div>
              {uploadResult && <ImagePreviewGeoInline uploadResult={uploadResult} />}
            </div>
            {errorMessage && <ErrorBanner message={errorMessage} />}
            <div className="flex gap-3">
              {uploadedFile && (
                <button
                  type="button"
                  onClick={startProcessing}
                  className="rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90"
                >
                  Retry
                </button>
              )}
              <button
                type="button"
                onClick={clearFile}
                className="rounded-lg border border-border px-4 py-2 text-sm font-medium text-muted-foreground hover:border-primary/40 hover:text-foreground"
              >
                Upload a Different Image
              </button>
            </div>
          </div>
        )}

        {status === "complete" && result && (
          <ResultsScreen result={result} uploadResult={uploadResult} onStartOver={clearFile} />
        )}
      </main>
    </div>
  );
}

function PipelineDiagram() {
  return (
    <div className="glass-panel overflow-hidden rounded-2xl px-6 py-8 sm:px-10">
      <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary/80">
        Single-View Height Estimation &amp; 3D Flythrough
      </p>
      <h2 className="mt-2 text-2xl font-semibold text-foreground sm:text-3xl">
        One pipeline, from pixels to a navigable digital twin.
      </h2>
      <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
        AakashDrishti estimates height with a satellite-fine-tuned Depth Anything V2 (Depth Pro runs alongside as a reference), calibrates it against real elevation data when available,
        and reconstructs a textured terrain mesh you can fly through, measure, and validate.
      </p>

      <div className="mt-7 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {PIPELINE_STEPS.map((step, i) => (
          <div key={step.label} className="relative min-w-0">
            <div className="flex h-full flex-col items-center rounded-xl border border-border bg-muted/30 px-2.5 py-3 text-center">
              <span className="flex h-6 w-6 items-center justify-center rounded-full border border-primary/40 bg-primary/10 text-[11px] font-semibold text-primary">
                {i + 1}
              </span>
              <p className="mt-2 text-xs font-semibold text-foreground">{step.label}</p>
              <p className="mt-0.5 text-[10px] leading-tight text-muted-foreground">{step.detail}</p>
            </div>
            {i < PIPELINE_STEPS.length - 1 && (
              <svg
                viewBox="0 0 24 24"
                fill="none"
                className="absolute -right-[0.55rem] top-1/2 z-10 hidden h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground lg:block"
                stroke="currentColor"
                strokeWidth={2}
              >
                <path d="M5 12h14M13 6l6 6-6 6" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ImagePreviewGeoInline({ uploadResult }: { uploadResult: UploadResult }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium ${
        uploadResult.isGeoreferenced
          ? "border-secondary/30 bg-secondary/10 text-secondary"
          : "border-muted-foreground/30 bg-muted-foreground/10 text-muted-foreground"
      }`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${uploadResult.isGeoreferenced ? "bg-secondary" : "bg-muted-foreground"}`} />
      {uploadResult.isGeoreferenced ? "GeoTIFF detected" : "Non-georeferenced image"}
    </span>
  );
}
