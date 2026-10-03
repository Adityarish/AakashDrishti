"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Maximize2, Minus, Plus } from "lucide-react";

import { cn } from "@/lib/utils";

export interface MapOverlay {
  src: string;
  opacity: number;
}

export interface MapMarker {
  col: number;
  row: number;
  label?: string;
  tone?: "orange" | "ice" | "aurora" | "krill";
  /** Overrides `tone` with an exact CSS colour (used to match a legend). */
  color?: string;
  radiusPx?: number;
  /** Draw only the radius ring, not the centre dot. */
  ringOnly?: boolean;
}

export interface MapLine {
  c0: number;
  r0: number;
  c1: number;
  r1: number;
  tone?: "orange" | "ice";
}

const TONE_COLOR = { orange: "#a88a2c", ice: "#3c5a33", aurora: "#5f8a45", krill: "#a3392c" };

interface Props {
  width: number;
  height: number;
  base: string;
  overlays?: MapOverlay[];
  /** When set, the right side of a draggable divider shows this image instead of `base`. */
  compare?: string | null;
  compareLabels?: [string, string];
  markers?: MapMarker[];
  lines?: MapLine[];
  onHover?: (point: { col: number; row: number } | null, event: React.PointerEvent) => void;
  onPick?: (col: number, row: number) => void;
  cursor?: string;
  className?: string;
}

