"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { AppHeader } from "@/components/common/AppHeader";
import { ErrorBanner } from "@/components/common/ErrorBanner";
import { WorldMap } from "@/components/map/WorldMap";
import { ApiError } from "@/lib/api/client";
import { listLocations, type JobLocation } from "@/lib/api/locations";

export default function MapPage() {
  const [locations, setLocations] = useState<JobLocation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<JobLocation | null>(null);

  useEffect(() => {
    let cancelled = false;
    listLocations()
      .then((l) => {
        if (!cancelled) setLocations(l);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load scene locations.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex min-h-full flex-col">
      <AppHeader />
      <main className="mx-auto w-full max-w-[1600px] flex-1 px-6 py-8 xl:px-10">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">World map</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Every georeferenced scene, placed from the coordinates inside its GeoTIFF. Hover a pin for a quick look at the land; click it to open the scene.
            </p>
          </div>
          {locations && (
            <p className="text-sm text-muted-foreground">
              {locations.length} scene{locations.length === 1 ? "" : "s"} on the map
            </p>
          )}
        </div>

        {error && <ErrorBanner message={error} />}
        {!error && locations === null && <p className="text-sm text-muted-foreground">Loading locations…</p>}
        {locations && locations.length === 0 && (
          <p className="text-sm text-muted-foreground">No georeferenced scenes yet. Process a GeoTIFF and its location will appear here.</p>
        )}

        {locations && locations.length > 0 && (
          <div className="grid gap-5 lg:grid-cols-[1fr_20rem]">
            <WorldMap locations={locations} onSelect={setSelected} className="h-[72vh] min-h-[420px] overflow-hidden rounded-2xl border border-border" />
            <aside className="glass-panel rounded-2xl p-4">
              {selected ? (
                <div className="space-y-3">
                  {selected.thumbnailUrl && (
                    // eslint-disable-next-line @next/next/no-img-element -- backend-served preview
                    <img src={selected.thumbnailUrl} alt="" className="aspect-square w-full rounded-lg object-cover" />
                  )}
                  <p className="font-semibold text-foreground">{selected.name}</p>
                  <p className="text-xs text-muted-foreground">
                    {selected.centre[1].toFixed(5)}°, {selected.centre[0].toFixed(5)}°
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {selected.isSite && (
                      <Link href={`/site/${selected.jobId}`} className="rounded-lg bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground">
                        Open 3D scene and analysis
                      </Link>
                    )}
                    <Link href={`/history/${selected.jobId}`} className="rounded-lg border border-border px-3 py-1.5 text-sm font-semibold text-foreground">
                      Job details
                    </Link>
                  </div>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Select a pin to see the scene. Orange pins are hand-verified sites with a full 3D scene.</p>
              )}
              <ul className="mt-5 space-y-1.5 border-t border-border pt-4">
                {locations.map((l) => (
                  <li key={l.jobId}>
                    <button type="button" onClick={() => setSelected(l)} className="w-full truncate text-left text-sm text-muted-foreground hover:text-foreground">
                      {l.isSite ? "● " : "○ "}
                      {l.name}
                    </button>
                  </li>
                ))}
              </ul>
            </aside>
          </div>
        )}
      </main>
    </div>
  );
}
