"""Disaster analysis tools computed live from the persisted DSM (FR-36..FR-40).

All results are decision support: vertical error of a single-view DSM is metre-scale, surface
strength is not assessed, and nothing here is an aviation- or survey-grade clearance.
"""

from __future__ import annotations

import math
from typing import Optional

import cv2
import numpy as np
from scipy import ndimage

from app.analysis.scene import Scene, overlay_rgba, png_base64
from app.landcover.classify import BUILDING, GROUND, LOW_VEG, ROAD, WATER

FLOOD_RGB = (91, 155, 200)
SLOPE_RGB = (228, 87, 75)
VIEW_RGB = (242, 107, 33)
LZ_DISCLAIMER = (
    "Candidate sites for operator confirmation. Surface strength is not assessed and vertical error is "
    "metre-scale: this is decision support, not a landing clearance."
)


def has_bare_earth_terrain(scene: Scene) -> bool:
    """Flood simulation needs a real, independently-derived bare-earth elevation -- `dsm - ndsm`
    only carries genuine relief when the DSM came from DEM/GCP calibration (kind ==
    "absolute_dsm"). For shadow-only (pseudo_metric) or uncalibrated (relative) scenes the
    height field is already AGL by construction (the fine-tuned model treats local ground as 0
    everywhere), so `terrain` is a flat plane with nothing to flood against."""
    finite = scene.terrain[np.isfinite(scene.terrain)]
    if finite.size == 0:
        return False
    spread = float(np.nanpercentile(finite, 98) - np.nanpercentile(finite, 2))
    return spread > 1e-3


NO_TERRAIN_NOTE = (
    "Flood simulation needs a bare-earth ground surface to test a water level against. This scene has "
    "none: it is not georeferenced (PNG/JPG), or no DEM tile covered it. Upload a GeoTIFF so its "
    "location can be matched to an SRTM DEM (downloaded automatically when online), or place a DEM "
    "tile for the area in the SRTM data folder."
)


def flood_reference_level(scene: Scene) -> float:
    """Elevation that a 0 m water level refers to: the median terrain of water pixels if any,
    otherwise the 2nd percentile of terrain."""
    terrain = scene.terrain
    water = (scene.labels == WATER) & np.isfinite(terrain)
    if water.sum() > 200:
        return float(np.median(terrain[water]))
    return float(np.nanpercentile(terrain, 2))


def flood_level_range(scene: Scene) -> tuple[float, float]:
    ref = flood_reference_level(scene)
    top = float(np.nanpercentile(scene.terrain, 98))
    return 0.0, max(1.0, top - ref) if scene.is_metric else max(top - ref, 1e-3)


