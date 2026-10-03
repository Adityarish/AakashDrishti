"""FR-11: validation of the estimated DSM against a reference DEM/LiDAR raster.

Reuses `app.calibration.srtm._find_overlapping_dem` (DEM discovery under
SRTM_DATA_DIR) and `app.calibration.srtm.reproject_dem_to_grid` (CRS +
resolution alignment onto the job's own grid) rather than duplicating that
logic -- see CLAUDE.md Section 7 for the exact validation steps required
(CRS alignment, spatial alignment, resolution matching, NoData masking,
unit verification) and Section 9 ("reuse working code").

Follows the same honesty pattern as `calibrate_with_srtm`: if no reference
data is available, or the DSM was never metric-calibrated (so units would
not be comparable to the reference DEM), this returns status="unavailable"
with an explanatory note -- never a fabricated RMSE/MAE/correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from app.calibration.srtm import _find_overlapping_dem, reproject_dem_to_grid
from app.core.logging import get_logger
from app.input.detect import GeoMetadata

logger = get_logger(__name__)

_MIN_VALID_PIXELS = 100


@dataclass
class ValidationMetrics:
    status: str  # "calibrated" | "unavailable"
    note: str
    rmse: Optional[float] = None
    mae: Optional[float] = None
    correlation: Optional[float] = None
    valid_pixel_count: Optional[int] = None
    reference_source: Optional[str] = None


def compute_validation_metrics(
    dsm_height: np.ndarray,
    geo: Optional[GeoMetadata],
    srtm_dir: Path,
    dsm_is_metric: bool,
) -> ValidationMetrics:
    if geo is None:
        return ValidationMetrics(
            status="unavailable",
            note="Input is not georeferenced; there is no CRS-aligned reference DEM to validate against.",
        )

    if not dsm_is_metric:
        return ValidationMetrics(
            status="unavailable",
            note=(
                "DSM was not metric-calibrated (no matching reference DEM was found/used during calibration), "
                "so its values are in arbitrary relative units and cannot be validated in meters against a "
                "reference DEM."
            ),
        )

    dem_path = _find_overlapping_dem(srtm_dir, geo)
    if dem_path is None:
        return ValidationMetrics(
            status="unavailable",
            note=(
                f"No reference DEM/LiDAR raster covering this image's footprint was found under {srtm_dir}. "
                "Place a reference GeoTIFF/HGT tile there to enable validation."
            ),
        )

    try:
        reference = reproject_dem_to_grid(dem_path, geo, dsm_height.shape)
    except Exception as exc:  # noqa: BLE001 -- reprojection failure is a real, reportable validation failure
        logger.exception("Validation DEM reprojection failed for %s", dem_path)
        return ValidationMetrics(
            status="unavailable",
            note=f"Found reference DEM {dem_path.name} but reprojection failed: {exc}",
        )

    valid = np.isfinite(dsm_height) & np.isfinite(reference)
    valid_count = int(valid.sum())
    if valid_count < _MIN_VALID_PIXELS:
        return ValidationMetrics(
            status="unavailable",
            note=(
                f"Reference DEM {dem_path.name} overlaps the footprint but yields too few valid pixels "
                f"({valid_count}) after reprojection/NoData masking."
            ),
        )

    estimated = dsm_height[valid].astype(np.float64)
    reference_valid = reference[valid].astype(np.float64)
    diff = estimated - reference_valid

    rmse = float(np.sqrt(np.mean(diff**2)))
    mae = float(np.mean(np.abs(diff)))

    correlation: Optional[float] = None
    if np.std(estimated) > 1e-9 and np.std(reference_valid) > 1e-9:
        correlation = float(np.corrcoef(estimated, reference_valid)[0, 1])

    return ValidationMetrics(
        status="calibrated",
        note=f"Validated against {dem_path.name} using {valid_count} overlapping valid pixels.",
        rmse=rmse,
        mae=mae,
        correlation=correlation,
        valid_pixel_count=valid_count,
        reference_source=dem_path.name,
    )
