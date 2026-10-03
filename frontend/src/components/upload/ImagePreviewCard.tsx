import type { UploadedFile, UploadResult } from "@/lib/types/upload";
import { formatBytes } from "@/lib/validation/file";
import { GeoStatusBadge } from "./GeoStatusBadge";

interface ImagePreviewCardProps {
  uploadedFile: UploadedFile;
  uploadResult: UploadResult | null;
  isCheckingGeo: boolean;
  onChangeImage: () => void;
  onProcess: () => void;
  processDisabled: boolean;
  processLabel: string;
}

export function ImagePreviewCard({
  uploadedFile,
  uploadResult,
  isCheckingGeo,
  onChangeImage,
  onProcess,
  processDisabled,
  processLabel,
}: ImagePreviewCardProps) {
  const isTiff = uploadedFile.extension === "tif" || uploadedFile.extension === "tiff";

  return (
    <div className="glass-panel overflow-hidden rounded-2xl">
      <div className="relative flex h-72 items-center justify-center bg-black/30">
        {isTiff && uploadedFile.width === null ? (
          <div className="flex flex-col items-center gap-2 px-6 text-center text-muted-foreground">
            <svg viewBox="0 0 24 24" fill="none" className="h-10 w-10" stroke="currentColor" strokeWidth={1.5}>
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <path d="M3 15l4-4 5 5 3-3 6 6" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <p className="text-sm">
              Browser preview isn&apos;t available for this TIFF/GeoTIFF. It will still be uploaded and processed
              as-is.
            </p>
          </div>
        ) : (
          // eslint-disable-next-line @next/next/no-img-element -- previewUrl is a blob: object URL from the user's File, not a static asset next/image can optimize.
          <img
            src={uploadedFile.previewUrl}
            alt={`Preview of uploaded file ${uploadedFile.name}`}
            className="max-h-full max-w-full object-contain"
          />
        )}
      </div>

      <div className="space-y-3 border-t border-border px-5 py-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-foreground">{uploadedFile.name}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {formatBytes(uploadedFile.sizeBytes)}
              {uploadedFile.width && uploadedFile.height ? ` · ${uploadedFile.width}×${uploadedFile.height}px` : ""}
              {" · "}
              {uploadedFile.extension.toUpperCase()}
            </p>
          </div>
          <button
            type="button"
            onClick={onChangeImage}
            className="shrink-0 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:border-primary/40 hover:text-foreground"
          >
            Change Image
          </button>
        </div>

        <GeoStatusBadge uploadResult={uploadResult} isChecking={isCheckingGeo} />

        <button
          type="button"
          onClick={onProcess}
          disabled={processDisabled}
          className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground"
        >
          {processLabel}
        </button>
      </div>
    </div>
  );
}
