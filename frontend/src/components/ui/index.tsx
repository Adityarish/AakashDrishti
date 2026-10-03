"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------- Button */
type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ice" | "ghost" | "soft" | "danger";
  size?: "sm" | "md" | "lg";
  loading?: boolean;
};

export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn("btn", `btn-${variant}`, size === "sm" && "btn-sm", size === "lg" && "btn-lg", className)}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={1.5} />}
      {children}
    </button>
  );
}

/* ---------------------------------------------------------------- Surfaces */
export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={cn("card", className)}>
      {children}
    </div>
  );
}

export function Panel({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={cn("frost rounded-lg", className)}>
      {children}
    </div>
  );
}

/* ---------------------------------------------------------------- Badge */
const TONES = {
  ice: "bg-glacier-100 text-deep-ice border-glacier-300",
  orange: "bg-station-orange/10 text-station-orange border-station-orange/30",
  aurora: "bg-aurora/10 text-[#4d6b3f] border-aurora/30",
  krill: "bg-krill/10 text-krill border-krill/30",
  muted: "bg-frost text-slate-ice border-glacier-300/60",
  night: "bg-polar-night text-white border-polar-night",
} as const;

export function Badge({ tone = "ice", className, children }: { tone?: keyof typeof TONES; className?: string; children: React.ReactNode }) {
  return <span className={cn("chip", TONES[tone], className)}>{children}</span>;
}

/* ---------------------------------------------------------------- Motion helpers */
export function Reveal({
  children,
  delay = 0,
  className,
  y = 16,
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
  y?: number;
}) {
  const reduced = useReducedMotion();
  return (
    <motion.div
      className={className}
      initial={reduced ? false : { opacity: 0, y }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5, delay, ease: [0.22, 1, 0.36, 1] }}
    >
      {children}
    </motion.div>
  );
}

export function useCountUp(target: number | null | undefined, durationMs = 800): number {
  const reduced = useReducedMotion();
  const [value, setValue] = useState(0);
  const previous = useRef(0);

  useEffect(() => {
    if (target === null || target === undefined || !Number.isFinite(target)) return;
    if (reduced) {
      previous.current = target;
      setValue(target);
      return;
    }
    const from = previous.current;
    const start = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      setValue(from + (target - from) * eased);
      if (t < 1) frame = requestAnimationFrame(tick);
      else previous.current = target;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [target, durationMs, reduced]);

  return value;
}

/* ---------------------------------------------------------------- Stat */
export function Stat({
  label,
  value,
  unit,
  digits = 1,
  hint,
  tone = "default",
  tag,
  className,
}: {
  label: string;
  value: number | null | undefined;
  unit?: string;
  digits?: number;
  hint?: string;
  tone?: "default" | "orange" | "aurora" | "krill";
  tag?: string;
  className?: string;
}) {
  const animated = useCountUp(value);
  const color = tone === "orange" ? "text-station-orange" : tone === "aurora" ? "text-[#4d6b3f]" : tone === "krill" ? "text-krill" : "text-polar-night";
  const missing = value === null || value === undefined || !Number.isFinite(value);
  return (
    <div className={cn("card p-4", className)}>
      <div className="flex items-start justify-between gap-2">
        <p className="eyebrow !text-slate-ice">{label}</p>
        {tag && <Badge tone="muted">{tag}</Badge>}
      </div>
      <p className={cn("mono mt-2 text-[1.75rem] font-semibold leading-none", color)}>
        {missing ? "n/a" : animated.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}
        {unit && !missing && <span className="ml-1 text-sm font-medium text-slate-ice">{unit}</span>}
      </p>
      {hint && <p className="mt-2 text-xs leading-snug text-slate-ice">{hint}</p>}
    </div>
  );
}

/* ---------------------------------------------------------------- Form controls */
export function Field({ label, hint, children, className }: { label: string; hint?: string; children: React.ReactNode; className?: string }) {
  return (
    <label className={cn("block", className)}>
      <span className="mb-1.5 block text-xs font-semibold text-deep-ice">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[0.72rem] leading-snug text-slate-ice">{hint}</span>}
    </label>
  );
}

export function Slider({
  value,
  min,
  max,
  step = 1,
  onChange,
  onCommit,
  label,
  format,
  disabled,
}: {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (value: number) => void;
  onCommit?: (value: number) => void;
  label?: string;
  format?: (value: number) => string;
  disabled?: boolean;
}) {
  const fill = max > min ? ((value - min) / (max - min)) * 100 : 0;
  return (
    <div className={disabled ? "opacity-50" : undefined}>
      {label && (
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold text-deep-ice">{label}</span>
          <span className="mono text-xs font-semibold text-polar-night">{format ? format(value) : value}</span>
        </div>
      )}
      <input
        type="range"
        className="slider"
        style={{ ["--fill" as string]: `${fill}%` }}
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        onPointerUp={(e) => onCommit?.(Number((e.target as HTMLInputElement).value))}
        onKeyUp={(e) => onCommit?.(Number((e.target as HTMLInputElement).value))}
      />
    </div>
  );
}

export function Switch({ checked, onChange, label, hint }: { checked: boolean; onChange: (checked: boolean) => void; label: string; hint?: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="ctl flex items-start gap-3 text-left !bg-transparent hover:!bg-glacier-100/60"
    >
      <span
        className={cn(
          "relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors",
          checked ? "bg-station-orange" : "bg-glacier-300",
        )}
      >
        <span
          className={cn("absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all", checked ? "left-[1.1rem]" : "left-0.5")}
        />
      </span>
      <span>
        <span className="block text-sm font-semibold text-polar-night">{label}</span>
        {hint && <span className="mt-0.5 block text-xs leading-snug text-slate-ice">{hint}</span>}
      </span>
    </button>
  );
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  className,
}: {
  value: T;
  options: { value: T; label: string; icon?: React.ReactNode }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <div className={cn("inline-flex rounded-lg border border-glacier-300 bg-glacier-100 p-1", className)} role="tablist">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all",
            value === option.value ? "bg-white text-deep-ice shadow-sm" : "text-slate-ice hover:text-deep-ice",
          )}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

