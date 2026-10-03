import { PROCESSING_STAGE_ORDER, STAGE_LABEL, type ProcessingStatus } from "@/lib/types/processing";

interface ProcessingStagesProps {
  processingStatus: ProcessingStatus | null;
  /** True while we're still uploading, before the backend has assigned a stage. */
  isUploading: boolean;
}

export function ProcessingStages({ processingStatus, isUploading }: ProcessingStagesProps) {
  const currentIndex = processingStatus ? PROCESSING_STAGE_ORDER.indexOf(processingStatus.stage) : -1;

  const progress = isUploading ? 0 : (processingStatus?.progress ?? 0);

  return (
    <div className="glass-panel rounded-2xl px-6 py-8">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-sm font-medium text-foreground">
          {isUploading ? "Uploading image to backend..." : "Processing pipeline"}
        </p>
        <span className="text-xs font-medium text-primary">{progress}%</span>
      </div>
      <div className="mb-6 h-1.5 w-full overflow-hidden rounded-full bg-muted/50">
        <div
          className="h-full rounded-full bg-gradient-to-r from-primary to-primary/60 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <ol className="space-y-4">
        {PROCESSING_STAGE_ORDER.map((stage, index) => {
          const isDone = currentIndex > index;
          const isActive = currentIndex === index;
          return (
            <li key={stage} className="flex items-center gap-3">
              <span
                className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold ${
                  isDone
                    ? "bg-primary text-primary-foreground"
                    : isActive
                      ? "border-2 border-primary text-primary"
                      : "border border-border text-muted-foreground"
                }`}
              >
                {isDone ? "✓" : index + 1}
              </span>
              <span
                className={`text-sm ${
                  isDone ? "text-muted-foreground line-through decoration-muted-foreground" : isActive ? "font-medium text-foreground" : "text-muted-foreground"
                }`}
              >
                {STAGE_LABEL[stage]}
              </span>
              {isActive && (
                <span className="ml-auto flex gap-1">
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.3s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary [animation-delay:-0.15s]" />
                  <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-primary" />
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