def simulate_flood(
    scene: Scene, level: float, seed: str = "auto", seed_col: Optional[float] = None, seed_row: Optional[float] = None,
    keep_mask: bool = False,
) -> dict:
    if not has_bare_earth_terrain(scene):
        result = {
            "level": float(level), "surface_elevation": None, "reference_elevation": None, "unit": scene.unit,
            "seed": seed, "inundated_pixels": 0, "area_km2": 0.0, "area_fraction": 0.0, "volume_m3": None,
            "mean_depth": 0.0, "max_depth": 0.0, "affected_buildings": 0,
            "total_buildings": int(len(np.unique(scene.building_labels[scene.building_labels > 0]))),
            "affected_building_ids": [], "affected_footprint_m2": 0.0, "total_footprint_m2": 0.0,
            "worst_hit_areas": [], "is_metric": scene.is_metric,
            "overlay_png": None, "terrain_available": False, "note": NO_TERRAIN_NOTE,
        }
        if keep_mask:
            result["_mask"] = np.zeros(scene.dsm.shape, dtype=bool)
            result["_depth"] = np.zeros(scene.dsm.shape, dtype=np.float32)
        return result

    terrain = scene.terrain
    finite = np.isfinite(terrain)
    ref = flood_reference_level(scene)
    surface = ref + level
    below = finite & (terrain <= surface)

    seeds = np.zeros_like(below)
    seed_used = seed
    if seed == "point" and seed_col is not None and seed_row is not None:
        r, c = int(round(seed_row)), int(round(seed_col))
        if 0 <= r < below.shape[0] and 0 <= c < below.shape[1]:
            seeds[max(r - 2, 0): r + 3, max(c - 2, 0): c + 3] = True
    else:
        water = scene.labels == WATER
        if seed in ("auto", "water") and water.sum() > 200:
            seeds |= water
            seed_used = "water bodies"
        if seed in ("auto", "edge") and not seeds.any():
            edges = {
                "top": terrain[0, :], "bottom": terrain[-1, :], "left": terrain[:, 0], "right": terrain[:, -1],
            }
            lowest = min(edges, key=lambda k: float(np.nanmean(edges[k])))
            border = np.zeros_like(below)
            if lowest == "top":
                border[0, :] = True
            elif lowest == "bottom":
                border[-1, :] = True
            elif lowest == "left":
                border[:, 0] = True
            else:
                border[:, -1] = True
            seeds |= border
            seed_used = f"lowest edge ({lowest})"

    labeled, count = ndimage.label(below, structure=np.ones((3, 3)))
    keep = np.zeros(count + 1, dtype=bool)
    hit = np.unique(labeled[seeds & below])
    keep[hit[hit > 0]] = True
    flooded = keep[labeled]

    building_ids = np.unique(scene.building_labels[scene.building_labels > 0])
    # One bincount pass instead of a full-raster mask per building.
    size = int(building_ids.max()) + 1 if building_ids.size else 1
    totals = np.bincount(scene.building_labels.ravel(), minlength=size)
    flooded_totals = np.bincount(scene.building_labels[flooded], minlength=size)
    affected: list[int] = [int(bid) for bid in building_ids if flooded_totals[bid] / totals[bid] > 0.25]

    # Buildings are all-or-nothing: bare-earth water only partly clips a footprint, which drew a
    # patchy overlay. An affected building is painted whole, an unaffected one is left dry.
    in_building = scene.building_labels > 0
    affected_mask = np.isin(scene.building_labels, np.asarray(affected, dtype=scene.building_labels.dtype))
    flooded = (flooded & ~in_building) | affected_mask

    px_area = scene.px_m**2
    depth = np.where(flooded, surface - terrain, 0.0).astype(np.float32)
    area_km2 = float(flooded.sum() * px_area / 1e6)
    volume_m3 = float(depth.sum() * px_area) if scene.is_metric else None

    blocks = _worst_blocks(flooded, scene, depth)
    total_footprint_px = int((scene.building_labels > 0).sum())
    flooded_footprint_px = int(affected_mask.sum())
    result = {
        "level": float(level),
        "surface_elevation": float(surface),
        "reference_elevation": float(ref),
        "unit": scene.unit,
        "seed": seed_used,
        "inundated_pixels": int(flooded.sum()),
        "area_km2": area_km2,
        "area_fraction": float(flooded.mean()),
        "volume_m3": volume_m3,
        "mean_depth": float(depth[flooded].mean()) if flooded.any() else 0.0,
        "max_depth": float(depth.max()) if flooded.any() else 0.0,
        "affected_buildings": len(affected),
        "total_buildings": int(len(building_ids)),
        "affected_building_ids": affected[:500],
        "affected_footprint_m2": float(flooded_footprint_px * px_area),
        "total_footprint_m2": float(total_footprint_px * px_area),
        "worst_hit_areas": blocks,
        "is_metric": scene.is_metric,
        "overlay_png": png_base64(overlay_rgba(flooded, FLOOD_RGB, 0.6)),
        "terrain_available": True,
        "note": None,
    }
    if keep_mask:
        result["_mask"] = flooded
        result["_depth"] = depth
    return result


