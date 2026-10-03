"use client";

import { useEffect, useState } from "react";
import { Box, Download, FileJson, Image as ImageIcon, Layers, MapPinned } from "lucide-react";

import { useSurvey } from "@/components/survey/SurveyContext";
import { Badge, InfoNote, Reveal } from "@/components/ui";
import { API_BASE_URL, outputUrl } from "@/lib/api/survey";
import { fmtBytes } from "@/lib/format";

interface Item {
  key: string;
  title: string;
  format: string;
  description: string;
  group: "Rasters" | "3D" | "Previews" | "Data";
  icon: typeof Layers;
  geo: boolean;
}

const ITEMS: Item[] = [
  { key: "dsm_tif", title: "DSM", format: "Cloud-Optimized GeoTIFF", description: "Surface elevation, float32, nodata -9999, overviews", group: "Rasters", icon: Layers, geo: true },
  { key: "ndsm_tif", title: "nDSM", format: "Cloud-Optimized GeoTIFF", description: "Height above ground (DSM minus terrain)", group: "Rasters", icon: Layers, geo: true },
  { key: "uncertainty_tif", title: "Uncertainty", format: "Cloud-Optimized GeoTIFF", description: "Per-pixel standard deviation over 8 test-time views", group: "Rasters", icon: Layers, geo: true },
  { key: "slope_tif", title: "Slope", format: "Cloud-Optimized GeoTIFF", description: "Degrees from horizontal", group: "Rasters", icon: Layers, geo: true },
  { key: "aspect_tif", title: "Aspect", format: "Cloud-Optimized GeoTIFF", description: "Downslope direction, degrees clockwise from north", group: "Rasters", icon: Layers, geo: true },
  { key: "rdsm_png", title: "Relative DSM", format: "16-bit PNG + world file", description: "Normalised 2nd-98th percentile, for scenes without absolute scale", group: "Rasters", icon: ImageIcon, geo: false },
  { key: "terrain_glb", title: "Terrain mesh", format: "GLB", description: "Adaptive RTIN triangulation with the optical image as texture", group: "3D", icon: Box, geo: false },
  { key: "terrain_obj_zip", title: "Terrain mesh (OBJ)", format: "OBJ + texture (zip)", description: "For Blender, MeshLab and other DCC tools", group: "3D", icon: Box, geo: false },
  { key: "hillshade_png", title: "Hillshade", format: "PNG", description: "Shaded relief, 8-bit", group: "Previews", icon: ImageIcon, geo: false },
  { key: "height_color_png", title: "Height colour map", format: "PNG", description: "Glacier colormap of the DSM", group: "Previews", icon: ImageIcon, geo: false },
  { key: "slope_color_png", title: "Slope hazard colours", format: "PNG", description: "Yellow to red gradient", group: "Previews", icon: ImageIcon, geo: false },
  { key: "uncertainty_color_png", title: "Uncertainty colours", format: "PNG", description: "White to orange", group: "Previews", icon: ImageIcon, geo: false },
  { key: "landcover_png", title: "Land cover", format: "PNG", description: "Six heuristic classes", group: "Previews", icon: ImageIcon, geo: false },
  { key: "validation_error_map", title: "Error map", format: "PNG (RGBA)", description: "Predicted minus reference, from the validation lab", group: "Previews", icon: ImageIcon, geo: false },
  { key: "metadata_json", title: "Run metadata", format: "JSON", description: "Calibration sources, timings, options, sun geometry", group: "Data", icon: FileJson, geo: false },
  { key: "buildings_json", title: "Building footprints", format: "JSON", description: "Polygons with height, confidence and shadow estimate", group: "Data", icon: FileJson, geo: false },
  { key: "disaster_zones_json", title: "Hazard zones", format: "GeoJSON-style JSON", description: "Landing, flood-risk and fire-access zones", group: "Data", icon: FileJson, geo: false },
  { key: "scene_json", title: "Scene manifest", format: "JSON", description: "Chunks, LOD files, overlays, sun and scale for the 3D viewer", group: "Data", icon: FileJson, geo: false },
];

const GROUPS: Item["group"][] = ["Rasters", "3D", "Previews", "Data"];

