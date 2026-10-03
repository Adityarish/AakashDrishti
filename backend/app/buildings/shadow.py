"""Shadow-geometry height cross-check: H = L * tan(sun_elevation).

Requires a real sun elevation (image metadata or user override) and a metric pixel size; it is
skipped, never guessed, when either is missing. The shadow is measured from the building's
leading edge along the shadow azimuth. If no azimuth is known, one is estimated from the scene's
own shadow layout (circular mean over buildings), which is reported as an estimate.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from scipy import ndimage

from app.buildings.height import BuildingHeight
from app.core.logging import get_logger

logger = get_logger(__name__)

DEFAULT_SEARCH_RADIUS_PX = 60


@dataclass
class ShadowEstimate:
    building_id: int
    shadow_length_px: Optional[float]
    shadow_estimate_m: Optional[float]
    depth_vs_shadow_delta_m: Optional[float]
    sun_elevation_deg: Optional[float]
    note: str


@dataclass
class ShadowAnalysis:
    estimates: list[ShadowEstimate]
    azimuth_deg: Optional[float]
    azimuth_source: str  # "metadata" | "estimated" | "unknown"
    shadow_fraction: float = 0.0
    measured_count: int = 0
    notes: list[str] = field(default_factory=list)


def get_sun_elevation_from_metadata(path: Path) -> Optional[float]:
    from app.input.detect import get_sun_from_metadata

    return get_sun_from_metadata(path)[1]


def shadow_mask(rgb_image: np.ndarray) -> np.ndarray:
    """Dark pixels below an Otsu luminance threshold with a bluish cast, cleaned by opening."""
    gray = cv2.cvtColor(rgb_image, cv2.COLOR_RGB2GRAY)
    threshold, _ = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark = gray <= 0.72 * threshold
    red = rgb_image[..., 0].astype(np.float32) + 1.0
    blue = rgb_image[..., 2].astype(np.float32) + 1.0
    bluish = (blue / red) > 0.88
    mask = (dark & bluish).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    return mask.astype(bool)


def _circular_mean_deg(angles_deg: list[float], weights: list[float]) -> float:
    x = sum(w * math.cos(math.radians(a)) for a, w in zip(angles_deg, weights))
    y = sum(w * math.sin(math.radians(a)) for a, w in zip(angles_deg, weights))
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _direction_from_shadow_azimuth(shadow_azimuth_deg: float) -> np.ndarray:
    rad = math.radians(shadow_azimuth_deg)
    return np.array([math.sin(rad), -math.cos(rad)], dtype=np.float32)  # image x right, y down


def analyze_shadows(
    rgb_image: np.ndarray,
    footprints: list[list[tuple[float, float]]],
    labels: np.ndarray,
    sun_azimuth_deg: Optional[float] = None,
    sun_elevation_deg: Optional[float] = None,
    pixel_size_m: Optional[float] = None,
    building_heights: Optional[list[BuildingHeight]] = None,
    search_radius_px: int = DEFAULT_SEARCH_RADIUS_PX,
) -> ShadowAnalysis:
    if not footprints:
        return ShadowAnalysis([], sun_azimuth_deg, "metadata" if sun_azimuth_deg is not None else "unknown",
                              notes=["No building footprints to measure shadows for."])

    shadows = shadow_mask(rgb_image)
    building_mask = labels > 0
    height_by_id = {bh.id: bh for bh in (building_heights or [])}
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (search_radius_px, search_radius_px))

    measured: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    offsets: list[tuple[float, float]] = []
    # Work per footprint inside its padded bounding box: full-image dilate/compare per building
    # is O(buildings x pixels) and stalls the job on large scenes with many footprints.
    height, width = labels.shape
    slices = ndimage.find_objects(labels.astype(np.int32))
    pad = search_radius_px + 1
    for idx, footprint in enumerate(footprints, start=1):
        if idx > len(slices) or slices[idx - 1] is None:
            continue
        ys_sl, xs_sl = slices[idx - 1]
        y0, y1 = max(0, ys_sl.start - pad), min(height, ys_sl.stop + pad)
        x0, x1 = max(0, xs_sl.start - pad), min(width, xs_sl.stop + pad)
        footprint_mask = labels[y0:y1, x0:x1] == idx
        ring = cv2.dilate(footprint_mask.astype(np.uint8), kernel).astype(bool) & ~building_mask[y0:y1, x0:x1]
        candidate = ring & shadows[y0:y1, x0:x1]
        if candidate.sum() < 12:
            continue
        ys, xs = np.nonzero(candidate)
        points = np.stack([xs + x0, ys + y0], axis=1).astype(np.float32)
        centroid = np.array(footprint, dtype=np.float32).mean(axis=0)
        measured[idx] = (points, centroid, np.array(footprint, dtype=np.float32))
        vector = points.mean(axis=0) - centroid
        norm = float(np.linalg.norm(vector))
        if norm > 1e-3:
            offsets.append((float(vector[0]), float(vector[1])))

    azimuth = sun_azimuth_deg
    azimuth_source = "metadata"
    notes: list[str] = []
    if azimuth is None and offsets:
        shadow_azimuths = [(math.degrees(math.atan2(dx, -dy)) + 360.0) % 360.0 for dx, dy in offsets]
        weights = [math.hypot(dx, dy) for dx, dy in offsets]
        shadow_az = _circular_mean_deg(shadow_azimuths, weights)
        azimuth = (shadow_az + 180.0) % 360.0
        azimuth_source = "estimated"
        notes.append("Sun azimuth estimated from the scene's shadow layout.")
    elif azimuth is None:
        azimuth_source = "unknown"

    estimates: list[ShadowEstimate] = []
    measured_count = 0
    for idx, footprint in enumerate(footprints, start=1):
        entry = measured.get(idx)
        if entry is None or azimuth is None:
            estimates.append(ShadowEstimate(idx, None, None, None, sun_elevation_deg,
                                            "No usable shadow adjacent to this footprint."))
            continue
        points, _centroid, poly = entry
        direction = _direction_from_shadow_azimuth((azimuth + 180.0) % 360.0)
        leading_edge = float((poly @ direction).max())
        length_px = max(0.0, float((points @ direction).max()) - leading_edge)
        if length_px < 1.0:
            estimates.append(ShadowEstimate(idx, None, None, None, sun_elevation_deg,
                                            "Shadow not resolvable along the sun direction."))
            continue

        estimate_m: Optional[float] = None
        note = "Shadow length measured; sun elevation or pixel size unavailable so no metric height was computed."
        if sun_elevation_deg and pixel_size_m and sun_elevation_deg > 0:
            estimate_m = length_px * pixel_size_m * math.tan(math.radians(sun_elevation_deg))
            note = "shadow_estimate_m = shadow_length_px * pixel_size_m * tan(sun_elevation_deg)."
            measured_count += 1

        delta: Optional[float] = None
        bh = height_by_id.get(idx)
        if estimate_m is not None and bh is not None and bh.is_metric and bh.height_value is not None:
            delta = float(bh.height_value - estimate_m)
        estimates.append(ShadowEstimate(idx, length_px, estimate_m, delta, sun_elevation_deg, note))

    return ShadowAnalysis(
        estimates=estimates,
        azimuth_deg=azimuth,
        azimuth_source=azimuth_source,
        shadow_fraction=float(shadows.mean()),
        measured_count=measured_count,
        notes=notes,
    )


def estimate_shadow_heights(
    rgb_image: np.ndarray,
    footprints: list[list[tuple[float, float]]],
    labels: np.ndarray,
    sun_azimuth_deg: Optional[float] = None,
    sun_elevation_deg: Optional[float] = None,
    pixel_size_m: Optional[float] = None,
    building_heights: Optional[list[BuildingHeight]] = None,
    search_radius_px: int = DEFAULT_SEARCH_RADIUS_PX,
) -> list[ShadowEstimate]:
    return analyze_shadows(
        rgb_image, footprints, labels, sun_azimuth_deg, sun_elevation_deg, pixel_size_m,
        building_heights, search_radius_px,
    ).estimates
