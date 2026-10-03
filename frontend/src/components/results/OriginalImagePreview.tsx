"use client";

import { useState } from "react";

interface OriginalImagePreviewProps {
  src: string;
}

/** Mirrors ImagePreviewCard's TIFF fallback: browsers can't decode TIFF/GeoTIFF
 * in an <img> tag, so show an honest message instead of a broken-image icon. */
export function OriginalImagePreview({ src }: OriginalImagePreviewProps) {
  const [failed, setFailed] = useState(false);

  if (failed) {
    return (
      <p className="max-w-xs text-center text-sm text-muted-foreground">
        Browser preview isn&apos;t available for this file format (e.g. TIFF/GeoTIFF), but it was uploaded and
        processed as-is.
      </p>
    );
  }

  return (
    // eslint-disable-next-line @next/next/no-img-element -- blob: object URL of the user's own uploaded file
    <img
      src={src}
      alt="Original uploaded remote-sensing image"
      className="max-h-full max-w-full object-contain"
      onError={() => setFailed(true)}
    />
  );
}
