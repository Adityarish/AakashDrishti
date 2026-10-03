"""Heuristic disaster-management decision-support layers.

Every function here produces DECISION-SUPPORT SUGGESTIONS ONLY, derived
from real pixel statistics on the estimated DSM/rDSM and building
footprints -- none of these are certified surveys, and none should be
presented as authoritative for actual emergency operations without expert
review and ground-truthing. This module exists to demonstrate the kind of
analysis AakashDrishti's height data enables (research-notes.md
"differentiating USPs"), not to replace real disaster-response planning.

Coordinate handling reuses the same affine-transform convention as
`app/dsm/generate.py` / `app/geospatial/raster_io.py`: `geo.transform` is a
GDAL-style 6-tuple consumed via `rasterio.Affine(*geo.transform)`. Pixel
spacing in meters reuses the geographic/projected-CRS approximation from
`app/mesh/generate.py::_geo_pixel_spacing_meters` (imported directly rather
than reimplemented) when `geo` is available; otherwise slope is expressed
per pixel-unit rather than per meter (not geographically calibrated, but
never a fabricated conversion factor).
"""

from __future__ import annotations

import math
from typing import Optional

import cv2
import numpy as np
import rasterio
from scipy import ndimage

from app.buildings.height import BuildingHeight
from app.input.detect import GeoMetadata
from app.mesh.generate import _geo_pixel_spacing_meters  # reuse: see module docstring

DEFAULT_LANDING_MIN_AREA_PX = 400
DEFAULT_LANDING_MAX_SLOPE_DEG = 5.0
DEFAULT_LANDING_MAX_ZONES = 10

DEFAULT_FLOOD_WINDOW_PX = 61
DEFAULT_FLOOD_MIN_AREA_PX = 300
DEFAULT_FLOOD_ROUGHNESS_MULT = 1.5

DEFAULT_FIRE_HEIGHT_THRESHOLD_M = 30.0
DEFAULT_FIRE_DENSITY_RADIUS_PX = 150
DEFAULT_FIRE_HIGH_DENSITY_COUNT = 5
DEFAULT_FIRE_MEDIUM_DENSITY_COUNT = 2

# Illustrative reference footprints for landing-zone aircraft-fit checks --
# NOT certified specs of any real aircraft/regulatory standard, same
# "illustrative, not real product specs" convention as the drone defaults in
# app/buildings/scenarios.py (compute_drone_water_drop).
HELICOPTER_MIN_CLEAR_DIAMETER_M = 14.0
PLANE_MIN_STRIP_WIDTH_M = 11.0
PLANE_MIN_STRIP_LENGTH_M = 150.0


def _pixel_spacing(geo: Optional[GeoMetadata]) -> tuple[float, float, str]:
    if geo is None:
        return 1.0, 1.0, "pixels"
    dx, dz = _geo_pixel_spacing_meters(geo)
    return dx, dz, "meters"


def _mask_to_polygons(
    mask: np.ndarray, geo: Optional[GeoMetadata], offset_xy: tuple[int, int] = (0, 0)
) -> list[list[list[float]]]:
    """Contours of a boolean mask -> list of polygons, each a list of
    [x, y] pixel coords, or [map_x, map_y] if `geo` is given. `offset_xy` is the (x, y) pixel
    position of `mask`'s top-left corner in the full image when `mask` is a bounding-box crop."""
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
                                   offset=offset_xy)
    affine = rasterio.Affine(*geo.transform) if geo is not None else None

    polygons: list[list[list[float]]] = []
    for contour in contours:
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.01 * peri, True)
        if len(approx) < 3:
            continue
        ring: list[list[float]] = []
        for pt in approx:
            x, y = float(pt[0][0]), float(pt[0][1])
            if affine is not None:
                mx, my = affine * (x, y)
                ring.append([mx, my])
            else:
                ring.append([x, y])
        polygons.append(ring)
    return polygons