def _worst_blocks(flooded: np.ndarray, scene: Scene, depth: np.ndarray) -> list[dict]:
    rows, cols = flooded.shape
    names = [["north-west", "north", "north-east"], ["west", "centre", "east"], ["south-west", "south", "south-east"]]
    out = []
    for i in range(3):
        for j in range(3):
            block = flooded[i * rows // 3:(i + 1) * rows // 3, j * cols // 3:(j + 1) * cols // 3]
            block_depth = depth[i * rows // 3:(i + 1) * rows // 3, j * cols // 3:(j + 1) * cols // 3]
            if block.size:
                out.append({"area": names[i][j], "flooded_fraction": float(block.mean()),
                            "mean_depth": float(block_depth[block].mean()) if block.any() else 0.0})
    out.sort(key=lambda item: item["flooded_fraction"], reverse=True)
    return out[:3]


def slope_hazard(scene: Scene, threshold_deg: float) -> dict:
    slope = scene.slope
    mask = np.isfinite(slope) & (slope >= threshold_deg)
    excess = np.clip((slope - threshold_deg) / max(90.0 - threshold_deg, 1.0), 0.0, 1.0)
    alpha = 0.35 + 0.55 * excess
    px_area = scene.px_m**2
    by_class = {}
    from app.landcover.classify import CLASS_NAMES

    for index, name in enumerate(CLASS_NAMES):
        by_class[name] = float((mask & (scene.labels == index)).sum() * px_area / 1e6)
    finite_slope = slope[np.isfinite(slope)]
    hist, edges = np.histogram(finite_slope, bins=18, range=(0, 90))
    return {
        "threshold_deg": float(threshold_deg),
        "area_km2": float(mask.sum() * px_area / 1e6),
        "area_fraction": float(mask.mean()),
        "max_slope_deg": float(finite_slope.max()) if finite_slope.size else 0.0,
        "mean_slope_deg": float(finite_slope.mean()) if finite_slope.size else 0.0,
        "area_km2_by_class": by_class,
        "histogram": {"counts": hist.tolist(), "edges": edges.tolist()},
        "px_size_m": scene.px_m,
        "overlay_png": png_base64(overlay_rgba(mask, SLOPE_RGB, alpha)),
    }


def _approach_clearance(scene: Scene, row: int, col: int, radius_m: float) -> tuple[float, float]:
    """Best 8:1 glide-slope clearance over two opposite 200 m corridors. Returns (score, heading_deg)."""
    dsm = scene.dsm
    px = scene.px_m
    steps = max(4, int(200.0 / px))
    site_z = float(dsm[row, col])
    best, heading = 0.0, 0.0
    start = max(1, int(radius_m / px))
    for angle in (0, 45, 90, 135):
        fractions = []
        for sign in (1, -1):
            rad = math.radians(angle + (0 if sign == 1 else 180))
            dx, dy = math.sin(rad), -math.cos(rad)
            ok = total = 0
            for step in range(start, steps + 1):
                r = int(round(row + dy * step))
                c = int(round(col + dx * step))
                if not (0 <= r < dsm.shape[0] and 0 <= c < dsm.shape[1]):
                    break
                dist_m = step * px
                total += 1
                if float(dsm[r, c]) - site_z <= dist_m / 8.0:
                    ok += 1
            fractions.append(ok / total if total else 1.0)
        score = min(fractions)
        if score > best:
            best, heading = score, float(angle)
    return best, heading


def landing_zones(
    scene: Scene,
    min_radius_m: float = 15.0,
    max_slope_deg: float = 5.0,
    max_ndsm_m: float = 0.5,
    top_n: int = 8,
    flood_level: Optional[float] = None,
) -> dict:
    px = scene.px_m
    ndsm_limit = max_ndsm_m if scene.is_metric else 0.02 * float(np.nanpercentile(scene.ndsm, 99) + 1e-9)
    ok = (
        np.isfinite(scene.slope) & (scene.slope <= max_slope_deg) & np.isfinite(scene.ndsm) & (scene.ndsm <= ndsm_limit)
        & np.isin(scene.labels, [GROUND, ROAD, LOW_VEG]) & (scene.building_labels == 0)
    )
    flood_note = None
    if flood_level is not None:
        flood = simulate_flood(scene, flood_level, keep_mask=True)
        ok &= ~flood["_mask"]
        if not flood["terrain_available"]:
            flood_note = "\"Avoid flooded ground\" had no effect: " + NO_TERRAIN_NOTE
    ok = cv2.morphologyEx(ok.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)

    distance = ndimage.distance_transform_edt(ok)
    radius_m = distance * px
    local_max = (distance == ndimage.maximum_filter(distance, size=max(3, int(min_radius_m / px) | 1))) & (radius_m >= min_radius_m)
    rows, cols = np.nonzero(local_max)
    order = np.argsort(-radius_m[rows, cols])

    road_distance_m = ndimage.distance_transform_edt(scene.labels != ROAD) * px if (scene.labels == ROAD).any() else None
    picked: list[tuple[int, int, float]] = []
    for index in order:
        r, c = int(rows[index]), int(cols[index])
        rad = float(radius_m[r, c])
        if all(math.hypot(r - pr, c - pc) * px > max(rad, pr_rad) for pr, pc, pr_rad in picked):
            picked.append((r, c, rad))
        if len(picked) >= 40:
            break

    candidates = []
    for r, c, rad in picked:
        window_r = max(1, int(rad / px))
        window = scene.slope[max(r - window_r, 0): r + window_r + 1, max(c - window_r, 0): c + window_r + 1]
        mean_slope = float(np.nanmean(window))
        clearance, heading = _approach_clearance(scene, r, c, rad)
        road_d = float(road_distance_m[r, c]) if road_distance_m is not None else None
        road_prox = 0.0 if road_d is None else float(np.clip(1.0 - road_d / 300.0, 0.0, 1.0))
        norm_radius = min(1.0, rad / (3.0 * min_radius_m))
        score = 0.4 * norm_radius + 0.3 * (1.0 - min(mean_slope, max_slope_deg) / max_slope_deg) + 0.2 * clearance + 0.1 * road_prox
        lonlat = scene.pixel_to_lonlat(c, r)
        candidates.append({
            "col": c, "row": r, "clear_radius_m": rad, "mean_slope_deg": mean_slope,
            "approach_clearance": clearance, "approach_heading_deg": heading,
            "nearest_road_m": road_d, "score": float(score),
            "lon": lonlat[0] if lonlat else None, "lat": lonlat[1] if lonlat else None,
            "elevation": float(scene.dsm[r, c]),
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    candidates = candidates[:top_n]
    for rank, item in enumerate(candidates, start=1):
        item["rank"] = rank
    return {
        "sites": candidates,
        "criteria": {"min_radius_m": min_radius_m, "max_slope_deg": max_slope_deg, "max_ndsm_m": ndsm_limit},
        "candidate_area_km2": float(ok.sum() * px * px / 1e6),
        "unit": "m" if scene.is_metric else "px (relative scene: distances assume 1 px = 1 unit)",
        "disclaimer": LZ_DISCLAIMER + (f" {flood_note}" if flood_note else ""),
    }


def viewshed(scene: Scene, col: float, row: float, observer_height_m: float = 2.0, max_radius_m: Optional[float] = None) -> dict:
    dsm = np.where(np.isfinite(scene.dsm), scene.dsm, np.nanmin(scene.dsm)).astype(np.float64)
    h, w = dsm.shape
    px = scene.px_m
    r0, c0 = int(round(row)), int(round(col))
    r0, c0 = min(max(r0, 0), h - 1), min(max(c0, 0), w - 1)
    max_px = int(min(math.hypot(h, w), (max_radius_m / px) if max_radius_m else math.hypot(h, w)))
    max_px = max(max_px, 2)
    angles = int(min(8000, max(360, 4 * max_px)))
    theta = np.linspace(0, 2 * np.pi, angles, endpoint=False)
    steps = np.arange(1, max_px + 1)
    rr = np.rint(r0 + np.outer(np.sin(theta), steps) * -1).astype(np.int64)
    cc = np.rint(c0 + np.outer(np.cos(theta), steps)).astype(np.int64)
    inside = (rr >= 0) & (rr < h) & (cc >= 0) & (cc < w)
    rr_c, cc_c = np.clip(rr, 0, h - 1), np.clip(cc, 0, w - 1)
    z = dsm[rr_c, cc_c]
    eye = dsm[r0, c0] + observer_height_m
    dist_m = steps[None, :] * px
    tan_angle = (z - eye) / dist_m
    running_max = np.maximum.accumulate(np.where(inside, tan_angle, -np.inf), axis=1)
    previous = np.concatenate([np.full((angles, 1), -np.inf), running_max[:, :-1]], axis=1)
    visible_ray = inside & (tan_angle >= previous)

    visible = np.zeros((h, w), dtype=bool)
    visible[rr_c[visible_ray], cc_c[visible_ray]] = True
    visible = cv2.morphologyEx(visible.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)
    visible[r0, c0] = True

    vr, vc = np.nonzero(visible)
    farthest = float(np.max(np.hypot(vr - r0, vc - c0)) * px) if vr.size else 0.0
    area_km2 = float(visible.sum() * px * px / 1e6)
    return {
        "observer": {"col": c0, "row": r0, "height_m": observer_height_m, "elevation": float(dsm[r0, c0])},
        "visible_fraction": float(visible.mean()),
        "area_km2": area_km2,
        "farthest_visible_m": farthest,
        "buildings_visible": int(len(np.unique(scene.building_labels[visible & (scene.building_labels > 0)]))),
        "overlay_png": png_base64(overlay_rgba(visible, VIEW_RGB, 0.45)),
    }


def elevation_profile(scene: Scene, c0: float, r0: float, c1: float, r1: float, samples: int = 256) -> dict:
    length_px = math.hypot(c1 - c0, r1 - r0)
    n = int(max(2, min(samples, max(2, length_px))))
    cols = np.linspace(c0, c1, n)
    rows = np.linspace(r0, r1, n)
    coords = [rows, cols]
    surface = ndimage.map_coordinates(np.nan_to_num(scene.dsm, nan=np.nanmin(scene.dsm)), coords, order=1, mode="nearest")
    terrain = ndimage.map_coordinates(np.nan_to_num(scene.terrain, nan=np.nanmin(scene.terrain)), coords, order=1, mode="nearest")
    unc = ndimage.map_coordinates(np.nan_to_num(scene.uncertainty_m, nan=0.0), coords, order=1, mode="nearest")
    dist = np.linspace(0, length_px * scene.px_m, n)
    return {
        "distance_m": dist.tolist(), "surface": surface.tolist(), "terrain": terrain.tolist(),
        "uncertainty": unc.tolist(), "length_m": float(length_px * scene.px_m), "unit": scene.unit,
        "max_rise": float(surface.max() - surface.min()),
    }


EXPLOSION_NOTE = (
    "Cube-root scaled-distance (Z = R / W^(1/3)) structural-damage radii, the same category of screening "
    "table used in industrial quantity-distance planning. It reports damage bands for buildings only: no "
    "casualty, injury or lethality figures are computed, and terrain shielding and blast confinement are "
    "not modelled."
)

BAND_LABELS = {"severe": "Severe structural damage", "moderate": "Moderate damage", "light": "Light / window damage"}


def _building_centroids(buildings: list[dict]) -> list[dict]:
    """Footprint centroid (pixel col,row), height and area for every building that has a usable footprint."""
    out = []
    for b in buildings:
        footprint = b.get("footprint") or []
        if len(footprint) < 3:
            continue
        pts = np.asarray(footprint, dtype=np.float64)
        out.append({
            "id": int(b["id"]), "col": float(pts[:, 0].mean()), "row": float(pts[:, 1].mean()),
            "height_m": b.get("height_m"), "area_px": int(b.get("area_px") or 0),
        })
    return out


def explosion_impact(scene: Scene, buildings: list[dict], col: float, row: float, yield_kg: float) -> dict:
    """Which detected buildings fall inside each scaled-distance damage band around a point."""
    from app.buildings.scenarios import SCALED_DISTANCE_BANDS

    h, w = scene.shape
    if not (0 <= col < w and 0 <= row < h):
        raise ValueError("The epicentre is outside the scene.")
    px = scene.px_m
    cents = _building_centroids(buildings)
    dist_px = {b["id"]: math.hypot(b["col"] - col, b["row"] - row) for b in cents}

    step = max(1, math.ceil(max(h, w) / 1024))
    grid_r = np.arange(0, h, step, dtype=np.float32)[:, None]
    grid_c = np.arange(0, w, step, dtype=np.float32)[None, :]
    grid_dist = np.hypot(grid_r - row, grid_c - col)

    bands = []
    for severity, z in SCALED_DISTANCE_BANDS:
        radius_m = z * (yield_kg ** (1.0 / 3.0))
        radius_px = radius_m / px
        inside = [b for b in cents if dist_px[b["id"]] <= radius_px]
        heights = [b["height_m"] for b in inside if b["height_m"] is not None and np.isfinite(b["height_m"])]
        bands.append({
            "severity": severity,
            "label": BAND_LABELS[severity],
            "scaled_distance": z,
            "radius_m": float(radius_m),
            "radius_px": float(radius_px),
            "area_km2": float((grid_dist <= radius_px).sum() * step * step * px * px / 1e6),
            "buildings": len(inside),
            "building_ids": [b["id"] for b in inside][:300],
            "footprint_m2": float(sum(b["area_px"] for b in inside) * px * px),
            "tallest_m": float(max(heights)) if heights else None,
        })

    def band_of(distance_px: float) -> Optional[str]:
        for band in bands:  # ordered severe -> moderate -> light
            if distance_px <= band["radius_px"]:
                return band["severity"]
        return None

    nearest = sorted(cents, key=lambda b: dist_px[b["id"]])[:8]
    return {
        "epicentre": {"col": float(col), "row": float(row)},
        "yield_kg": float(yield_kg),
        "total_buildings": len(cents),
        "bands": bands,
        "nearest": [{
            "id": b["id"], "distance_m": float(dist_px[b["id"]] * px), "height_m": b["height_m"],
            "band": band_of(dist_px[b["id"]]),
        } for b in nearest],
        "px_size_m": px,
        "is_metric": scene.is_metric,
        "note": EXPLOSION_NOTE,
    }


def wildfire_drop(scene: Scene, col: float, row: float, hover_agl_m: float, exit_velocity_mps: float) -> dict:
    """No-drag projectile drop for a hovering firefighting drone, anchored on the DSM at the fire point."""
    from app.buildings.scenarios import compute_drone_water_drop

    h, w = scene.shape
    if not (0 <= col < w and 0 <= row < h):
        raise ValueError("The fire location is outside the scene.")
    result = compute_drone_water_drop(scene.dsm, (col, row), hover_agl_m, exit_velocity_mps, dsm_is_metric=scene.is_metric)
    if result.get("status") != "computed":
        return result
    from app.landcover.classify import CLASS_NAMES

    r, c = int(round(row)), int(round(col))
    reach_m = float(result["horizontal_reach_m"])
    absolute = scene.kind == "absolute_dsm"
    terrain_z = float(scene.terrain[r, c]) if absolute and np.isfinite(scene.terrain[r, c]) else None
    # A single pixel on a roof edge reads a wall-steep slope; the median of a small window is the ground the fire sits on.
    window = scene.slope[max(r - 3, 0): r + 4, max(c - 3, 0): c + 4]
    window = window[np.isfinite(window)]
    slope = float(np.median(window)) if window.size else None
    result.update({
        "fire": {"col": float(col), "row": float(row)},
        "reach_px": reach_m / scene.px_m,
        "ground_elevation_m": terrain_z,
        # In a scene without a DEM every height is above local ground, so "elevation" is only a height there.
        "elevation_kind": "absolute" if absolute else "above_ground",
        "slope_deg": slope,
        "land_cover": CLASS_NAMES[int(scene.labels[r, c])],
        "px_size_m": scene.px_m,
        "hover_altitude_agl_m": float(hover_agl_m),
        "exit_velocity_mps": float(exit_velocity_mps),
    })
    return result
