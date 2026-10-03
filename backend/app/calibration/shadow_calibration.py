"""Shadow-geometry cross-check on the pipeline's height field (PRD.md /
research-notes.md "shadow-geometry cross-check ... fuse ... rather than
trusting one method"): compares the per-building shadow-derived heights
(app/buildings/shadow.py, real trigonometry, no DEM needed) against the
same buildings' depth-model heights, and blends the two when they disagree.

This only ever fires when the input is georeferenced AND a sun elevation
angle was found in the image metadata AND at least a handful of buildings
have both a shadow estimate and a depth estimate (shadow.py already
requires pixel spacing, which requires `geo`) -- for a plain non-
georeferenced PNG/JPG there is no way to get a shadow_estimate_m at all, so
this always returns "insufficient_data" for those.

Deliberately does NOT rescale an already DEM/SRTM-verified DSM: a real
reference DEM is a stronger source of truth than a classical-CV shadow
heuristic, so a verified calibration is reported alongside the shadow
cross-check for transparency but never silently overridden by it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.buildings.height import BuildingHeight
from app.buildings.shadow import ShadowEstimate

DEFAULT_DEVIATION_THRESHOLD = 0.2
DEFAULT_MIN_BUILDINGS = 3


@dataclass
class ShadowCrossCheckResult:
    status: str  # "insufficient_data" | "skipped_metric_dsm" | "consistent_no_change" | "applied"
    note: str
    dsm_height: np.ndarray
    dsm_is_metric: bool
    scale_factor: Optional[float]
    median_ratio: Optional[float]
    n_buildings_used: int


def apply_shadow_cross_check(
    dsm_height: np.ndarray,
    dsm_is_metric: bool,
    building_heights: list[BuildingHeight],
    shadow_estimates: list[ShadowEstimate],
    deviation_threshold: float = DEFAULT_DEVIATION_THRESHOLD,
    min_buildings: int = DEFAULT_MIN_BUILDINGS,
) -> ShadowCrossCheckResult:
    shadow_by_id = {s.building_id: s.shadow_estimate_m for s in shadow_estimates if s.shadow_estimate_m is not None}
    height_by_id = {
        b.id: b.height_value
        for b in building_heights
        if b.height_value is not None and np.isfinite(b.height_value) and b.height_value > 0
    }
    common_ids = sorted(shadow_by_id.keys() & height_by_id.keys())
    ratios = [shadow_by_id[i] / height_by_id[i] for i in common_ids]

    if len(ratios) < min_buildings:
        return ShadowCrossCheckResult(
            status="insufficient_data",
            note=(
                f"Only {len(ratios)} building(s) have both a shadow-length estimate and a depth-model "
                f"height (need >= {min_buildings}); shadow cross-check skipped. This needs a "
                "georeferenced input with a sun elevation angle in its metadata, plus a clear building "
                "shadow adjacent to the footprint."
            ),
            dsm_height=dsm_height,
            dsm_is_metric=dsm_is_metric,
            scale_factor=None,
            median_ratio=None,
            n_buildings_used=len(ratios),
        )

    median_ratio = float(np.median(ratios))

    if dsm_is_metric:
        return ShadowCrossCheckResult(
            status="skipped_metric_dsm",
            note=(
                f"Shadow cross-check on {len(ratios)} building(s) gives a median shadow/depth ratio of "
                f"{median_ratio:.2f}, shown for information only -- this job's DSM is already "
                "DEM/SRTM-verified, which is a stronger source of truth than the shadow heuristic, so "
                "it was NOT rescaled."
            ),
            dsm_height=dsm_height,
            dsm_is_metric=dsm_is_metric,
            scale_factor=None,
            median_ratio=median_ratio,
            n_buildings_used=len(ratios),
        )

    if abs(median_ratio - 1.0) <= deviation_threshold:
        return ShadowCrossCheckResult(
            status="consistent_no_change",
            note=(
                f"Shadow cross-check on {len(ratios)} building(s) gives a median shadow/depth ratio of "
                f"{median_ratio:.2f}, within the {deviation_threshold:.0%} agreement threshold -- no "
                "rescale applied."
            ),
            dsm_height=dsm_height,
            dsm_is_metric=dsm_is_metric,
            scale_factor=None,
            median_ratio=median_ratio,
            n_buildings_used=len(ratios),
        )

    # Disagreement beyond the threshold: blend the current scale 50/50 toward the
    # shadow-implied scale (median_ratio), per research-notes.md's fusion rule.
    blended_factor = 0.5 + 0.5 * median_ratio
    rescaled = np.where(np.isfinite(dsm_height), dsm_height * blended_factor, dsm_height).astype(np.float32)

    return ShadowCrossCheckResult(
        status="applied",
        note=(
            f"Shadow cross-check on {len(ratios)} building(s) gives a median shadow/depth ratio of "
            f"{median_ratio:.2f}, exceeding the {deviation_threshold:.0%} agreement threshold. The "
            f"height field was rescaled by blending 50/50 toward the shadow-implied scale (factor "
            f"{blended_factor:.3f}). The DSM now reports a shadow-corrected empirical estimate, not a "
            "DEM-verified metric elevation."
        ),
        dsm_height=rescaled,
        dsm_is_metric=True,
        scale_factor=blended_factor,
        median_ratio=median_ratio,
        n_buildings_used=len(ratios),
    )