export default function Downloads() {
  const { job, metadata } = useSurvey();
  const [sizes, setSizes] = useState<Record<string, number>>({});

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const found: Record<string, number> = {};
      await Promise.all(
        ITEMS.filter((i) => job.outputs[i.key]).map(async (item) => {
          try {
            const response = await fetch(outputUrl(job.outputs[item.key]), { method: "HEAD" });
            const length = Number(response.headers.get("content-length"));
            if (length) found[item.key] = length;
          } catch {
            /* size stays unknown */
          }
        }),
      );
      if (!cancelled) setSizes(found);
    })();
    return () => {
      cancelled = true;
    };
  }, [job.outputs]);

  const available = ITEMS.filter((item) => job.outputs[item.key]);

  return (
    <div className="mx-auto w-full max-w-[1200px] flex-1 space-y-8 px-5 py-8 sm:px-8">
      <div className="max-w-3xl">
        <p className="eyebrow">Downloads</p>
        <h1 className="mt-1 text-3xl font-semibold tracking-tight text-polar-night">Standards-compliant outputs.</h1>
        <p className="mt-2 text-[0.95rem] leading-relaxed text-slate-ice">
          Every raster is a Cloud-Optimized GeoTIFF that opens directly in QGIS or ArcGIS, and the mesh is a GLB and OBJ for Blender. This is operational data, not a screenshot.
        </p>
      </div>

      {GROUPS.map((group) => {
        const items = available.filter((i) => i.group === group);
        if (items.length === 0) return null;
        return (
          <section key={group}>
            <h2 className="eyebrow mb-3">{group}</h2>
            <div className="grid gap-3 sm:grid-cols-2">
              {items.map((item, index) => (
                <Reveal key={item.key} delay={index * 0.03}>
                  <div className="card card-lift flex items-center gap-4 p-4">
                    <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-glacier-100 text-deep-ice">
                      <item.icon className="h-5 w-5" strokeWidth={1.5} />
                    </span>
                    <div className="min-w-0 flex-1">
                      <p className="font-semibold text-polar-night">{item.title}</p>
                      <p className="text-xs leading-snug text-slate-ice">{item.description}</p>
                      <div className="mt-1.5 flex flex-wrap items-center gap-2">
                        <Badge tone="muted">{item.format}</Badge>
                        {sizes[item.key] && <span className="mono text-[0.7rem] text-slate-ice">{fmtBytes(sizes[item.key])}</span>}
                        {item.geo && <span className="mono text-[0.7rem] text-slate-ice">{metadata.crs ?? "no CRS (plain image)"}</span>}
                      </div>
                    </div>
                    <a href={outputUrl(job.outputs[item.key])} download className="btn btn-primary btn-sm" aria-label={`Download ${item.title}`}>
                      <Download className="h-4 w-4" strokeWidth={1.75} />
                    </a>
                  </div>
                </Reveal>
              ))}
            </div>
          </section>
        );
      })}

      <Reveal>
        <div className="card p-6">
          <div className="flex items-start gap-4">
            <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-station-orange/10 text-station-orange"><MapPinned className="h-5 w-5" strokeWidth={1.5} /></span>
            <div>
              <h3 className="text-lg font-semibold text-polar-night">Open the DSM in QGIS</h3>
              <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm leading-relaxed text-slate-ice">
                <li>In QGIS 3.x choose <b className="text-deep-ice">Layer → Add Layer → Add Raster Layer</b> and select the downloaded DSM GeoTIFF.</li>
                <li>{metadata.crs ? <>It carries <span className="mono font-semibold text-deep-ice">{metadata.crs}</span>, so it lines up on the map with no manual georeferencing.</> : "This scene has no CRS (plain image); it opens as an image-space raster."}</li>
                <li>Use <b className="text-deep-ice">Singleband pseudocolor</b> for elevation, or stack the slope and hillshade rasters for shaded relief.</li>
              </ol>
              {metadata.dsm_kind !== "absolute_dsm" && <InfoNote className="mt-4">This scene is {metadata.dsm_kind === "pseudo_metric" ? "pseudo-metric (metres above local ground, no absolute datum)" : "relative (no metric scale)"}; values are not absolute elevations.</InfoNote>}
              <p className="mt-3 text-xs text-slate-ice">Files are served from <span className="mono">{API_BASE_URL}</span>.</p>
            </div>
          </div>
        </div>
      </Reveal>
    </div>
  );
}
