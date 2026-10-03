import type { ProcessingStage } from "@/lib/types/processing";
import { STAGE_LABEL } from "@/lib/types/processing";

/**
 * Status pill for a job history card/detail view. Color-coding follows the
 * same theme-token convention already used across the app (ResultsScreen.tsx,
 * GeoStatusBadge.tsx): `secondary` = real/ready, `muted-foreground` = neutral,
 * `destructive` = failed, `primary` (pulsing dot) = actively in progress.
 */
export function JobStatusBadge({ stage }: { stage: ProcessingStage }) {
  if (stage === "READY") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-secondary/30 bg-secondary/10 px-2.5 py-1 text-[11px] font-medium text-secondary">
        <span className="h-1.5 w-1.5 rounded-full bg-secondary" />
        Ready
      </span>
    );
  }

  if (stage === "FAILED") {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-destructive/30 bg-destructive/10 px-2.5 py-1 text-[11px] font-medium text-destructive">
        <span className="h-1.5 w-1.5 rounded-full bg-destructive" />
        Failed
      </span>
    );
  }

  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-primary/30 bg-primary/10 px-2.5 py-1 text-[11px] font-medium text-primary">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-primary" />
      {STAGE_LABEL[stage] ?? stage}
    </span>
  );
}

export function GeoreferencedBadge({ isGeoreferenced }: { isGeoreferenced: boolean }) {
  if (isGeoreferenced) {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
        GeoTIFF
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1 rounded-full border border-border bg-muted/40 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
      Non-georeferenced
    </span>
  );
}
