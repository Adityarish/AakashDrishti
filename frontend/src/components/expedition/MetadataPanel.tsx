"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "motion/react";

import { Badge } from "@/components/ui";
import { fmtBytes, fmtLonLat } from "@/lib/format";
import type { UploadInfo } from "@/lib/sceneTypes";

/** Reveals a value character by character once, so detection feels alive but never blocks. */
function Typed({ text, delay = 0 }: { text: string; delay?: number }) {
  const reduced = useReducedMotion();
  const [shown, setShown] = useState(reduced ? text.length : 0);

  useEffect(() => {
    if (reduced) {
      setShown(text.length);
      return;
    }
    setShown(0);
    let index = 0;
    let interval: ReturnType<typeof setInterval> | undefined;
    const timeout = setTimeout(() => {
      interval = setInterval(() => {
        index += 1;
        setShown(index);
        if (index >= text.length && interval) clearInterval(interval);
      }, 16);
    }, delay);
    return () => {
      clearTimeout(timeout);
      if (interval) clearInterval(interval);
    };
  }, [text, delay, reduced]);

  return (
    <span>
      {text.slice(0, shown)}
      {shown < text.length && <span className="animate-pulse text-station-orange">▍</span>}
    </span>
  );
}

export function MetadataPanel({ info }: { info: UploadInfo }) {
  const geo = info.geo;
  const rows: [string, string][] = [
    ["File", info.filename],
    ["Size", fmtBytes(info.size_bytes)],
    ["Dimensions", `${info.width.toLocaleString()} × ${info.height.toLocaleString()} px`],
    ["Format", info.file_format.toUpperCase()],
    ["Bands · bit depth", `${info.band_count} · ${info.bit_depth}-bit`],
    ["CRS", geo?.crs ?? "none detected"],
    ["Centre", info.bounds_wgs84 ? fmtLonLat((info.bounds_wgs84[0] + info.bounds_wgs84[2]) / 2, (info.bounds_wgs84[1] + info.bounds_wgs84[3]) / 2) : "none detected"],
    ["GSD", info.gsd_m ? `${info.gsd_m.toFixed(3)} m / px` : "unknown (override below)"],
    ["Sun azimuth", info.sun_azimuth_deg !== null ? `${info.sun_azimuth_deg.toFixed(1)}°` : "not in metadata"],
    ["Sun elevation", info.sun_elevation_deg !== null ? `${info.sun_elevation_deg.toFixed(1)}°` : "not in metadata"],
  ];

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="eyebrow">Detected metadata</p>
          <p className="mt-1 text-sm text-slate-ice">Read from the file itself, never guessed from its extension.</p>
        </div>
        {info.mode === "absolute" ? (
          <Badge tone="orange" className="!px-3.5 !py-1.5 !text-xs">
            ABSOLUTE · metres
          </Badge>
        ) : (
          <Badge tone="ice" className="!px-3.5 !py-1.5 !text-xs">
            RELATIVE · no units
          </Badge>
        )}
      </div>
      <dl className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2">
        {rows.map(([label, value], index) => (
          <div key={label} className="flex items-baseline justify-between gap-4 border-b border-glacier-300/40 pb-2">
            <dt className="text-xs font-semibold text-slate-ice">{label}</dt>
            <dd className="mono truncate text-right text-[0.82rem] font-semibold text-polar-night" title={value}>
              <Typed text={value} delay={index * 90} />
            </dd>
          </div>
        ))}
      </dl>
      {info.mode === "relative" && (
        <p className="mt-4 rounded-lg bg-glacier-100/70 px-3.5 py-2.5 text-xs leading-relaxed text-deep-ice">
          No spatial metadata found, so the pixel size is unknown. Heights will be <b>approximate metres</b> from the model&apos;s native scale (it assumes about 0.5 m per pixel).
          For accurate heights, supply the image&apos;s real GSD, and a sun elevation for the shadow cross-check, in the next step.
        </p>
      )}
      {info.notes.length > 0 && <ul className="mt-3 space-y-1 text-xs text-slate-ice">{info.notes.map((note) => <li key={note}>· {note}</li>)}</ul>}
    </div>
  );
}
