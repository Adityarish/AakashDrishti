"""Stage 3: assemble the finished, hand-verified scene bundle for 7.tif and write it to backend/demo/denver7/job.

Nothing here uses a machine-learning model. Inputs are the outputs of the earlier stages (data/*.json), the half-resolution
mosaic and the class raster; outputs are the Unity bundle (unity_scene.json, heightmap.r16, texture.jpg), preview images,
metadata.json, buildings.json, objects.json and analysis.json.

usage: python build_scene.py <rgb_half.npy> <classes_half.npy> <out_job_dir>
"""

from __future__ import annotations

import json
import math
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.warp import transform as warp_transform
from scipy.ndimage import map_coordinates, gaussian_filter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import FT_M, HALF_PX_M, MOSAIC, REPO, TIF, WORLD_M, polygon_area_m2  # noqa: E402
from detect_roofs import refine_with_grabcut  # noqa: E402
from heights import building_height, tree_height  # noqa: E402
from shadows import shadow_direction, sun_elevation_from_cars  # noqa: E402

JOB_ID = "site-denver-7"
SRC_NAME = "7.tif"
HGT = REPO / "data" / "reference" / "N39W105.hgt"
HEIGHTMAP_N = 129
TEXTURE_PX = 4096
ORTHO_PX = 2048

CLASS_RGB = np.array([[128, 148, 92], [112, 112, 118], [32, 112, 44], [214, 70, 56], [255, 220, 40]], np.uint8)
CLASS_NAMES = ["open ground / lawn", "pavement", "tree canopy", "buildings", "vehicles"]


def scene_xy(col: float, row: float) -> list[float]:
    return [round(col * HALF_PX_M, 3), round((MOSAIC - row) * HALF_PX_M, 3)]


