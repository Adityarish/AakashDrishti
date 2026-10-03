import type { UploadResult } from "@/lib/types/upload";

interface GeoStatusBadgeProps {
  /** null = not checked yet (before upload), "checking" while the upload request is in flight. */
  uploadResult: UploadResult | null;
  isChecking: boolean;
}

export function GeoStatusBadge({ uploadResult, isChecking }: GeoStatusBadgeProps) {
  if (isChecking) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-border bg-muted/50 px-3 py-1 text-xs font-medium text-muted-foreground">
        <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted-foreground" />
        Checking geospatial metadata...
      </span>
    );
  }

  if (!uploadResult) {
    return null;
  }

  if (uploadResult.isGeoreferenced) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-secondary/30 bg-secondary/10 px-3 py-1 text-xs font-medium text-secondary">
        <span className="h-1.5 w-1.5 rounded-full bg-secondary" />
        GeoTIFF detected &middot; {uploadResult.geo?.crs ?? "CRS unknown"}
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-muted-foreground/30 bg-muted-foreground/10 px-3 py-1 text-xs font-medium text-muted-foreground">
      <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground" />
      Non-georeferenced image &middot; relative depth only
    </span>
  );
}
