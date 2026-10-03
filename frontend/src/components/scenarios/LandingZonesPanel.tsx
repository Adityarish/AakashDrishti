"use client";

import { useEffect, useState } from "react";

import { getDisasterZones } from "@/lib/api/pipeline";
import type { DisasterZone } from "@/lib/types/results";

export type AircraftType = "plane" | "helicopter";

export interface SelectedLandingZone {
  centerPx: [number, number];
  widthM: number;
  lengthM: number;
  angleDeg: number;
  fits: boolean | null;
  /** "meters" = widthM/lengthM are real calibrated distances; "pixels" =
   * an illustrative 1px~=1m visualization (this job isn't georeferenced). */
  spacingUnits: "meters" | "pixels";
}

interface LandingZonesPanelProps {
  jobId: string;
  aircraftType: AircraftType;
  onAircraftTypeChange: (type: AircraftType) => void;
  onSelectZone?: (zone: SelectedLandingZone) => void;
}

type FetchState = { status: "loading" | "ready" | "unavailable"; zones: DisasterZone[] };

/** Reads a numeric field out of a zone's free-form `properties` bag.
 * Real backend keys (app/buildings/disaster.py:find_emergency_landing_zones):
 * area_px, slope_variance_deg2, width_m, length_m, angle_deg, center_px. */
function num(properties: Record<string, unknown> | undefined, key: string): number | null {
  const val = properties?.[key];
  return typeof val === "number" && Number.isFinite(val) ? val : null;
}

function centerPxOf(properties: Record<string, unknown> | undefined): [number, number] | null {
  const val = properties?.["center_px"];
  if (Array.isArray(val) && val.length === 2 && typeof val[0] === "number" && typeof val[1] === "number") {
    return [val[0], val[1]];
  }
  return null;
}

function aircraftFitOf(properties: Record<string, unknown> | undefined): { fits: boolean | null } | null {
  const val = properties?.["aircraft_fit"];
  if (val && typeof val === "object" && "fits" in val) {
    return { fits: (val as { fits: boolean | null }).fits };
  }
  return null;
}

export function LandingZonesPanel({ jobId, aircraftType, onAircraftTypeChange, onSelectZone }: LandingZonesPanelProps) {
  const [state, setState] = useState<FetchState>({ status: "loading", zones: [] });

  useEffect(() => {
    let cancelled = false;
    getDisasterZones(jobId, aircraftType)
      .then((zones) => !cancelled && setState({ status: "ready", zones }))
      .catch(() => !cancelled && setState({ status: "unavailable", zones: [] }));
    return () => {
      cancelled = true;
    };
  }, [jobId, aircraftType]);

  const landingZones = state.zones.filter((z) => z.type === "landing_zone");

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-base font-semibold text-foreground">Emergency Landing Zones</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Ranked, low-slope, obstacle-free candidates from the real DSM, compared against an illustrative
          reference footprint for the selected aircraft. Heuristic decision support, not a certified survey.
        </p>
      </div>

      <div className="flex gap-2">
        {(["helicopter", "plane"] as const).map((type) => (
          <button
            key={type}
            type="button"
            onClick={() => onAircraftTypeChange(type)}
            className={`rounded-lg px-3 py-1.5 text-xs font-semibold capitalize transition-colors ${
              aircraftType === type
                ? "bg-primary text-primary-foreground"
                : "border border-border text-muted-foreground hover:border-primary/40 hover:text-foreground"
            }`}
          >
            {type}
          </button>
        ))}
      </div>

      <div className="glass-panel rounded-2xl p-5">
        {state.status === "loading" && <p className="text-sm text-muted-foreground">Loading disaster-zone data...</p>}

        {state.status === "unavailable" && (
          <p className="text-sm text-muted-foreground">
            Disaster-zone data isn&apos;t reachable for this job yet (endpoint may still be deploying, or this job
            predates the feature).
          </p>
        )}

        {state.status === "ready" && landingZones.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No candidate landing zones were identified for this job&apos;s terrain.
          </p>
        )}

        {state.status === "ready" && landingZones.length > 0 && (
          <div className="space-y-3">
            <p className="text-sm font-medium text-foreground">
              {landingZones.length} Candidate Landing Zone{landingZones.length === 1 ? "" : "s"}
            </p>
            <ol className="space-y-2">
              {landingZones.map((zone, i) => {
                const widthM = num(zone.properties, "width_m");
                const lengthM = num(zone.properties, "length_m");
                const angleDeg = num(zone.properties, "angle_deg") ?? 0;
                const slopeVariance = num(zone.properties, "slope_variance_deg2");
                const center = centerPxOf(zone.properties);
                const fit = aircraftFitOf(zone.properties);
                const isIllustrative = zone.properties?.["spacing_units"] === "pixels";
                const selectable = center != null && widthM != null && lengthM != null;

                return (
                  <li key={i} className="rounded-lg border border-border bg-muted/20 p-4">
                    <div className="mb-1 flex items-center justify-between">
                      <span className="text-sm font-semibold text-foreground">Zone #{i + 1}</span>
                      {fit && fit.fits !== null && (
                        <span
                          className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium ${
                            fit.fits
                              ? "border border-secondary/30 bg-secondary/10 text-secondary"
                              : "border border-destructive/30 bg-destructive/10 text-destructive"
                          }`}
                        >
                          {fit.fits ? "Fits" : "Too Small"}
                        </span>
                      )}
                    </div>
                    <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-muted-foreground sm:grid-cols-3">
                      <dt>Dimensions</dt>
                      <dd className="col-span-2 text-foreground">
                        {widthM !== null && lengthM !== null
                          ? `${widthM.toFixed(1)} ${isIllustrative ? "px" : "m"} × ${lengthM.toFixed(1)} ${isIllustrative ? "px" : "m"}`
                          : "n/a"}
                      </dd>
                      <dt>Slope variance</dt>
                      <dd className="col-span-2 text-foreground">
                        {slopeVariance !== null ? `${slopeVariance.toFixed(3)} deg² (lower = flatter)` : "n/a"}
                      </dd>
                    </dl>
                    {isIllustrative && (widthM !== null || lengthM !== null) && (
                      <p className="mt-2 text-[11px] text-muted-foreground">
                        This job isn&apos;t georeferenced, so dimensions/fit above use an illustrative 1px&asymp;1m
                        scale, not a calibrated real-world distance.
                      </p>
                    )}
                    {zone.notes && <p className="mt-2 text-xs text-muted-foreground">{zone.notes}</p>}
                    {selectable && (
                      <button
                        type="button"
                        onClick={() =>
                          onSelectZone?.({
                            centerPx: center!,
                            widthM: widthM!,
                            lengthM: lengthM!,
                            angleDeg,
                            fits: fit?.fits ?? null,
                            spacingUnits: isIllustrative ? "pixels" : "meters",
                          })
                        }
                        className="mt-3 w-full rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90"
                      >
                        Show on 3D Terrain
                      </button>
                    )}
                  </li>
                );
              })}
            </ol>
          </div>
        )}
      </div>
    </div>
  );
}
