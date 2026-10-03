"""What the Unity viewer actually draws: cleaned-up buildings, vehicles with real size/heading/colour, trees.

Why this exists. The building extractor (`app/buildings/segment.py`) is a height heuristic: it boxes
anything elevated, so bare winter trees and bridge decks come out as "buildings", and the viewer drew
every one of them as a white block. The DOTA oriented-box detector (`app/detect/objects.py`) finds
vehicles, pools, tanks and so on very well but has NO tree class, so trees cannot come from it.

Resulting split of responsibilities (all of it measured from this scene's own pixels):
  * vehicles / pools / tanks ... straight from the detector, sized from the oriented box, coloured
                                 from the photo under the box;
  * buildings ................... heuristic footprints, minus the ones that are really vegetation
                                 (warm/green and dim and not a clean rectangle, or mostly "tree" land
                                 cover), long thin rail/road slivers, or a cluster of parked cars
                                 (mostly covered by detected vehicles);
  * trees ....................... crowns laid out on a jittered hex grid (about one per 4.5 m) inside the
                                 tree land-cover mask plus the footprints rejected above. The *position
                                 pattern* is procedural; the vegetation mask, each crown's height (sampled
                                 from the height field) and its colour (sampled from the photo) are measured.

Every vehicle/pool/tank is a real detection. Dimensions are clamped to physically plausible ranges so a
bad box cannot produce a 30 m car.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Optional

import cv2
import numpy as np

from app.landcover.classify import TREE

MAX_TREES = 2500
MAX_OTHER_OBJECTS = 2500

# Vegetation-looking footprint: WARM or GREEN (mean R-B or G-B above a margin), dim, and not a clean
# rectangle. Measured on a winter scene: white/grey/tar/dark-blue roofs sit at R-B in [-18, 6]; bare brown
# trees at R-B >= 9 and grey level <= 125. (HSV saturation was tried first and rejected: very dark pixels
# have unstable saturation, which flagged a dark grey roof as a tree.)
TREE_WARM_MIN = 9.0        # mean(R) - mean(B)
TREE_GREEN_MIN = 8.0       # mean(G) - mean(B)
TREE_VALUE_MAX = 125.0     # mean grey level, 0-255
TREE_RECT_MAX = 0.88       # footprint area / min-area-rectangle: real roofs are close to 1
STRIP_ASPECT_MIN = 2.2     # long thin vegetation-coloured slivers are rail/road clutter, not trees
TREE_LABEL_FRACTION = 0.5
TREE_SPACING_M = 4.5
ROOF_PLATEAU_MIN_M = 8.0
ROOF_PLATEAU_ROUGHNESS = 0.3
MAX_TREE_HEIGHT_M = 22.0
VEHICLE_COVER_MAX = 0.35

# (min, max) metres for the long and short side of the oriented box, and a nominal height.
VEHICLE_LIMITS = {
    "small vehicle": {"length": (3.2, 6.0), "width": (1.5, 2.3), "height": 1.5, "kind": "vehicle"},
    "large vehicle": {"length": (6.0, 14.0), "width": (2.2, 2.9), "height": 3.2, "kind": "truck"},
}
OTHER_KINDS = {
    "storage tank": "tank", "swimming pool": "pool", "tennis court": "slab", "basketball court": "slab",
    "baseball diamond": "slab", "soccer ball field": "slab", "ground track field": "slab",
    "plane": "aircraft", "helicopter": "aircraft", "ship": "ship",
}
SLAB_HEIGHT_M = 0.08
NOMINAL_HEIGHT_M = {"tank": 6.0, "aircraft": 5.0, "ship": 8.0}


def _poly_crop(shape: tuple[int, int], poly: np.ndarray, pad: int = 0):
    """(y0, y1, x0, x1, mask) for one polygon on a local crop, or None when it is off-image."""
    h, w = shape
    x0, y0 = max(0, int(np.floor(poly[:, 0].min())) - pad), max(0, int(np.floor(poly[:, 1].min())) - pad)
    x1, y1 = min(w, int(np.ceil(poly[:, 0].max())) + 1 + pad), min(h, int(np.ceil(poly[:, 1].max())) + 1 + pad)
    if x1 <= x0 or y1 <= y0:
        return None
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(poly - [x0, y0]).astype(np.int32)], 1)
    return y0, y1, x0, x1, mask


def _vehicle_mask(shape: tuple[int, int], objects: list[dict[str, Any]]) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    for obj in objects:
        if obj.get("label") in VEHICLE_LIMITS and obj.get("polygon"):
            cv2.fillPoly(mask, [np.round(np.asarray(obj["polygon"], dtype=np.float64)).astype(np.int32)], 1)
    return mask.astype(bool)


def _shrink(mask: np.ndarray) -> np.ndarray:
    """Erode so edge pixels (walls, shadows, neighbours) do not contaminate a colour/texture sample."""
    eroded = cv2.erode(mask, np.ones((5, 5), np.uint8))
    return eroded if eroded.sum() >= 20 else mask


def classify_buildings(
    buildings: list[dict[str, Any]],
    rgb: np.ndarray,
    labels: Optional[np.ndarray],
    objects: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[np.ndarray], dict[str, int]]:
    """Split heuristic footprints into real buildings, vegetation (kept as tree masks), clutter and car clusters."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
    rgbf = rgb.astype(np.float32)
    vehicles = _vehicle_mask(rgb.shape[:2], objects)

    kept: list[dict[str, Any]] = []
    tree_masks: list[np.ndarray] = []
    stats = {"input": len(buildings), "dropped_vegetation": 0, "dropped_clutter": 0, "dropped_vehicle_cluster": 0}
    for b in buildings:
        footprint = np.asarray(b.get("footprint") or [], dtype=np.float64)
        if len(footprint) < 3:
            continue
        crop = _poly_crop(rgb.shape[:2], footprint)
        if crop is None:
            kept.append(b)
            continue
        y0, y1, x0, x1, full = crop
        sel = _shrink(full).astype(bool)
        window = (slice(y0, y1), slice(x0, x1))

        if vehicles[window][full.astype(bool)].mean() >= VEHICLE_COVER_MAX:
            stats["dropped_vehicle_cluster"] += 1
            continue

        tree_label = float((labels[window][sel] == TREE).mean()) if labels is not None else 0.0
        r, g, bl = (float(rgbf[window][..., i][sel].mean()) for i in range(3))
        poly32 = footprint.astype(np.float32)
        (_, _), (rw, rh), _ = cv2.minAreaRect(poly32)
        rectangularity = cv2.contourArea(poly32) / max(rw * rh, 1e-6)
        aspect = max(rw, rh) / max(min(rw, rh), 1e-6)
        vegetation_colour = (r - bl >= TREE_WARM_MIN or g - bl >= TREE_GREEN_MIN) and float(gray[window][sel].mean()) <= TREE_VALUE_MAX

        if tree_label >= TREE_LABEL_FRACTION or (vegetation_colour and rectangularity < TREE_RECT_MAX):
            if aspect >= STRIP_ASPECT_MIN and tree_label < TREE_LABEL_FRACTION:
                stats["dropped_clutter"] += 1
                continue
            stats["dropped_vegetation"] += 1
            whole = np.zeros(rgb.shape[:2], dtype=bool)
            whole[window] = full.astype(bool)
            tree_masks.append(whole)
            continue
        kept.append(b)
    stats["kept"] = len(kept)
    return kept, tree_masks, stats