export function ProgressBar({ value, tone = "orange", className }: { value: number; tone?: "orange" | "ice" | "aurora"; className?: string }) {
  const color = tone === "orange" ? "bg-station-orange" : tone === "aurora" ? "bg-aurora" : "bg-deep-ice";
  return (
    <div className={cn("h-2 w-full overflow-hidden rounded-full bg-glacier-100", className)}>
      <div className={cn("h-full rounded-full transition-[width] duration-500 ease-out", color)} style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
    </div>
  );
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={cn("animate-spin text-deep-ice", className ?? "h-5 w-5")} strokeWidth={1.5} />;
}

/* ---------------------------------------------------------------- Layout bits */
export function EmptyState({ title, body, action, icon }: { title: string; body: string; action?: React.ReactNode; icon?: React.ReactNode }) {
  return (
    <div className="card contour-bg relative overflow-hidden px-6 py-14 text-center">
      <div className="absolute inset-0 bg-gradient-to-b from-frost/70 to-frost" />
      <div className="relative mx-auto max-w-md">
        {icon && <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-glacier-100 text-deep-ice">{icon}</div>}
        <h3 className="text-lg font-semibold text-polar-night">{title}</h3>
        <p className="mt-2 text-sm leading-relaxed text-slate-ice">{body}</p>
        {action && <div className="mt-5 flex justify-center">{action}</div>}
      </div>
    </div>
  );
}

export function PageHeader({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="max-w-2xl">
        {eyebrow && <p className="eyebrow">{eyebrow}</p>}
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-polar-night sm:text-[2.1rem]">{title}</h1>
        {description && <p className="mt-2 text-[0.95rem] leading-relaxed text-slate-ice">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function ErrorNote({ message, className }: { message: string; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-krill/30 bg-krill/5 px-4 py-3 text-sm leading-relaxed text-krill", className)} role="alert">
      {message}
    </div>
  );
}

export function InfoNote({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-lg border border-glacier-300 bg-glacier-100/60 px-4 py-3 text-xs leading-relaxed text-deep-ice", className)}>
      {children}
    </div>
  );
}