def assess_aircraft_fit(
    width_m: Optional[float],
    length_m: Optional[float],
    aircraft_type: str,
) -> dict:
    """Compare a landing-zone candidate's measured clear-area dimensions
    against an illustrative reference footprint for `aircraft_type`
    ("helicopter" | "plane") -- see HELICOPTER_MIN_CLEAR_DIAMETER_M /
    PLANE_MIN_STRIP_WIDTH_M / PLANE_MIN_STRIP_LENGTH_M above. These are
    illustrative reference figures, NOT certified aircraft specs or a
    regulatory landing-site standard.

    `width_m`/`length_m` here are BOTH the diameter of the zone's largest
    inscribed clear circle (see find_emergency_landing_zones's distance-
    transform comment) -- i.e. a real, guaranteed-obstacle-free circular
    area, not an independently-measured rectangle. A plane needs a long,
    narrow strip, which this heuristic cannot actually detect (it only finds
    the best circular clearing); the safe, honest translation is to require
    the clearing to be big enough to contain a square of side
    `required_length_m` INSCRIBED IN THE CIRCLE (side = diameter / sqrt(2)),
    not merely `diameter >= required_length_m` -- the latter would mark a
    150m-diameter circle as "fits" for a 150m-long strip, but a 150x11
    rectangle centered in that circle has corners ~53m outside the circle's
    edge, i.e. potentially over a building or other obstacle the distance
    transform never verified as clear. Using the inscribed-square side
    guarantees the reported footprint is geometrically contained within the
    verified-clear area, at the cost of being a much stricter (and much
    less often satisfied) plane-fit check than before -- more accurate, not
    a regression.

    `fits` and the margins are `None` (never guessed) when `width_m`/
    `length_m` are `None` -- i.e. the job has no real pixel spacing to
    measure the zone in meters, so aircraft fit is genuinely unknown rather
    than approximated in pixel units.
    """
    if aircraft_type == "helicopter":
        required_width_m = HELICOPTER_MIN_CLEAR_DIAMETER_M
        required_length_m = HELICOPTER_MIN_CLEAR_DIAMETER_M
    elif aircraft_type == "plane":
        required_width_m = PLANE_MIN_STRIP_WIDTH_M
        required_length_m = PLANE_MIN_STRIP_LENGTH_M
    else:
        raise ValueError(f"Unknown aircraft_type: {aircraft_type!r} (expected 'helicopter' or 'plane')")

    if width_m is None or length_m is None:
        return {
            "fits": None,
            "aircraft_type": aircraft_type,
            "required_width_m": required_width_m,
            "required_length_m": required_length_m,
            "margin_width_m": None,
            "margin_length_m": None,
        }

    if aircraft_type == "helicopter":
        # Circle-in-circle: the reported diameter itself is the safe,
        # geometrically-guaranteed comparison -- no correction needed.
        diameter_m = min(width_m, length_m)
        fits = diameter_m >= required_width_m
        margin_width_m = margin_length_m = diameter_m - required_width_m
    else:
        # Square-in-circle (see docstring): only the inscribed-square side
        # is geometrically guaranteed to lie entirely within the verified-
        # clear circle.
        diameter_m = min(width_m, length_m)
        inscribed_square_side_m = diameter_m / math.sqrt(2)
        fits = inscribed_square_side_m >= required_length_m and inscribed_square_side_m >= required_width_m
        margin_width_m = inscribed_square_side_m - required_width_m
        margin_length_m = inscribed_square_side_m - required_length_m

    return {
        "fits": bool(fits),
        "aircraft_type": aircraft_type,
        "required_width_m": required_width_m,
        "required_length_m": required_length_m,
        "margin_width_m": margin_width_m,
        "margin_length_m": margin_length_m,
    }


