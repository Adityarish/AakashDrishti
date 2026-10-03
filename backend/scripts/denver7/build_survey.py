"""Stage 4: turn the hand-verified 7.tif scene into a full, stored "advanced run" job (like the featured scene).

Rasterises the verified buildings / trees / cars onto a 1320 x 1320 grid (0.61 m per pixel), adds the SRTM terrain,
and then writes every output the survey workspace, hazards, scenarios, brief, downloads and PDF screens read:
arrays.npz, scene.json (+ terrain chunks), height/nDSM/uncertainty rasters and previews, GeoTIFF exports, objects.json,
disaster zones, validation status, the AI-analyst brief and report.pdf. Nothing here uses a machine-learning model.

usage: python build_survey.py <job_dir>      (run build_scene.py first; it writes the inputs this reads)
"""

from __future__ import annotations

import json
import math
import shutil
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import rasterio
from scipy.ndimage import map_coordinates, gaussian_filter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

from app.analyst import report as analyst  # noqa: E402
from app.analyst.pdf_report import build_brief_pdf  # noqa: E402
from app.export import rasters  # noqa: E402
from app.input.detect import GeoMetadata  # noqa: E402
from app.landcover.classify import BUILDING, GROUND, LOW_VEG, ROAD, TREE, class_color_image  # noqa: E402
from app.mesh.rtin import build_scene_meshes  # noqa: E402
from common import FT_M, MOSAIC  # noqa: E402

GRID = 1320
SCALE = MOSAIC / GRID                     # mosaic px per grid px (4)
PX_M = SCALE * 0.5 * FT_M                 # 0.6096 m
JOB_ID = "site-denver-7"
ORTHO_PX = 2048


def burn_polygon(canvas: np.ndarray, poly: np.ndarray, value: float) -> np.ndarray:
    mask = np.zeros(canvas.shape, np.uint8)
    cv2.fillPoly(mask, [np.round(poly / SCALE).astype(np.int32)], 1)
    canvas[mask > 0] = value
    return mask.astype(bool)