class Georef:
    """Mosaic pixel <-> state-plane feet <-> WGS84."""

    def __init__(self) -> None:
        with rasterio.open(TIF) as d:
            self.crs = d.crs.to_string()
            self.x0, self.y0 = d.transform.c, d.transform.f
            self.width, self.height, self.res = d.width, d.height, d.res[0]
            self.bounds = tuple(d.bounds)
            self.transform = tuple(d.transform)[:6]

    def lonlat(self, cols: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x = self.x0 + np.asarray(cols, float) * 0.5
        y = self.y0 - np.asarray(rows, float) * 0.5
        lon, lat = warp_transform(self.crs, "EPSG:4326", list(x.ravel()), list(y.ravel()))
        return np.array(lon).reshape(x.shape), np.array(lat).reshape(x.shape)


def dem_grid(geo: Georef) -> tuple[np.ndarray, dict]:
    """Real terrain: SRTM 1-arcsec tile resampled onto the scene (north-first rows). ~30 m native, so it is smooth."""
    with rasterio.open(HGT) as d:
        arr = d.read(1).astype(np.float32)
        arr[arr < -1000] = np.nan
        t = d.transform
    n = HEIGHTMAP_N
    gx = np.linspace(0, MOSAIC, n)
    gy = np.linspace(0, MOSAIC, n)
    cols, rows = np.meshgrid(gx, gy)
    lon, lat = geo.lonlat(cols, rows)
    fc = (lon - t.c) / t.a - 0.5
    fr = (lat - t.f) / t.e - 0.5
    z = map_coordinates(np.nan_to_num(arr, nan=float(np.nanmedian(arr))), [fr, fc], order=3, mode="nearest")
    z = gaussian_filter(z, 1.0)
    return z.astype(np.float32), {"source": "SRTM 1 arc-second (about 30 m)", "min": float(z.min()), "max": float(z.max()), "mean": float(z.mean())}


def terrain_sampler(z: np.ndarray):
    n = z.shape[0]

    def sample(col: float, row: float) -> float:
        fx, fy = np.clip(col / MOSAIC * (n - 1), 0, n - 1), np.clip(row / MOSAIC * (n - 1), 0, n - 1)
        return float(map_coordinates(z, [[fy], [fx]], order=1)[0])

    return sample


def refine_flats(mosaic: np.ndarray, buildings: list[dict]) -> int:
    """Snap hand-traced large flat roofs to the real roof edge (GrabCut); keep the hand trace if the result disagrees."""
    n = 0
    for b in buildings:
        if b["source"] != "manual" or b["kind"] != "flat" or b["area_m2"] < 120:
            continue
        poly = np.asarray(b["polygon"], float)
        x0, y0 = np.maximum(poly.min(0).astype(int) - 70, 0)
        x1, y1 = np.minimum(poly.max(0).astype(int) + 71, [MOSAIC, MOSAIC])
        crop = np.ascontiguousarray(mosaic[y0:y1, x0:x1])
        refined = refine_with_grabcut(crop, poly - [x0, y0], grow_px=10, shrink_px=9)
        if refined is None:
            continue
        a0, a1 = cv2.contourArea(poly.astype(np.float32)), cv2.contourArea(refined.astype(np.float32))
        if 0.8 * a0 <= a1 <= 1.25 * a0:
            b["polygon"] = (refined + [x0, y0]).round(1).tolist()
            b["refined"] = True
            n += 1
    return n


def roof_colour(mosaic: np.ndarray, poly: np.ndarray) -> list[int]:
    p = np.round(poly).astype(np.int32)
    x0, y0 = np.maximum(p.min(0), 0)
    x1, y1 = np.minimum(p.max(0) + 1, [MOSAIC, MOSAIC])
    m = np.zeros((y1 - y0, x1 - x0), np.uint8)
    cv2.fillPoly(m, [p - [x0, y0]], 1)
    sel = cv2.erode(m, np.ones((5, 5), np.uint8))
    if sel.sum() < 20:
        sel = m
    pix = mosaic[y0:y1, x0:x1][sel.astype(bool)]
    return [int(round(v)) for v in pix.mean(0)] if len(pix) else [200, 200, 200]


def longest_edge_yaw(poly: np.ndarray) -> float:
    best, vec = 0.0, (1.0, 0.0)
    for i in range(len(poly)):
        d = poly[(i + 1) % len(poly)] - poly[i]
        if np.hypot(*d) > best:
            best, vec = float(np.hypot(*d)), (float(d[0]), float(d[1]))
    return math.degrees(math.atan2(-vec[1], vec[0])) % 180.0  # image rows run south, scene z runs north


def stats(values: list[float]) -> dict:
    v = np.asarray(values, float)
    if not len(v):
        return {}
    return {"count": int(len(v)), "mean": round(float(v.mean()), 2), "median": round(float(np.median(v)), 2),
            "p10": round(float(np.percentile(v, 10)), 2), "p90": round(float(np.percentile(v, 90)), 2),
            "min": round(float(v.min()), 2), "max": round(float(v.max()), 2)}


def histogram(values: list[float], edges: list[float]) -> list[dict]:
    counts, _ = np.histogram(values, bins=edges)
    return [{"from": edges[i], "to": edges[i + 1], "count": int(c)} for i, c in enumerate(counts)]


def main(mosaic_npy: str, classes_npy: str, out_dir: str) -> None:
    t0 = time.time()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    mosaic = np.load(mosaic_npy, mmap_mode="r")
    classes = np.load(classes_npy)
    geo = Georef()
    buildings = json.loads((HERE / "data" / "buildings_final.json").read_text(encoding="utf-8"))
    cars = json.loads((HERE / "data" / "cars_auto.json").read_text(encoding="utf-8"))
    crowns = json.loads((HERE / "data" / "trees_auto.json").read_text(encoding="utf-8"))

    print("refining flat roofs...", flush=True)
    print("  refined", refine_flats(mosaic, buildings))
    for b in buildings:
        b["area_m2"] = round(polygon_area_m2(np.asarray(b["polygon"])), 1)

    print("sun direction / elevation from shadows...", flush=True)
    polys = [np.asarray(b["polygon"]) for b in buildings if b["kind"] in ("house", "flat")]
    direction = shadow_direction(mosaic, polys, samples=300)
    az = float(direction["shadow_azimuth_deg"])
    lots = [(460, 280, 1500, 1180), (1500, 270, 1760, 1030), (2020, 740, 2300, 1240), (4400, 4500, 4750, 4820)]
    lot_cars = [c for c in cars if any(a <= c["center"][0] < b and c0 <= c["center"][1] < d for a, c0, b, d in lots)]
    el_res = sun_elevation_from_cars(mosaic, lot_cars, az)
    elev = float(el_res["elevation_deg"])
    sun_az = (az + 180.0) % 360.0
    print(f"  shadows point to {az:.1f} deg (sun azimuth {sun_az:.1f}); elevation {elev:.1f} deg from {el_res['cars_used']} cars")

    print("heights...", flush=True)
    for b in buildings:
        if b["kind"] == "house" and b["area_m2"] < 45:
            b["kind"] = "shed"   # garden sheds / detached garages are not houses
        b.update(building_height(mosaic, b, az, elev))
    # crowns sitting among parked cars are the cars' own dark shapes and shadows read as foliage, not trees
    n_before = len(crowns)
    crowns = [t for t in crowns if t.get("car_frac", 0.0) < 0.12]
    print(f"  dropped {n_before - len(crowns)} crowns overlapping parked cars")
    for t in crowns:
        t.update(tree_height(mosaic, t, az, elev))

    (out / "site_objects.json").write_text(json.dumps({
        "buildings": [{"id": b["id"], "kind": b["kind"], "polygon": b["polygon"], "height_m": b["height_m"], "uncertainty_m": b["uncertainty_m"], "area_m2": b["area_m2"]}
                      for b in buildings],
        "trees": [{"center": t["center"], "radius_px": t["radius_px"], "height_m": t["height_m"]} for t in crowns],
        "cars": [{"center": c["center"], "polygon": c["polygon"]} for c in cars]}), encoding="utf-8")
    z, dem = dem_grid(geo)
    ground = terrain_sampler(z)

    # ------------------------------------------------------------ Unity bundle
    unity_buildings, rows_out = [], []
    for b in buildings:
        poly = np.asarray(b["polygon"])
        color = roof_colour(mosaic, poly)
        lon, lat = geo.lonlat(np.array([poly[:, 0].mean()]), np.array([poly[:, 1].mean()]))
        (_, _), (rw, rh), _ = cv2.minAreaRect(poly.astype(np.float32))
        floors = max(1, int(round(b["eave_m"] / 3.4))) if b["kind"] in ("flat",) else (2 if b["eave_m"] > 5.4 else 1)
        unity_buildings.append({"id": b["id"], "height_m": b["height_m"], "footprint": [scene_xy(x, y) for x, y in poly], "color_rgb": color,
                                "kind": b["kind"]})
        rows_out.append({"id": b["id"], "kind": b["kind"], "label": b["label"], "area_m2": b["area_m2"], "height_m": b["height_m"],
                         "eave_m": b["eave_m"], "ridge_m": b["ridge_m"], "uncertainty_m": b["uncertainty_m"], "height_method": b["height_method"],
                         "floors_est": floors, "length_m": round(max(rw, rh) * HALF_PX_M, 1), "width_m": round(min(rw, rh) * HALF_PX_M, 1),
                         "lon": round(float(lon[0]), 6), "lat": round(float(lat[0]), 6), "roof_rgb": color, "source": b["source"]})

    unity_trees = []
    for i, t in enumerate(sorted(crowns, key=lambda t: (t["center"][1], t["center"][0])), start=1):
        radius_m = float(np.clip(t["radius_px"] * HALF_PX_M * 1.25, 1.5, 6.0))
        unity_trees.append({"id": i, "position": scene_xy(*t["center"]), "height_m": t["height_m"], "crown_radius_m": round(radius_m, 2),
                            "color_rgb": [int(round(v)) for v in t["rgb"]], "height_method": t["height_method"]})

    unity_objects = []
    for i, c in enumerate(cars, start=1):
        poly = np.asarray(c["polygon"])
        yaw = longest_edge_yaw(poly)
        unity_objects.append({"id": i, "label": "small vehicle", "kind": "vehicle", "confidence": round(min(0.99, 0.5 + c["score"] / 60.0), 2),
                              "center": scene_xy(*c["center"]), "yaw_deg": round(yaw, 1),
                              "size_m": {"length": 4.6, "width": 1.9, "height": 1.5}, "color_rgb": [int(round(v)) for v in c["rgb"]],
                              "polygon": [scene_xy(x, y) for x, y in poly]})

    zmin, zmax = float(z.min()), float(z.max())
    zmax = max(zmax, zmin + 0.5)
    quant = np.round((z - zmin) / (zmax - zmin) * 65535.0).astype("<u2")
    (out / "heightmap.r16").write_bytes(quant.tobytes())

    scene = {"job_id": JOB_ID, "heightmap": {"file": "heightmap.r16", "width": HEIGHTMAP_N, "height": HEIGHTMAP_N, "min_m": zmin, "max_m": zmax},
             "texture": {"file": "texture.jpg"}, "world_size_m": {"x": round(WORLD_M, 3), "z": round(WORLD_M, 3)}, "is_metric": True,
             "horizontal_scale_source": "geotiff", "buildings": unity_buildings, "disaster_zones": [], "objects": unity_objects,
             "trees": unity_trees,
             "refinement": {"method": "hand-verified classical image processing (no ML)", "buildings": len(unity_buildings),
                            "trees": len(unity_trees), "vehicles": len(unity_objects)}}
    (out / "unity_scene.json").write_text(json.dumps(scene), encoding="utf-8")

    # ------------------------------------------------------------ images
    print("textures...", flush=True)
    with rasterio.open(TIF) as d:
        tex = np.transpose(d.read([1, 2, 3], out_shape=(3, TEXTURE_PX, TEXTURE_PX), resampling=Resampling.average), (1, 2, 0))
    cv2.imwrite(str(out / "texture.jpg"), cv2.cvtColor(tex, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
    ortho = cv2.resize(tex, (ORTHO_PX, ORTHO_PX), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out / "ortho.jpg"), cv2.cvtColor(ortho, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 88])
    cv2.imwrite(str(out / "thumb.jpg"), cv2.cvtColor(cv2.resize(tex, (480, 480), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])
    lc = CLASS_RGB[classes[::4, ::4]]
    cv2.imwrite(str(out / "landcover.png"), cv2.cvtColor(cv2.resize(lc, (1320, 1320), interpolation=cv2.INTER_NEAREST), cv2.COLOR_RGB2BGR))
    # shaded relief of the real terrain, for a sanity view
    gy, gx = np.gradient(z, WORLD_M / (HEIGHTMAP_N - 1))
    hill = np.clip(0.5 + 0.5 * (gx * -0.7 + gy * 0.7) * 30, 0, 1)
    cv2.imwrite(str(out / "hillshade.png"), cv2.resize((hill * 255).astype(np.uint8), (512, 512), interpolation=cv2.INTER_CUBIC))

    # ------------------------------------------------------------ analysis
    print("analysis...", flush=True)
    px_area_m2 = HALF_PX_M ** 2
    cover = {CLASS_NAMES[k]: round(float((classes == k).mean()) * 100, 2) for k in range(5)}
    scene_area_m2 = WORLD_M ** 2
    house_rows = [r for r in rows_out if r["kind"] == "house"]
    flat_rows = [r for r in rows_out if r["kind"] == "flat"]
    foot = sum(r["area_m2"] for r in rows_out)
    tree_h = [t["height_m"] for t in unity_trees]
    canopy_m2 = float((classes == 2).sum()) * px_area_m2
    pave_m2 = float((classes == 1).sum()) * px_area_m2
    lon_all, lat_all = geo.lonlat(np.array([0, MOSAIC, 0, MOSAIC, MOSAIC / 2]), np.array([0, 0, MOSAIC, MOSAIC, MOSAIC / 2]))
    bounds_wgs84 = [round(float(lon_all[:4].min()), 6), round(float(lat_all[:4].min()), 6), round(float(lon_all[:4].max()), 6), round(float(lat_all[:4].max()), 6)]
    centre = [round(float(lon_all[4]), 6), round(float(lat_all[4]), 6)]

    lot_density = len(lot_cars) / max(1, 1)
    analysis = {
        "job_id": JOB_ID, "title": "Denver suburb, Colorado (7.tif)", "generated_by": "hand-verified classical image analysis, no ML models",
        "location": {"centre_lon_lat": centre, "bounds_wgs84": bounds_wgs84, "crs": geo.crs, "pixel_size_m": round(0.25 * FT_M, 4),
                     "size_m": round(WORLD_M, 1), "area_ha": round(scene_area_m2 / 1e4, 1), "area_km2": round(scene_area_m2 / 1e6, 3)},
        "sun": {"shadow_azimuth_deg": round(az, 1), "sun_azimuth_deg": round(sun_az, 1), "sun_elevation_deg": round(elev, 1),
                "elevation_cars_used": int(el_res["cars_used"]), "method": "shadow direction by 72-way search over 300 roofs; elevation from car shadow length (cars assumed 1.5 m tall)"},
        "terrain": {"source": dem["source"], "min_m": round(dem["min"], 1), "max_m": round(dem["max"], 1), "mean_m": round(dem["mean"], 1),
                    "relief_m": round(dem["max"] - dem["min"], 1),
                    "note": "Real elevation from the SRTM tile covering the site. At about 30 m native resolution it shows the broad slope only; hills or mountains would appear here. Relief this small means the site is flat suburban terrain."},
        "landcover_percent": cover,
        "impervious_percent": round(cover["pavement"] + cover["buildings"] + cover["vehicles"], 2),
        "buildings": {"count": len(rows_out), "by_kind": dict(Counter(r["kind"] for r in rows_out)), "footprint_total_m2": round(foot, 0),
                      "coverage_percent": round(foot / scene_area_m2 * 100, 2), "density_per_km2": round(len(rows_out) / (scene_area_m2 / 1e6), 0),
                      "height_m": stats([r["height_m"] for r in rows_out]), "house_height_m": stats([r["height_m"] for r in house_rows]),
                      "commercial_height_m": stats([r["height_m"] for r in flat_rows]),
                      "height_histogram": histogram([r["height_m"] for r in rows_out], [0, 2.5, 3.5, 4.5, 5.5, 7, 10, 20]),
                      "footprint_histogram": histogram([r["area_m2"] for r in rows_out], [0, 25, 100, 150, 200, 300, 600, 3000, 20000]),
                      "heights_from_shadow": sum(1 for r in rows_out if r["height_method"] == "shadow"),
                      "heights_assumed": sum(1 for r in rows_out if r["height_method"] == "assumed"),
                      "floors": dict(Counter(r["floors_est"] for r in rows_out)),
                      "tallest": sorted(rows_out, key=lambda r: -r["height_m"])[:10], "largest": sorted(rows_out, key=lambda r: -r["area_m2"])[:10]},
        "trees": {"count": len(unity_trees), "density_per_ha": round(len(unity_trees) / (scene_area_m2 / 1e4), 1),
                  "canopy_cover_percent": cover["tree canopy"], "canopy_area_ha": round(canopy_m2 / 1e4, 2),
                  "height_m": stats(tree_h), "height_histogram": histogram(tree_h, [0, 4, 6, 8, 10, 13, 17, 25]),
                  "heights_from_shadow": sum(1 for t in unity_trees if t["height_method"] == "shadow"),
                  "heights_assumed": sum(1 for t in unity_trees if t["height_method"] == "assumed")},
        "vehicles": {"count": len(unity_objects), "note": "Counted in wide parking areas only (lots at the shopping centre, school and stores). Cars parked on narrow streets and driveways are not counted, so this is a lower bound.",
                     "parking_area_cars": len(lot_cars)},
        "pavement": {"area_ha": round(pave_m2 / 1e4, 2), "percent": cover["pavement"]},
        "rocks": {"count": 0, "note": "No distinct boulders or rock outcrops are resolved at 0.15 m/pixel. Decorative gravel beds exist but are not separable from paving by colour and texture."},
        "mountains": {"count": 0, "note": "None: the terrain relief across the whole site is under 10 m."},
        "method": {
            "buildings": "Roofs found by smoothness + cast-shadow evidence, merged by chroma, edge-snapped with GrabCut, then every 880 px review tile was checked by eye: false detections removed, missed roofs seeded or traced.",
            "heights": "Shadow length / tan(sun elevation). Pitched roofs add a modelled rise (4:12 pitch). Each height carries an uncertainty; 'assumed' means no usable shadow, a class default was used.",
            "vehicles": "Oriented-rectangle matched filter on pavement; template 4.6 x 1.9 m. Position, heading and colour are measured, size is nominal.",
            "trees": "Textured canopy mask (dark evergreen or bare high-variance crowns) split into crowns by distance-transform peaks; height from shadow length.",
        },
        "limits": [
            "Heights are estimates from shadows: expect roughly +/-15-25%. Eave height is measured; ridge height includes an assumed roof pitch.",
            "Bare winter trees are harder to find; some crowns are missed and some yard clutter is counted.",
            "Terrain is SRTM at about 30 m, so small slopes and the exact ground under each building are not resolved.",
        ],
        "buildings_table": rows_out,
        "total_seconds": round(time.time() - t0, 1),
    }
    (out / "analysis.json").write_text(json.dumps(analysis), encoding="utf-8")

    # ------------------------------------------------------------ job metadata
    meta = {
        "job_id": JOB_ID, "source_filename": SRC_NAME, "is_georeferenced": True, "mode": "absolute", "dsm_kind": "absolute_dsm", "crs": geo.crs,
        "geo": {"crs": geo.crs, "transform": list(geo.transform), "width": geo.width, "height": geo.height, "bounds": list(geo.bounds),
                "resolution": [geo.res, geo.res]},
        "bounds_wgs84": bounds_wgs84, "centre_lon_lat": centre, "width": geo.width, "height": geo.height, "band_count": 4, "bit_depth": 8, "file_format": "GeoTIFF",
        "gsd_m": round(0.25 * FT_M, 4), "pixel_size_m": round(0.25 * FT_M, 4), "sun_azimuth_deg": round(sun_az, 1), "sun_elevation_deg": round(elev, 1),
        "sun_azimuth_source": "measured from cast shadows", "dsm_is_metric": True, "buildings_count": len(rows_out),
        "unity_world_size_m": {"x": round(WORLD_M, 3), "z": round(WORLD_M, 3)}, "height_unit": "m", "land_cover_fractions": {k: v / 100 for k, v in cover.items()},
        "site": True,
    }
    (out / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    b_json = {"job_id": JOB_ID, "count": len(rows_out), "note": "Hand-verified footprints; heights from shadows.",
              "buildings": [{"id": r["id"], "footprint": [[x * ORTHO_PX / MOSAIC, y * ORTHO_PX / MOSAIC] for x, y in b["polygon"]], "height_m": r["height_m"], "is_metric": True,
                             "confidence": 0.8 if r["height_method"] == "shadow" else 0.4, "shadow_estimate_m": r["eave_m"], "depth_vs_shadow_delta_m": None}
                            for r, b in zip(rows_out, buildings)]}
    (out / "buildings.json").write_text(json.dumps(b_json), encoding="utf-8")

    outputs = {k: f"/api/pipeline/output/{JOB_ID}/{f}" for k, f in
               {"original": "ortho.jpg", "ortho_jpg": "ortho.jpg", "thumb_jpg": "thumb.jpg", "landcover_png": "landcover.png", "hillshade_png": "hillshade.png",
                "unity_scene_json": "unity_scene.json", "unity_heightmap_r16": "heightmap.r16", "unity_texture_jpg": "texture.jpg", "metadata_json": "metadata.json",
                "buildings_json": "buildings.json", "analysis_json": "analysis.json"}.items()}
    now = time.time()
    job = {"job_id": JOB_ID, "stage": "READY", "source_filename": SRC_NAME, "stored_path": "", "is_georeferenced": True, "error": None, "created_at": now, "updated_at": now,
           "outputs": outputs, "mode": "absolute", "summary": {"site": True, "featured": True, "centre_lon_lat": centre, "bounds_wgs84": bounds_wgs84}}
    (out / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
    print(f"done in {time.time() - t0:.0f}s: {len(rows_out)} buildings, {len(unity_trees)} trees, {len(unity_objects)} vehicles; centre {centre}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