def find_emergency_landing_zones(
    dsm_height: np.ndarray,
    building_mask: np.ndarray,
    geo: Optional[GeoMetadata] = None,
    min_area_px: int = DEFAULT_LANDING_MIN_AREA_PX,
    max_slope_deg: float = DEFAULT_LANDING_MAX_SLOPE_DEG,
    max_zones: int = DEFAULT_LANDING_MAX_ZONES,
    aircraft_type: Optional[str] = None,
) -> list[dict]:
    """Heuristic decision support ONLY -- not a certified landing survey.

    Finds contiguous, low-slope, building-free regions, ranked by area
    (larger first) then flatness (lower slope variance first).
    """
    finite = np.isfinite(dsm_height)
    if finite.sum() < min_area_px:
        return []

    dx, dz, units = _pixel_spacing(geo)
    gy, gx = np.gradient(np.where(finite, dsm_height, 0.0), dz, dx)
    slope_deg = np.degrees(np.arctan(np.hypot(gx, gy)))

    candidate = finite & (~building_mask) & (slope_deg <= max_slope_deg)
    if not candidate.any():
        return []

    labeled, _n_labels = ndimage.label(candidate)
    features: list[dict] = []
    # Work inside each region's bounding box: `labeled == id` on the full raster per region is
    # O(regions x pixels), which stalls the job on large scenes.
    for label_id, box in enumerate(ndimage.find_objects(labeled), start=1):
        if box is None:
            continue
        y0, x0 = box[0].start, box[1].start
        region = labeled[box] == label_id
        area_px = int(region.sum())
        if area_px < min_area_px:
            continue
        slope_variance = float(np.var(slope_deg[box][region]))
        polygons = _mask_to_polygons(region, geo, (x0, y0))
        if not polygons:
            continue

        # A real candidate "flat, building-free" connected region in an
        # actual scene is rarely a single compact clearing -- roads,
        # sidewalks, and yards around buildings are usually all connected
        # together into one large, non-convex, snake-shaped blob. Using that
        # blob's `cv2.minAreaRect` CENTER as the landing point is wrong: a
        # rotated bounding rect's center has no guarantee of falling inside
        # a non-convex shape, and in practice lands squarely on a building
        # gap between two arms of the snake. Instead, find the single safest
        # point via a distance transform: for every region pixel, its value
        # is the distance to the nearest non-region (building/steep) pixel,
        # so the pixel with the MAXIMUM value is the center of the largest
        # circle that fits entirely inside real open ground -- guaranteed to
        # be a real usable point, with a real, locally-meaningful clear
        # diameter (not the misleading bounding-box size of the whole
        # sprawling blob).
        # `cv2.distanceTransform` does NOT treat the array boundary as an
        # obstacle -- a region touching the image edge gets an artificially
        # inflated, meaningless distance near that edge (nothing is actually
        # there to be "far from"), so the peak collapses onto a corner/edge
        # pixel instead of a genuine interior clearing. Pad with a 1px false
        # border first so the image edge itself counts as an obstacle, then
        # subtract the padding back out of the resulting index.
        padded = np.pad(region, 1, mode="constant", constant_values=False)
        dist = cv2.distanceTransform(padded.astype(np.uint8), cv2.DIST_L2, 5)
        peak_idx = int(np.argmax(dist))
        peak_y, peak_x = np.unravel_index(peak_idx, dist.shape)
        peak_y, peak_x = peak_y - 1 + y0, peak_x - 1 + x0
        clear_radius_px = float(dist[peak_y - y0 + 1, peak_x - x0 + 1])

        width_px = length_px = 2.0 * clear_radius_px
        angle_deg = 0.0  # a circular clearing has no meaningful orientation
        center_px = [float(peak_x), float(peak_y)]
        # A single x/y pixel spacing doesn't cleanly apply to a diagonal
        # clearance, so use the mean spacing (dx+dz)/2, same approximation
        # `simulate_explosion_impact` (app/buildings/scenarios.py) uses for
        # radii. Always computed (not gated on `units == "meters"`) --
        # `_pixel_spacing` already falls back to (1.0, 1.0, "pixels") when
        # ungeoreferenced, same graceful-degradation pattern
        # `simulate_explosion_impact` uses, so aircraft-fit/footprint
        # visualization still works (with an honest "pixels" `spacing_units`
        # flag, not a fabricated real distance) instead of going dead on
        # every non-georeferenced test image.
        mean_spacing = (dx + dz) / 2.0
        width_m = width_px * mean_spacing
        length_m = length_px * mean_spacing

        properties: dict = {
            "zone_type": "landing_zone",
            "area_px": area_px,
            "slope_variance_deg2": slope_variance,
            "spacing_units": units,
            "width_px": width_px,
            "length_px": length_px,
            "angle_deg": angle_deg,
            "center_px": center_px,
            "width_m": width_m,
            "length_m": length_m,
            "note": "Heuristic decision support: low-slope, building-free region. Not a certified LZ survey.",
        }
        if aircraft_type is not None:
            properties["aircraft_fit"] = assess_aircraft_fit(width_m, length_m, aircraft_type)

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [polygons[0]]},
                "properties": properties,
            }
        )

    features.sort(key=lambda f: (-f["properties"]["area_px"], f["properties"]["slope_variance_deg2"]))
    return features[:max_zones]