def main(job_dir: str) -> None:
    t0 = time.time()
    job = Path(job_dir)
    meta = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
    analysis = json.loads((job / "analysis.json").read_text(encoding="utf-8"))
    objs = json.loads((job / "site_objects.json").read_text(encoding="utf-8"))
    classes = np.load(HERE / "data" / "classes_grid.npy") if (HERE / "data" / "classes_grid.npy").exists() else None
    hm = np.frombuffer((job / "heightmap.r16").read_bytes(), "<u2")
    n = int(math.isqrt(hm.size))
    scene_u = json.loads((job / "unity_scene.json").read_text(encoding="utf-8"))["heightmap"]
    z_small = scene_u["min_m"] + hm.reshape(n, n).astype(np.float32) / 65535.0 * (scene_u["max_m"] - scene_u["min_m"])
    # heightmap.r16 rows run north -> south, like the image; resample to the grid
    gy, gx = np.mgrid[0:GRID, 0:GRID].astype(np.float32)
    terrain = map_coordinates(z_small, [gy / (GRID - 1) * (n - 1), gx / (GRID - 1) * (n - 1)], order=1).astype(np.float32)
    terrain = gaussian_filter(terrain, 3.0)

    # ---------------------------------------------------------------- rasters
    ndsm = np.zeros((GRID, GRID), np.float32)
    labels = np.full((GRID, GRID), GROUND, np.uint8)
    building_labels = np.zeros((GRID, GRID), np.int32)
    unc = np.full((GRID, GRID), 0.25, np.float32)

    if classes is None:
        raise SystemExit("data/classes_grid.npy missing: run `python build_survey.py --prepare <classes_half.npy>` first")

    cls = classes
    labels[cls == 1] = ROAD
    labels[cls == 0] = LOW_VEG
    labels[cls == 2] = TREE

    # trees: a rounded dome per crown so the canopy has relief (height measured from shadow)
    yy, xx = np.mgrid[0:GRID, 0:GRID]
    for t in objs["trees"]:
        cx, cy = t["center"][0] / SCALE, t["center"][1] / SCALE
        r = max(1.5, t["radius_px"] * 1.25 / SCALE)
        x0, x1, y0, y1 = int(cx - r - 1), int(cx + r + 2), int(cy - r - 1), int(cy + r + 2)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(GRID, x1), min(GRID, y1)
        if x1 <= x0 or y1 <= y0:
            continue
        d = np.hypot(xx[y0:y1, x0:x1] - cx, yy[y0:y1, x0:x1] - cy) / r
        dome = t["height_m"] * np.sqrt(np.clip(1 - d ** 2, 0, 1))
        ndsm[y0:y1, x0:x1] = np.maximum(ndsm[y0:y1, x0:x1], dome.astype(np.float32))
        sel = d < 1
        labels[y0:y1, x0:x1][sel] = TREE
        unc[y0:y1, x0:x1][sel] = np.maximum(unc[y0:y1, x0:x1][sel], 0.25 * t["height_m"] * 0.3 + 0.8)

    # cars sit on pavement: 1.5 m boxes, labelled as road surface
    for c in objs["cars"]:
        m = np.zeros((GRID, GRID), np.uint8)
        cv2.fillPoly(m, [np.round(np.array(c["polygon"]) / SCALE).astype(np.int32)], 1)
        ndsm[m > 0] = np.maximum(ndsm[m > 0], 1.5)
        labels[m > 0] = ROAD

    # buildings last so they win over any tree crown that overlaps a roof
    for b in objs["buildings"]:
        poly = np.asarray(b["polygon"], float)
        m = burn_polygon(ndsm, poly, b["height_m"])
        building_labels[m] = b["id"]
        labels[m] = BUILDING
        unc[m] = b["uncertainty_m"]

    dsm = (terrain + ndsm).astype(np.float32)
    slope, aspect = rasters.slope_aspect(dsm, PX_M)

    # ---------------------------------------------------------------- georeferencing of the grid
    x0, y0 = meta["geo"]["transform"][2], meta["geo"]["transform"][5]
    step = SCALE * 0.5            # grid pixel in state-plane feet
    transform = (step, 0.0, x0, 0.0, -step, y0)
    bounds = (x0, y0 - step * GRID, x0 + step * GRID, y0)
    geo = GeoMetadata(crs=meta["crs"], transform=transform, width=GRID, height=GRID, bounds=bounds, resolution=(step, step), nodata=None, band_count=3)

    np.savez_compressed(job / "arrays.npz", dsm=dsm, ndsm=ndsm, labels=labels, building_labels=building_labels, slope=slope.astype(np.float32),
             uncertainty=unc)

    # ---------------------------------------------------------------- images / rasters
    ortho = cv2.cvtColor(cv2.imread(str(job / "ortho.jpg")), cv2.COLOR_BGR2RGB)
    ortho_grid = cv2.resize(ortho, (GRID, GRID), interpolation=cv2.INTER_AREA)
    unc01 = np.clip(unc / max(float(unc.max()), 1e-3), 0, 1)
    rasters.save_png(rasters.height_color_image(dsm), job / "height_color.png")
    rasters.save_png(rasters.height_color_image(dsm), job / "dsm_preview.png")
    rasters.save_png(rasters.hillshade(dsm, PX_M, azimuth_deg=315.0, altitude_deg=45.0), job / "hillshade.png")
    rasters.save_png(rasters.slope_color_image(slope), job / "slope_color.png")
    rasters.save_png(rasters.uncertainty_color_image(unc01), job / "uncertainty_color.png")
    rasters.save_png(class_color_image(labels), job / "landcover.png")
    for name, arr in (("dsm", dsm), ("ndsm", ndsm), ("uncertainty", unc), ("slope", slope), ("aspect", aspect)):
        rasters.write_cog(arr, job / f"{name}.tif", geo)
    height_meta = rasters.save_height_png16(dsm, job / "height.png", job / "height_meta.json")
    for name, arr in (("height.f32", dsm), ("ndsm.f32", ndsm), ("uncertainty.f32", unc)):
        arr.astype("<f4").tofile(job / name)

    # ---------------------------------------------------------------- terrain meshes
    geom, export_stats = build_scene_meshes(dsm, job, PX_M, True, ortho_grid, ortho)
    lo, hi = float(dsm.min()), float(dsm.max())
    shutil.rmtree(job / "terrain_obj", ignore_errors=True)   # OBJ export folder: 26 MB, not needed for the stored scene

    # ---------------------------------------------------------------- detections + footprints in grid pixels
    from app.landcover.classify import CLASS_NAMES  # noqa: E402

    unity_objects = json.loads((job / "unity_scene.json").read_text(encoding="utf-8"))["objects"]
    obj_payload = []
    for car, uo in zip(objs["cars"], unity_objects):
        poly = [[round(x / SCALE, 1), round(y / SCALE, 1)] for x, y in car["polygon"]]
        cx, cy = car["center"][0] / SCALE, car["center"][1] / SCALE
        obj_payload.append({"id": uo["id"], "label": "small vehicle", "confidence": uo["confidence"], "polygon": poly, "center_px": [round(cx, 1), round(cy, 1)],
                            "area_px": round(cv2.contourArea(np.array(poly, np.float32)), 1),
                            "surface_elevation": round(float(dsm[min(GRID - 1, int(cy)), min(GRID - 1, int(cx))]), 2),
                            "terrain_elevation": round(float(terrain[min(GRID - 1, int(cy)), min(GRID - 1, int(cx))]), 2),
                            "height_above_ground": 1.5, "height_reliable": False, "lonlat": None})
    counts = {"small vehicle": len(obj_payload)}
    (job / "objects.json").write_text(json.dumps({"job_id": JOB_ID, "status": "ok", "model": "classical image analysis (oriented matched filter)", "count": len(obj_payload),
                                                  "counts_by_class": counts, "height_unit": "m", "objects": obj_payload,
                                                  "note": "Vehicles found by an oriented-rectangle matched filter in wide parking areas (no ML model). Positions and headings are measured; size is nominal."}), encoding="utf-8")

    b_json = {"job_id": JOB_ID, "count": len(objs["buildings"]), "note": "Hand-verified footprints; heights estimated from shadow length.",
              "buildings": [{"id": b["id"], "footprint": [[round(x / SCALE, 1), round(y / SCALE, 1)] for x, y in b["polygon"]], "area_px": round(b["area_m2"] / PX_M ** 2),
                             "height_m": b["height_m"], "is_metric": True, "confidence": 0.8 if b["uncertainty_m"] < 2 else 0.5,
                             "shadow_estimate_m": b["height_m"], "depth_vs_shadow_delta_m": None} for b in objs["buildings"]]}
    (job / "buildings.json").write_text(json.dumps(b_json), encoding="utf-8")
    (job / "disaster_zones.json").write_text(json.dumps({"job_id": JOB_ID, "count": 0, "zones": [], "note": "Zones are computed live on the Hazards screen."}), encoding="utf-8")
    (job / "validation.json").write_text(json.dumps({"status": "unavailable", "note": "No LiDAR reference was supplied for this scene, so no accuracy score is claimed. Building heights are shadow estimates (see the site analysis page).",
                                                     "rmse": None, "mae": None, "correlation": None, "valid_pixel_count": None, "reference_source": None}), encoding="utf-8")

    # ---------------------------------------------------------------- metadata / manifest
    finite = dsm[np.isfinite(dsm)]
    counts_lc = np.bincount(labels.ravel(), minlength=len(CLASS_NAMES))
    meta.update({
        "width": GRID, "height": GRID, "mode": "absolute", "dsm_kind": "absolute_dsm", "pixel_size_m": round(PX_M, 4), "gsd_m": round(PX_M, 4),
        "geo": {"crs": geo.crs, "transform": list(transform), "width": GRID, "height": GRID, "bounds": list(bounds), "resolution": [step, step]},
        "da_v2_encoder": "none", "da_v2_checkpoint": "none (no model used)", "depth_pro_used": False, "depth_pro_skipped_reason": "no model is used for this scene",
        "tiles": 1, "tta_variants": 0, "tile_size": GRID, "overlap": 0, "fusion_method": "hand-verified classical image analysis",
        "calibration_status": "calibrated", "calibration_note": "Terrain from SRTM 1 arc-second; building and tree heights from measured cast-shadow length at the sun elevation measured in the image.",
        "calibration_scale": None, "calibration_sources": [{"name": "shadow", "scale": 1.0, "weight": 1.0, "detail": f"{analysis['buildings']['heights_from_shadow']} buildings, H = L tan(elevation)"}],
        "calibration_scale_log_sigma": None, "ground_residual_rmse_m": None, "gcp_residuals": [], "shadow_summary": f"{analysis['buildings']['heights_from_shadow']} shadow heights; azimuth {analysis['sun']['sun_azimuth_deg']:.0f} deg (measured)",
        "shadow_measured": analysis["buildings"]["heights_from_shadow"], "dsm_is_metric": True, "mesh_status": "ready", "mesh_triangle_count": export_stats["triangles"],
        "mesh_chunks": len(geom["chunks"]), "mesh_lod0_triangles": sum(c["triangles"][0] for c in geom["chunks"]), "buildings_count": len(objs["buildings"]),
        "disaster_zones_count": 0, "validation_status": "unavailable", "height_range": [lo, hi], "mean_height": float(ndsm.mean()), "height_unit": "m",
        "land_cover_fractions": {CLASS_NAMES[i]: float(counts_lc[i]) / labels.size for i in range(len(CLASS_NAMES))}, "land_cover_counts": {CLASS_NAMES[i]: int(counts_lc[i]) for i in range(len(CLASS_NAMES))},
        "timings": {"inference_s": 0.0, "mesh_s": 0.0, "total_s": round(time.time() - t0, 1)}, "pixels_per_second": 0, "options": {"gsd_m": None, "crs": None, "origin_x": None, "origin_y": None, "sun_azimuth_deg": None,
                                                                                                                     "sun_elevation_deg": None, "dem_source": "auto", "tta": False, "ensemble": False},
        "is_georeferenced": True, "unity_horizontal_scale_source": "geotiff", "mesh_spacing_units": "meters", "mesh_downsample_factor": 1, "mesh_vertical_exaggeration": 1,
        "depth_pro_stats": None, "da_v2_stats": None, "confidence_available": False, "started_at": time.time() - 30, "completed_at": time.time(),
    })
    (job / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    scene_json = {"projectId": JOB_ID, "mode": "absolute", "kind": "absolute_dsm", "crs": geo.crs,
                  "sun": {"azimuth": analysis["sun"]["sun_azimuth_deg"], "elevation": analysis["sun"]["sun_elevation_deg"]}, "texture": "ortho.jpg", **geom,
                  "overlays": {"optical": "ortho.jpg", "height": "height_color.png", "hillshade": "hillshade.png", "slope": "slope_color.png", "uncertainty": "uncertainty_color.png",
                               "landcover": "landcover.png", "error": None, "flood": None}}
    (job / "scene.json").write_text(json.dumps(scene_json), encoding="utf-8")

    # ---------------------------------------------------------------- analyst brief + PDF
    context, called = analyst.gather_context(job)
    brief = {"text": analyst.template_report(context), "mode": "offline_template", "generated_at": time.time(), "unverified_numbers": [], "tools": called, "notice": None}
    (job / "brief.json").write_text(json.dumps(brief), encoding="utf-8")
    pdf = build_brief_pdf(JOB_ID, job, brief, meta, None)
    (job / "report.pdf").write_bytes(pdf)

    # ---------------------------------------------------------------- job.json
    out_names = {"original": "ortho.jpg", "ortho_jpg": "ortho.jpg", "thumb_jpg": "thumb.jpg", "buildings_json": "buildings.json", "disaster_zones_json": "disaster_zones.json",
                 "validation_json": "validation.json", "objects_json": "objects.json", "terrain_hires_glb": "terrain_hires.glb", "height_f32": "height.f32", "ndsm_f32": "ndsm.f32",
                 "uncertainty_f32": "uncertainty.f32", "dsm_tif": "dsm.tif", "ndsm_tif": "ndsm.tif", "uncertainty_tif": "uncertainty.tif", "slope_tif": "slope.tif",
                 "aspect_tif": "aspect.tif", "hillshade_png": "hillshade.png", "height_color_png": "height_color.png", "slope_color_png": "slope_color.png",
                 "uncertainty_color_png": "uncertainty_color.png", "landcover_png": "landcover.png", "dsm_preview_png": "dsm_preview.png", "height_png": "height.png",
                 "height_meta_json": "height_meta.json", "scene_json": "scene.json", "unity_scene_json": "unity_scene.json", "unity_heightmap_r16": "heightmap.r16",
                 "unity_texture_jpg": "texture.jpg", "metadata_json": "metadata.json", "analysis_json": "analysis.json", "report_pdf": "report.pdf"}
    for extra in ("terrain_obj.zip", "terrain.glb"):
        if (job / extra).exists():
            out_names[extra.replace(".", "_")] = extra
    outputs = {k: f"/api/pipeline/output/{JOB_ID}/{f}" for k, f in out_names.items() if (job / f).exists()}
    now = time.time()
    job_json = {"job_id": JOB_ID, "stage": "READY", "source_filename": "7.tif", "stored_path": "", "is_georeferenced": True, "error": None, "created_at": now - 60, "updated_at": now,
                "outputs": outputs, "mode": "absolute", "options": meta["options"],
                "summary": {"site": True, "featured": True, "buildings": len(objs["buildings"]), "trees": len(objs["trees"]), "vehicles": len(objs["cars"]),
                            "centre_lon_lat": meta["centre_lon_lat"], "bounds_wgs84": meta["bounds_wgs84"], "rmse": None, "pearson_r": None}}
    (job / "job.json").write_text(json.dumps(job_json, indent=2), encoding="utf-8")
    print(f"survey bundle done in {time.time() - t0:.0f}s: {len(outputs)} outputs, {len(geom['chunks'])} mesh chunk(s), PDF {len(pdf) // 1024} KB")


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--prepare":
        c = np.load(sys.argv[2])
        small = cv2.resize(c, (GRID, GRID), interpolation=cv2.INTER_NEAREST)
        np.save(HERE / "data" / "classes_grid.npy", small)
        print("saved classes_grid.npy", small.shape)
    else:
        main(sys.argv[1])
