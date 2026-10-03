"""Per-building height from footprint masks + the calibrated DSM/rDSM.

Uses the 90th percentile (not max) of in-footprint height values, per
IMPLEMENTATION.md/research-notes.md guidance that roof-edge DSM noise
(mixed pixels at the roof boundary, guided-filter halo) can spike well
above the true roof height -- p90 is a cheap, real-data-derived way to
reject that tail without fabricating a correction model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import ndimage


@dataclass
class BuildingHeight:
    id: int
    footprint: list[tuple[float, float]]
    area_px: int
    height_value: Optional[float]  # meters if is_metric else relative DSM units
    is_metric: bool
    mean_confidence: Optional[float]


def compute_building_heights(
    footprints: list[list[tuple[float, float]]],
    labels: np.ndarray,
    dsm_height: np.ndarray,
    confidence: Optional[np.ndarray],
    is_metric: bool,
    percentile: float = 90.0,
) -> list[BuildingHeight]:
    """One BuildingHeight per label id in `labels` (1..len(footprints))."""
    results: list[BuildingHeight] = []
    # Per-building work stays inside its bounding box (full-raster `labels == idx` per building
    # is O(buildings x pixels) and stalls large scenes).
    boxes = ndimage.find_objects(labels.astype(np.int32))

    for idx, footprint in enumerate(footprints, start=1):
        box = boxes[idx - 1] if idx <= len(boxes) else None
        mask = (labels[box] == idx) if box is not None else np.zeros((0, 0), dtype=bool)
        area_px = int(mask.sum())
        if area_px == 0:
            # Footprint polygon exists but the label mask doesn't (shouldn't
            # happen given segment.py always draws the contour it returns a
            # polygon for, but degrade gracefully rather than crash).
            results.append(
                BuildingHeight(
                    id=idx, footprint=footprint, area_px=0, height_value=None, is_metric=is_metric, mean_confidence=None
                )
            )
            continue

        values = dsm_height[box][mask]
        finite_values = values[np.isfinite(values)]
        height_value = float(np.percentile(finite_values, percentile)) if finite_values.size > 0 else None

        mean_confidence = None
        if confidence is not None:
            conf_values = confidence[box][mask]
            finite_conf = conf_values[np.isfinite(conf_values)]
            if finite_conf.size > 0:
                mean_confidence = float(finite_conf.mean())

        results.append(
            BuildingHeight(
                id=idx,
                footprint=footprint,
                area_px=area_px,
                height_value=height_value,
                is_metric=is_metric,
                mean_confidence=mean_confidence,
            )
        )

    return results


def scale_buildings_to_reference(
    buildings: list[dict],
    reference_building_id: int,
    reference_height_m: float,
) -> Optional[dict]:
    """Rescale a scene's relative building heights using one user-supplied
    real-world height as an anchor -- a single-point Ground Control Point,
    per the problem statement's "minimal Ground Control Points" calibration
    option (PRD.md), for scenes with no GeoTIFF/SRTM/GCP data at all.

    This is NOT the same as DEM/GCP-verified metric calibration
    (app/calibration/srtm.py) -- it is a linear rescale anchored on exactly
    one caller-supplied fact, so it inherits all of that single measurement's
    error and any segmentation/height-estimation error in the reference
    building itself. Callers (the API layer) must label results from this
    function as "reference-scaled", never as "calibrated" or "metric DSM".

    Returns None if the reference building isn't found or has no usable
    (positive, finite) relative height -- never fabricates a scale.
    """
    reference = next((b for b in buildings if b["id"] == reference_building_id), None)
    if reference is None:
        return None
    ref_value = reference.get("height_m")
    if ref_value is None or not np.isfinite(ref_value) or ref_value <= 0 or reference_height_m <= 0:
        return None

    scale = reference_height_m / ref_value
    scaled = []
    for b in buildings:
        value = b.get("height_m")
        scaled.append(
            {
                **b,
                "height_m": (value * scale) if value is not None and np.isfinite(value) else None,
                "is_metric": False,  # deliberately not True -- see docstring, this is not verified-metric
            }
        )
    return {
        "scale_factor": scale,
        "reference_building_id": reference_building_id,
        "reference_height_m": reference_height_m,
        "buildings": scaled,
    }


def scale_buildings_to_reference_multi(
    buildings: list[dict],
    points: list[tuple[int, float]],
) -> Optional[dict]:
    """Same idea as `scale_buildings_to_reference` but for 3+ user-supplied
    reference heights (PRD.md "minimal Ground Control Points... GCP
    refinement"): fits scale AND offset `height_m * s + t` by ordinary least
    squares over the given (building_id, reference_height_m) pairs, instead
    of anchoring on exactly one point. With fewer than 2 usable points this
    falls back to the same pure-ratio (t=0) behavior as the single-point
    function, since scale+offset is underdetermined from one sample.

    Still explicitly NOT the same as DEM/GCP-verified metric calibration --
    see the single-point function's docstring; callers must label results
    "reference-scaled", not "calibrated".

    Returns None if no supplied point resolves to a usable (finite,
    positive) building height -- never fabricates a fit.
    """
    by_id = {b["id"]: b for b in buildings}
    pairs: list[tuple[float, float]] = []
    used_points: list[dict] = []
    for building_id, reference_height_m in points:
        b = by_id.get(building_id)
        if b is None or reference_height_m <= 0:
            continue
        value = b.get("height_m")
        if value is None or not np.isfinite(value) or value <= 0:
            continue
        pairs.append((float(value), float(reference_height_m)))
        used_points.append({"building_id": building_id, "reference_height_m": reference_height_m})

    if not pairs:
        return None

    x = np.array([p[0] for p in pairs], dtype=np.float64)
    y = np.array([p[1] for p in pairs], dtype=np.float64)

    if len(pairs) < 2:
        scale, offset = float(y[0] / x[0]), 0.0
    else:
        design = np.vstack([x, np.ones_like(x)]).T
        (scale, offset), *_ = np.linalg.lstsq(design, y, rcond=None)
        scale, offset = float(scale), float(offset)
        if not np.isfinite(scale) or scale <= 0:
            # Degenerate affine fit (e.g. near-constant heights): fall back to a
            # forced-through-origin least-squares scale, still real least squares.
            scale, offset = float(np.sum(x * y) / np.sum(x * x)), 0.0

    residuals = scale * x + offset - y
    residual_rmse_m = float(np.sqrt(np.mean(residuals**2)))

    scaled = []
    for b in buildings:
        value = b.get("height_m")
        scaled.append(
            {
                **b,
                "height_m": (value * scale + offset) if value is not None and np.isfinite(value) else None,
                "is_metric": False,  # unverified reference points, same as the single-point function
            }
        )
    return {
        "scale_factor": scale,
        "offset_m": offset,
        "residual_rmse_m": residual_rmse_m,
        "reference_points": used_points,
        "buildings": scaled,
    }