def find_flood_risk_zones(
    dsm_height: np.ndarray,
    geo: Optional[GeoMetadata] = None,
    building_mask: Optional[np.ndarray] = None,
    window_px: int = DEFAULT_FLOOD_WINDOW_PX,
    dsm_is_metric: bool = False,
    depth_threshold: float = 1.0,
    min_area_px: int = DEFAULT_FLOOD_MIN_AREA_PX,
    roughness_mult: float = DEFAULT_FLOOD_ROUGHNESS_MULT,
) -> list[dict]:
    """Heuristic decision support ONLY. Flags local depressions -- cells
    meaningfully below their local neighborhood mean -- as candidate flood
    accumulation risk zones. `depth_threshold` is in meters if
    `dsm_is_metric`, else in the DSM's relative units (flagged in output).

    `building_mask`, when given, is excluded from both the depression
    candidates and the neighborhood-mean baseline: a real building's height
    spike would otherwise drag the local mean up and flag the flat ground
    around it as a "depression" -- an artifact of the DSM now carrying real
    building relief, not an actual low spot.

    On dense scenes the classical-CV building segmentation (app/buildings/segment.py)
    only finds a fraction of real footprints (e.g. attached rowhouses), so most rooftops
    still count as "ground" here -- their ordinary roof-to-roof height variation would
    otherwise get flagged as thousands of tiny "depressions" tracing every rooftop edge.
    Two guards against that, on top of the building-mask exclusion: a wide averaging
    window (`window_px`, urban-block scale rather than single-building scale) so
    building-scale bumps wash out of the local mean, and a local-roughness-adaptive
    threshold (`deficit > max(depth_threshold, roughness_mult * local_std)`) so a patch
    of terrain needs a genuinely anomalous dip relative to its own neighborhood's normal
    variability, not just any dip past a flat absolute cutoff -- a flat field and a jumbled
    rooftop-line get different effective thresholds automatically."""
    finite = np.isfinite(dsm_height)
    if building_mask is not None:
        finite = finite & ~building_mask
    if finite.sum() < min_area_px:
        return []

    filled = np.where(finite, dsm_height, 0.0).astype(np.float32)
    finite_f = finite.astype(np.float32)
    sum_vals = ndimage.uniform_filter(filled, size=window_px, mode="nearest")
    sumsq_vals = ndimage.uniform_filter(filled * filled, size=window_px, mode="nearest")
    count_vals = ndimage.uniform_filter(finite_f, size=window_px, mode="nearest")
    with np.errstate(invalid="ignore", divide="ignore"):
        local_mean = sum_vals / np.maximum(count_vals, 1e-6)
        local_var = sumsq_vals / np.maximum(count_vals, 1e-6) - local_mean**2
    local_std = np.sqrt(np.clip(local_var, 0.0, None))

    deficit = local_mean - dsm_height
    effective_threshold = np.maximum(depth_threshold, roughness_mult * local_std)
    depression = finite & (deficit > effective_threshold)
    if not depression.any():
        return []

    labeled, _n_labels = ndimage.label(depression)
    features: list[dict] = []
    for label_id, box in enumerate(ndimage.find_objects(labeled), start=1):
        if box is None:
            continue
        region = labeled[box] == label_id
        area_px = int(region.sum())
        if area_px < min_area_px:
            continue
        mean_deficit = float(deficit[box][region].mean())
        polygons = _mask_to_polygons(region, geo, (box[1].start, box[0].start))
        if not polygons:
            continue
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [polygons[0]]},
                "properties": {
                    "zone_type": "flood_risk_zone",
                    "area_px": area_px,
                    "mean_depth_deficit": mean_deficit,
                    "unit": "meters" if dsm_is_metric else "relative_dsm_units",
                    "note": "Heuristic decision support: local elevation depression vs. neighborhood mean. Not a hydrological flood model.",
                },
            }
        )

    features.sort(key=lambda f: -f["properties"]["area_px"])
    return features