def build_trees(
    rgb: np.ndarray,
    ndsm: np.ndarray,
    terrain: Optional[np.ndarray],
    labels: Optional[np.ndarray],
    extra_masks: list[np.ndarray],
    px_m: float,
    dsm_is_metric: bool,
    px_to_scene: Callable[[float, float], list[float]],
    building_footprints: Optional[list[list[list[float]]]] = None,
) -> list[dict[str, Any]]:
    """Crowns on a jittered hex grid inside the vegetation mask (deterministic, seeded).

    Footprints that stayed buildings are excluded: land cover sometimes paints a green roof or courtyard
    "tree", and a 20 m tree on top of a roof would be wrong."""
    mask = np.zeros(rgb.shape[:2], dtype=bool)
    if labels is not None:
        mask |= labels == TREE
    for extra in extra_masks:
        mask |= extra
    if building_footprints:
        roofs = np.zeros(rgb.shape[:2], dtype=np.uint8)
        for ring in building_footprints:
            cv2.fillPoly(roofs, [np.round(np.asarray(ring, dtype=np.float64)).astype(np.int32)], 1)
        mask &= ~cv2.dilate(roofs, np.ones((3, 3), np.uint8)).astype(bool)
    mask = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)).astype(bool)
    if not mask.any():
        return []

    h, w = mask.shape
    spacing = max(4.0, TREE_SPACING_M / max(px_m, 1e-3))
    height = np.nan_to_num(ndsm, nan=0.0).astype(np.float32)
    smooth = cv2.GaussianBlur(height, (0, 0), max(1.0, spacing / 4.0))
    if dsm_is_metric:
        # A tall, perfectly flat "tree" area is a green roof or terrace on a building, not a canopy.
        mean = cv2.blur(height, (7, 7))
        roughness = np.sqrt(np.maximum(cv2.blur(height * height, (7, 7)) - mean * mean, 0.0))
        mask &= ~((smooth > ROOF_PLATEAU_MIN_M) & (roughness < ROOF_PLATEAU_ROUGHNESS))
        if not mask.any():
            return []
    rng = np.random.default_rng(7)
    radius_px = max(2, int(round(spacing / 2)))

    candidates: list[tuple[int, int]] = []
    row_step = spacing * math.sqrt(3) / 2
    for line, y in enumerate(np.arange(spacing / 2, h, row_step)):
        offset = spacing / 2 if line % 2 else 0.0
        for x in np.arange(spacing / 2 + offset, w, spacing):
            jy, jx = rng.uniform(-0.25, 0.25, 2) * spacing
            row, col = int(round(y + jy)), int(round(x + jx))
            if 0 <= row < h and 0 <= col < w and mask[row, col]:
                candidates.append((row, col))
    if len(candidates) > MAX_TREES:  # thin evenly instead of keeping only one corner of the scene
        keep = np.sort(rng.choice(len(candidates), MAX_TREES, replace=False))
        candidates = [candidates[i] for i in keep]

    trees: list[dict[str, Any]] = []
    for row, col in candidates:
        y0, y1 = max(0, row - radius_px), min(h, row + radius_px + 1)
        x0, x1 = max(0, col - radius_px), min(w, col + radius_px + 1)
        yy, xx = np.ogrid[y0:y1, x0:x1]
        local = mask[y0:y1, x0:x1] & ((yy - row) ** 2 + (xx - col) ** 2 <= radius_px ** 2)
        if not local.any():
            continue
        tree_h = float(np.clip(smooth[row, col], 3.0, MAX_TREE_HEIGHT_M)) if dsm_is_metric else 5.0
        colour = np.median(rgb[y0:y1, x0:x1][local].reshape(-1, 3), axis=0)
        base = None
        if terrain is not None:
            ground = terrain[y0:y1, x0:x1][local]
            ground = ground[np.isfinite(ground)]
            base = float(np.median(ground)) if ground.size else None
        trees.append({
            "id": len(trees) + 1,
            "position": px_to_scene(float(col), float(row)),
            "height_m": round(tree_h, 2),
            "crown_radius_m": round(float(np.clip(0.22 * tree_h + 0.9, 1.5, 4.5)), 2),
            "color_rgb": [int(round(c)) for c in colour],
            "base_m": None if base is None else round(base, 2),
        })
    return trees


