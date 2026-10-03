interface ErrorBannerProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onDismiss }: ErrorBannerProps) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-400/30 bg-red-400/10 px-4 py-3 text-sm text-red-200">
      <svg viewBox="0 0 24 24" fill="none" className="mt-0.5 h-4 w-4 shrink-0 text-red-400" stroke="currentColor" strokeWidth={2}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 8v5M12 16h.01" strokeLinecap="round" />
      </svg>
      <p className="flex-1 leading-relaxed">{message}</p>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          className="shrink-0 text-red-400 hover:text-red-200"
          aria-label="Dismiss error"
        >
          ✕
        </button>
      )}
    </div>
  );
}
