interface ResultPanelProps {
  title: string;
  available: boolean;
  unavailableNote: string;
  children?: React.ReactNode;
}

export function ResultPanel({ title, available, unavailableNote, children }: ResultPanelProps) {
  return (
    <div className="glass-panel overflow-hidden rounded-2xl">
      <div className="flex items-center justify-between border-b border-border px-5 py-3">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <span
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
            available ? "border border-secondary/30 bg-secondary/10 text-secondary" : "border border-border bg-muted/50 text-muted-foreground"
          }`}
        >
          {available ? "Real result" : "Not yet available"}
        </span>
      </div>
      <div className="flex min-h-40 items-center justify-center p-5">
        {available ? (
          children
        ) : (
          <p className="max-w-xs text-center text-sm text-muted-foreground">{unavailableNote}</p>
        )}
      </div>
    </div>
  );
}
