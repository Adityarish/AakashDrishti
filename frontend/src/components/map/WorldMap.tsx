"use client";

import "leaflet/dist/leaflet.css";

import { useEffect, useRef } from "react";
import type { Map as LeafletMap } from "leaflet";

import type { JobLocation } from "@/lib/api/locations";

const LAYERS = {
  Satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics",
    maxZoom: 19,
  },
  Streets: {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  },
} as const;

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string);
}

/** Hover card: the image preview sits above the pin, small, with the facts a reader needs to recognise the place. */
function previewHtml(loc: JobLocation): string {
  const [lon, lat] = loc.centre;
  const size = loc.widthPx && loc.pixelSizeM ? `${Math.round(loc.widthPx * loc.pixelSizeM)} m wide` : null;
  const facts = [`${lat.toFixed(4)}, ${lon.toFixed(4)}`, size, loc.buildings ? `${loc.buildings} buildings` : null].filter(Boolean).join(" · ");
  const image = loc.thumbnailUrl
    ? `<img src="${escapeHtml(loc.thumbnailUrl)}" alt="" style="display:block;width:168px;height:168px;object-fit:cover;border-radius:6px" />`
    : `<div style="width:168px;height:168px;display:flex;align-items:center;justify-content:center;background:#e8eef4;border-radius:6px;color:#5c7188;font-size:12px">no preview</div>`;
  return `<div style="width:168px">${image}<div style="margin-top:6px;font:600 12px system-ui;color:#0b2545;max-width:168px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHtml(loc.name)}</div><div style="font:11px system-ui;color:#5c7188;white-space:normal;line-height:1.35">${escapeHtml(facts)}</div></div>`;
}

const pinSvg = (color: string) =>
  `<svg width="30" height="40" viewBox="0 0 30 40" xmlns="http://www.w3.org/2000/svg"><path d="M15 39C15 39 28 24 28 14.5A13 13 0 0 0 2 14.5C2 24 15 39 15 39Z" fill="${color}" stroke="#fff" stroke-width="2.5"/><circle cx="15" cy="14.5" r="5" fill="#fff"/></svg>`;

interface Props {
  locations: JobLocation[];
  /** Called when a pin is clicked. */
  onSelect?: (loc: JobLocation) => void;
  className?: string;
}

/** World map with one pin per georeferenced scene. Hovering a pin shows the scene's image above it. */
export function WorldMap({ locations, onSelect, className }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  useEffect(() => {
    let cancelled = false;
    let instance: LeafletMap | null = null;

    (async () => {
      const L = (await import("leaflet")).default;
      if (cancelled || !host.current) return;

      instance = L.map(host.current, { worldCopyJump: true, zoomControl: true, minZoom: 2 }).setView([20, 10], 2);
      const base = Object.fromEntries(
        Object.entries(LAYERS).map(([name, l]) => [name, L.tileLayer(l.url, { attribution: l.attribution, maxZoom: l.maxZoom })]),
      );
      base.Satellite.addTo(instance);
      L.control.layers(base, undefined, { position: "topright" }).addTo(instance);

      const points: [number, number][] = [];
      // site scenes last so their pin sits on top of any other job at the same place
      [...locations]
        .sort((a, b) => Number(a.isSite) - Number(b.isSite))
        .forEach((loc) => {
          const [lon, lat] = loc.centre;
          points.push([lat, lon]);
          const [w, s, e, n] = loc.bounds;
          const footprint = L.rectangle([[s, w], [n, e]], { color: "#f26b21", weight: 2, fillOpacity: 0.12 });
          const marker = L.marker([lat, lon], {
            icon: L.divIcon({ className: "", html: pinSvg(loc.isSite ? "#f26b21" : "#1f5f8b"), iconSize: [30, 40], iconAnchor: [15, 39] }),
            title: loc.name,
            riseOnHover: true,
          });
          // the card opens ABOVE the pin (direction top, offset past the pin's head)
          marker.bindTooltip(previewHtml(loc), { direction: "top", offset: [0, -40], opacity: 1, className: "scene-preview" });
          marker.on("mouseover", () => footprint.addTo(instance!));
          marker.on("mouseout", () => footprint.remove());
          marker.on("click", () => onSelectRef.current?.(loc));
          marker.addTo(instance!);
        });
      if (points.length) instance.fitBounds(L.latLngBounds(points).pad(0.6), { maxZoom: 5 });
    })();

    return () => {
      cancelled = true;
      instance?.remove();
    };
  }, [locations]);

  return (
    <>
      <style>{`.scene-preview{padding:8px;border-radius:10px;border:1px solid #c9d9e8;box-shadow:0 10px 30px rgba(11,37,69,.28)}`}</style>
      <div ref={host} className={className} role="application" aria-label="World map of processed scenes" />
    </>
  );
}
