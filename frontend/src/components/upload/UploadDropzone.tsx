"use client";

import { useCallback, useRef, useState } from "react";

interface UploadDropzoneProps {
  onFileSelected: (file: File) => void;
  validationError: string | null;
}

const ACCEPT = ".png,.jpg,.jpeg,.tif,.tiff,image/png,image/jpeg,image/tiff";

export function UploadDropzone({ onFileSelected, validationError }: UploadDropzoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (files: FileList | null) => {
      const file = files?.[0];
      if (file) onFileSelected(file);
    },
    [onFileSelected],
  );

  const onDrop = useCallback(
    (event: React.DragEvent<HTMLDivElement>) => {
      event.preventDefault();
      setIsDragging(false);
      handleFiles(event.dataTransfer.files);
    },
    [handleFiles],
  );

  return (
    <div className="w-full">
      <div
        role="button"
        tabIndex={0}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && inputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
        className={`glass-panel flex cursor-pointer flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed px-8 py-16 text-center transition-colors ${
          isDragging
            ? "border-primary/70 bg-primary/5"
            : "border-border hover:border-primary/40 hover:bg-muted/30"
        }`}
      >
        <div className="flex h-14 w-14 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-primary">
          <svg viewBox="0 0 24 24" fill="none" className="h-7 w-7" stroke="currentColor" strokeWidth={1.75}>
            <path
              d="M12 16V4m0 0L7 9m5-5l5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <div>
          <p className="text-lg font-medium text-foreground">Upload Remote-Sensing Image</p>
          <p className="mt-1 text-sm text-muted-foreground">Drag &amp; drop your image here, or</p>
        </div>
        <span className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90">
          Browse Files
        </span>
        <p className="text-xs uppercase tracking-wider text-muted-foreground">PNG &bull; JPG &bull; TIFF &bull; GeoTIFF</p>
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(e) => handleFiles(e.target.files)}
        />
      </div>
      {validationError && (
        <p className="mt-3 rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-2 text-sm text-red-200">
          {validationError}
        </p>
      )}
    </div>
  );
}