def _clamp(value: float, bounds: tuple[float, float]) -> float:
    return float(min(max(value, bounds[0]), bounds[1]))


def build_objects(
    objects: list[dict[str, Any]],
    rgb: np.ndarray,
    terrain: Optional[np.ndarray],
    src_size: tuple[int, int],
    world_size: tuple[float, float],
    px_to_scene: Callable[[float, float], list[float]],
) -> list[dict[str, Any]]:
    """Detections as sized, oriented, coloured shapes ready to draw."""
    src_h, src_w = src_size
    sx, sz = world_size[0] / src_w, world_size[1] / src_h  # metres per pixel on each axis
    out: list[dict[str, Any]] = []
    for obj in objects:
        label = obj.get("label", "")
        spec = VEHICLE_LIMITS.get(label)
        kind = spec["kind"] if spec else OTHER_KINDS.get(label)
        polygon = np.asarray(obj.get("polygon") or [], dtype=np.float64)
        if kind is None or len(polygon) != 4:
            continue

        # Box edges in metres; the longer pair gives the heading and the length.
        edges = [polygon[(i + 1) % 4] - polygon[i] for i in range(4)]
        metres = [math.hypot(e[0] * sx, e[1] * sz) for e in edges]
        long_edge = max(range(2), key=lambda i: metres[i])
        length, width = max(metres[0], metres[1]), min(metres[0], metres[1])
        direction = edges[long_edge]
        yaw = math.degrees(math.atan2(-direction[1] * sz, direction[0] * sx))  # CCW from east toward north

        if spec:
            length, width = _clamp(length, spec["length"]), _clamp(width, spec["width"])
            box_height = spec["height"]
        elif kind == "tank":
            length = width = max(length, width)
            box_height = float(obj["height_above_ground"]) if obj.get("height_reliable") and obj.get("height_above_ground") else NOMINAL_HEIGHT_M["tank"]
        elif kind in ("pool", "slab"):
            box_height = SLAB_HEIGHT_M
        else:
            box_height = NOMINAL_HEIGHT_M.get(kind, 4.0)

        crop = _poly_crop(rgb.shape[:2], polygon)
        colour = [150, 150, 150]
        base = None
        if crop is not None:
            y0, y1, x0, x1, full = crop
            sel = _shrink(full).astype(bool)
            colour = [int(round(c)) for c in np.median(rgb[y0:y1, x0:x1][sel].reshape(-1, 3), axis=0)]
            if terrain is not None:
                ground = terrain[y0:y1, x0:x1][full.astype(bool)]
                ground = ground[np.isfinite(ground)]
                base = float(np.median(ground)) if ground.size else None
        out.append({
            "id": obj["id"], "label": label, "kind": kind, "confidence": obj.get("confidence"),
            "center": px_to_scene(*obj["center_px"]),
            "yaw_deg": round(yaw, 1),
            "size_m": {"length": round(length, 2), "width": round(width, 2), "height": round(box_height, 2)},
            "color_rgb": colour,
            "base_m": None if base is None else round(base, 2),
            # kept for the existing consumers of this array
            "polygon": [px_to_scene(float(x), float(y)) for x, y in polygon],
            "surface_elevation": obj.get("surface_elevation"), "terrain_elevation": obj.get("terrain_elevation"),
            "height_above_ground": obj.get("height_above_ground"), "height_reliable": bool(obj.get("height_reliable")),
        })
    return out[:MAX_OTHER_OBJECTS]