export function MapView({ width, height, base, overlays = [], compare, compareLabels, markers = [], lines = [], onHover, onPick, cursor, className }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [view, setView] = useState({ z: 1, tx: 0, ty: 0 });
  const [split, setSplit] = useState(50);
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean } | null>(null);
  const splitDrag = useRef(false);

  // Until the container has been measured (box 0x0) fit would be 0 and collapse the image, so fall back to 1.
  const fit = useMemo(() => (box.w > 0 && box.h > 0 ? Math.min(box.w / width, box.h / height) : 1), [box, width, height]);

  const reset = useCallback(() => {
    setView({ z: 1, tx: (box.w - width * fit) / 2, ty: (box.h - height * fit) / 2 });
  }, [box, width, height, fit]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const measure = () => setBox({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const firstFit = useRef(true);
  useEffect(() => {
    if (firstFit.current && box.w > 0) {
      firstFit.current = false;
      reset();
    }
  }, [box, reset]);

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      const rect = el.getBoundingClientRect();
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      setView((v) => {
        const nz = Math.min(24, Math.max(0.6, v.z * Math.exp(-event.deltaY * 0.0016)));
        const k = nz / v.z;
        return { z: nz, tx: px - (px - v.tx) * k, ty: py - (py - v.ty) * k };
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const toImage = (clientX: number, clientY: number) => {
    const rect = host.current!.getBoundingClientRect();
    const scale = fit * view.z;
    return { col: (clientX - rect.left - view.tx) / scale, row: (clientY - rect.top - view.ty) / scale };
  };

  const onPointerDown = (event: React.PointerEvent) => {
    if (splitDrag.current) return;
    host.current?.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, y: event.clientY, tx: view.tx, ty: view.ty, moved: false };
  };
  const onPointerMove = (event: React.PointerEvent) => {
    if (splitDrag.current && host.current) {
      const rect = host.current.getBoundingClientRect();
      const imageLeft = view.tx;
      const imageWidth = width * fit * view.z;
      setSplit(Math.min(100, Math.max(0, ((event.clientX - rect.left - imageLeft) / imageWidth) * 100)));
      return;
    }
    const d = drag.current;
    if (d) {
      const dx = event.clientX - d.x;
      const dy = event.clientY - d.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
      if (d.moved) setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }));
      return;
    }
    if (onHover) {
      const p = toImage(event.clientX, event.clientY);
      onHover(p.col >= 0 && p.row >= 0 && p.col < width && p.row < height ? p : null, event);
    }
  };
  const onPointerUp = (event: React.PointerEvent) => {
    splitDrag.current = false;
    const d = drag.current;
    drag.current = null;
    if (d && !d.moved && onPick) {
      const p = toImage(event.clientX, event.clientY);
      if (p.col >= 0 && p.row >= 0 && p.col < width && p.row < height) onPick(p.col, p.row);
    }
  };

  const scale = fit * view.z;
  const zoomBy = (factor: number) =>
    setView((v) => {
      const nz = Math.min(24, Math.max(0.6, v.z * factor));
      const k = nz / v.z;
      const cx = box.w / 2;
      const cy = box.h / 2;
      return { z: nz, tx: cx - (cx - v.tx) * k, ty: cy - (cy - v.ty) * k };
    });

  return (
    <div
      ref={host}
      className={cn("relative touch-none select-none overflow-hidden rounded-lg border border-glacier-300/60 bg-[#efe8d0]", className)}
      style={{ cursor: cursor ?? (drag.current ? "grabbing" : "crosshair") }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={(event) => {
        if (!drag.current) onHover?.(null, event);
      }}
      onDoubleClick={reset}
    >
      <div className="absolute left-0 top-0 origin-top-left" style={{ width, height, transform: `translate(${view.tx}px, ${view.ty}px) scale(${scale})`, willChange: "transform", imageRendering: view.z > 3 ? "pixelated" : "auto" }}>
        {/* eslint-disable @next/next/no-img-element */}
        <img src={base} alt="" draggable={false} decoding="async" className="absolute inset-0 h-full w-full" />
        {compare && <img src={compare} alt="" draggable={false} decoding="async" className="absolute inset-0 h-full w-full" style={{ clipPath: `inset(0 0 0 ${split}%)` }} />}
        {overlays.map((overlay, index) => (
          <img key={index} src={overlay.src} alt="" draggable={false} className="pointer-events-none absolute inset-0 h-full w-full" style={{ opacity: overlay.opacity }} />
        ))}
        {/* eslint-enable @next/next/no-img-element */}
        <svg className="pointer-events-none absolute inset-0 h-full w-full overflow-visible" viewBox={`0 0 ${width} ${height}`}>
          {lines.map((line, index) => (
            <g key={index}>
              <line x1={line.c0} y1={line.r0} x2={line.c1} y2={line.r1} stroke="#fff" strokeWidth={4.5 / scale} strokeLinecap="round" />
              <line x1={line.c0} y1={line.r0} x2={line.c1} y2={line.r1} stroke={TONE_COLOR[line.tone ?? "orange"]} strokeWidth={2.4 / scale} strokeLinecap="round" />
            </g>
          ))}
          {markers.map((marker, index) => {
            const color = marker.color ?? TONE_COLOR[marker.tone ?? "orange"];
            return (
              <g key={index}>
                {marker.radiusPx && <circle cx={marker.col} cy={marker.row} r={marker.radiusPx} fill={color} fillOpacity={0.12} stroke={color} strokeWidth={1.6 / scale} strokeDasharray={`${5 / scale} ${4 / scale}`} />}
                {!marker.ringOnly && <circle cx={marker.col} cy={marker.row} r={7 / scale} fill={color} stroke="#fff" strokeWidth={2.4 / scale} />}
                {marker.label && !marker.ringOnly && (
                  <text x={marker.col} y={marker.row + 0.4 / scale} textAnchor="middle" dominantBaseline="middle" fontSize={9 / scale} fontWeight={800} fill="#fff" style={{ fontFamily: "var(--font-jetbrains-mono)" }}>
                    {marker.label}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>

      {compare && (
        <>
          <div
            className="absolute inset-y-0 z-10 w-9 -translate-x-1/2 cursor-ew-resize"
            style={{ left: view.tx + (split / 100) * width * scale }}
            onPointerDown={(event) => {
              event.stopPropagation();
              splitDrag.current = true;
              host.current?.setPointerCapture(event.pointerId);
            }}
          >
            <div className="absolute inset-y-0 left-1/2 w-[3px] -translate-x-1/2 bg-white shadow-[0_0_0_1px_rgba(11,37,69,0.25)]" />
            <div className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-[3px] border-station-orange bg-white text-[0.7rem] font-semibold text-station-orange shadow-lg">⇄</div>
          </div>
          {compareLabels && (
            <>
              <span className="hud pointer-events-none absolute left-3 top-3 px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-wider">{compareLabels[0]}</span>
              <span className="hud pointer-events-none absolute right-3 top-3 px-2.5 py-1 text-[0.68rem] font-semibold uppercase tracking-wider">{compareLabels[1]}</span>
            </>
          )}
        </>
      )}

      <div className="hud absolute bottom-3 right-3 flex flex-col overflow-hidden !rounded-lg" onPointerDown={(e) => e.stopPropagation()}>
        <button className="flex h-9 w-9 items-center justify-center hover:bg-white/80" onClick={() => zoomBy(1.5)} aria-label="Zoom in">
          <Plus className="h-4 w-4" strokeWidth={2} />
        </button>
        <button className="flex h-9 w-9 items-center justify-center border-y border-white/70 hover:bg-white/80" onClick={() => zoomBy(1 / 1.5)} aria-label="Zoom out">
          <Minus className="h-4 w-4" strokeWidth={2} />
        </button>
        <button className="flex h-9 w-9 items-center justify-center hover:bg-white/80" onClick={reset} aria-label="Fit to view">
          <Maximize2 className="h-4 w-4" strokeWidth={1.75} />
        </button>
      </div>
    </div>
  );
}