def find_highrise_fire_access_risk(
    buildings: list[BuildingHeight],
    geo: Optional[GeoMetadata] = None,
    height_threshold_m: float = DEFAULT_FIRE_HEIGHT_THRESHOLD_M,
    density_radius_px: float = DEFAULT_FIRE_DENSITY_RADIUS_PX,
    high_density_count: int = DEFAULT_FIRE_HIGH_DENSITY_COUNT,
    medium_density_count: int = DEFAULT_FIRE_MEDIUM_DENSITY_COUNT,
) -> list[dict]:
    """Heuristic decision support ONLY. Flags tall buildings (above
    `height_threshold_m` if metric, else the scene's own 90th-percentile
    height if not) that also sit in a dense cluster of other footprints
    (a proxy for narrow/constrained access, not measured street width)."""
    valid_buildings = [b for b in buildings if b.height_value is not None]
    if not valid_buildings:
        return []

    is_metric = valid_buildings[0].is_metric
    if is_metric:
        threshold = height_threshold_m
    else:
        threshold = float(np.percentile([b.height_value for b in valid_buildings], 90))

    tall_buildings = [b for b in valid_buildings if b.height_value >= threshold]
    if not tall_buildings:
        return []

    centroids = {
        b.id: np.mean(np.asarray(b.footprint, dtype=np.float32), axis=0) for b in valid_buildings
    }
    affine = rasterio.Affine(*geo.transform) if geo is not None else None

    features: list[dict] = []
    for b in tall_buildings:
        c = centroids[b.id]
        neighbor_count = 0
        for other in valid_buildings:
            if other.id == b.id:
                continue
            dist = float(np.linalg.norm(centroids[other.id] - c))
            if dist <= density_radius_px:
                neighbor_count += 1

        if neighbor_count >= high_density_count:
            risk_level = "high"
        elif neighbor_count >= medium_density_count:
            risk_level = "medium"
        else:
            risk_level = "low"

        ring = []
        for x, y in b.footprint:
            if affine is not None:
                mx, my = affine * (x, y)
                ring.append([mx, my])
            else:
                ring.append([float(x), float(y)])

        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "zone_type": "fire_access_risk",
                    "building_id": b.id,
                    "height_value": b.height_value,
                    "is_metric": b.is_metric,
                    "neighbor_count_within_radius": neighbor_count,
                    "risk_level": risk_level,
                    "note": (
                        "Heuristic decision support: tall building + dense neighboring-footprint proxy for "
                        "constrained access. Not a measured street width or certified fire-access assessment."
                    ),
                },
            }
        )

    return features
