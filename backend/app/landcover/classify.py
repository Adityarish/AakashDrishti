"""Heuristic six-class land-cover map: ground, low vegetation, building, water, road, tree.

Classical colour + height reasoning, not a trained segmentation head. It provides (a) a ground
mask for calibration, (b) semantic priors, (c) building masks for flood counting and (d) per-class
and per-landscape validation. Class ids follow the SRS order.

When the height checkpoint regresses metres above ground (the GAMUS fine-tune) the height field is
used directly; otherwise a local-minimum baseline stands in for ground level.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage

CLASS_NAMES = ["ground", "low_vegetation", "building", "water", "road", "tree"]
GROUND, LOW_VEG, BUILDING, WATER, ROAD, TREE = range(6)
CLASS_COLORS = [
    (176, 166, 146),
    (140, 200, 120),
    (231, 96, 78),
    (70, 130, 200),
    (110, 118, 130),
    (30, 120, 70),
]

# Semantic caps (metres of nDSM) per class, FR-16.
CLASS_HEIGHT_CAPS = {GROUND: 4.0, LOW_VEG: 3.0, BUILDING: 400.0, WATER: 0.0, ROAD: 0.0, TREE: 60.0}

AGL_ELEVATED_M = 1.5
AGL_TALL_M = 3.0


@dataclass
class LandCover:
    labels: np.ndarray  # HxW uint8 class ids
    counts: dict[str, int]

    def fractions(self) -> dict[str, float]:
        total = max(1, int(self.labels.size))
        return {name: self.counts.get(name, 0) / total for name in CLASS_NAMES}


def above_ground_height(rel_height: np.ndarray, height_is_agl: bool) -> np.ndarray:
    """Height above local ground in the field's own units."""
    finite = np.isfinite(rel_height)
    h = np.where(finite, rel_height, 0.0).astype(np.float32)
    if height_is_agl:
        ground = float(np.percentile(h[finite], 1.0)) if finite.any() else 0.0
        return np.maximum(h - ground, 0.0)
    factor = max(1, int(np.ceil(max(h.shape) / 768)))
    small = cv2.resize(h, (h.shape[1] // factor, h.shape[0] // factor), interpolation=cv2.INTER_AREA)
    baseline = ndimage.percentile_filter(small, 15, size=max(3, 61 // factor), mode="nearest")
    baseline = cv2.resize(baseline, (h.shape[1], h.shape[0]), interpolation=cv2.INTER_LINEAR)
    return np.maximum(h - baseline, 0.0)


def _remove_small(mask: np.ndarray, min_area: int) -> np.ndarray:
    labeled, count = ndimage.label(mask)
    if count == 0:
        return mask
    sizes = ndimage.sum(mask, labeled, index=np.arange(1, count + 1))
    keep = np.zeros(count + 1, dtype=bool)
    keep[1:] = sizes >= min_area
    return keep[labeled]


def classify_land_cover(
    rgb: np.ndarray,
    rel_height: np.ndarray,
    building_mask: np.ndarray,
    height_is_agl: bool = False,
) -> LandCover:
    height, width = rgb.shape[:2]
    scale = height * width / (1024.0 * 1024.0)
    small_object = max(24, int(60 * scale))

    img = rgb.astype(np.float32) / 255.0
    red, green, blue = img[..., 0], img[..., 1], img[..., 2]
    total = red + green + blue + 1e-6
    exg = (2 * green - red - blue) / total
    brightness = total / 3.0
    saturation = (img.max(axis=2) - img.min(axis=2)) / (img.max(axis=2) + 1e-6)

    above = above_ground_height(rel_height, height_is_agl)
    if height_is_agl:
        elevated_thr, tall_thr = AGL_ELEVATED_M, AGL_TALL_M
    else:
        finite = np.isfinite(rel_height)
        span = max(float(np.percentile(rel_height[finite], 99) - np.percentile(rel_height[finite], 1)), 1e-6) if finite.any() else 1.0
        elevated_thr, tall_thr = 0.05 * span, 0.12 * span
    elevated = above > elevated_thr
    tall = above > tall_thr

    vegetation = exg > 0.04
    near_tall = cv2.dilate(tall.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))).astype(bool)

    gray = (brightness * 255).astype(np.uint8)
    texture = cv2.GaussianBlur(cv2.Laplacian(gray, cv2.CV_32F, ksize=3) ** 2, (0, 0), 3.0)
    smooth = texture < np.percentile(texture, 35)

    water = (
        (blue >= red + 0.02) & (blue >= green - 0.02) & ~vegetation & smooth & ~elevated & ~near_tall & (brightness < 0.55)
    )
    water = _remove_small(
        cv2.morphologyEx(water.astype(np.uint8), cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)).astype(bool),
        max(1500, int(4000 * scale)),
    )

    road_candidate = (saturation < 0.25) & ~vegetation & ~water & ~elevated & (brightness > 0.10) & ~building_mask
    road = _remove_small(
        cv2.morphologyEx(road_candidate.astype(np.uint8), cv2.MORPH_OPEN, np.ones((5, 5), np.uint8)).astype(bool),
        max(300, int(1200 * scale)),
    )

    labels = np.full((height, width), GROUND, dtype=np.uint8)
    labels[vegetation & ~tall] = LOW_VEG
    labels[road] = ROAD
    labels[tall & vegetation] = TREE
    if height_is_agl:
        labels[tall & ~building_mask & ~water] = TREE
        labels[elevated & ~tall & ~building_mask & ~water & ~road] = LOW_VEG
    else:
        labels[elevated & ~vegetation & ~building_mask & ~water] = BUILDING
    labels[building_mask] = BUILDING
    labels[water] = WATER

    small_tree = (labels == TREE) & ~_remove_small(labels == TREE, small_object)
    labels[small_tree] = LOW_VEG

    counts = {name: int((labels == idx).sum()) for idx, name in enumerate(CLASS_NAMES)}
    return LandCover(labels=labels, counts=counts)


def class_color_image(labels: np.ndarray) -> np.ndarray:
    palette = np.array(CLASS_COLORS, dtype=np.uint8)
    return palette[np.clip(labels, 0, len(palette) - 1)]
