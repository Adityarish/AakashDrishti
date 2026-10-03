"""Calibrate relative height to absolute elevation using a local SRTM/DEM tile.

PRD.md Section 10 / CLAUDE.md Section 6: only claim metric accuracy when a
real reference DEM overlapping the input's footprint is actually found and
used. If SRTM_DATA_DIR (see app/core/config.py) contains no tile covering
the image, this returns status="unavailable" with an explanatory note --
never a fabricated scale/offset.

This module is implemented and exercised by unit-style logic, but has not
been validated against real SRTM data in this environment (no reference
tiles are bundled with the repo -- see IMPLEMENTATION.md "known
limitations"). Drop a GeoTIFF DEM covering the input's footprint into
SRTM_DATA_DIR to exercise the real calibration path.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject, transform_bounds

from app.core.logging import get_logger
from app.input.detect import GeoMetadata

logger = get_logger(__name__)

_DEM_EXTENSIONS = {".tif", ".tiff", ".hgt"}


@dataclass
class CalibrationResult:
    status: str  # "calibrated" | "unavailable"
    note: str
    calibrated_height: Optional[np.ndarray] = None
    scale: Optional[float] = None
    offset: Optional[float] = None
    reference_source: Optional[str] = None


def _find_overlapping_dem(srtm_dir: Path, geo: GeoMetadata) -> Optional[Path]:
    if not srtm_dir.exists():
        return None

    target_bounds_wgs84 = transform_bounds(geo.crs, "EPSG:4326", *geo.bounds)

    for path in srtm_dir.rglob("*"):
        if path.suffix.lower() not in _DEM_EXTENSIONS:
            continue
        try:
            with rasterio.open(path) as dem:
                if dem.crs is None:
                    continue
                dem_bounds_wgs84 = transform_bounds(dem.crs, "EPSG:4326", *dem.bounds)
        except rasterio.errors.RasterioIOError:
            continue

        left = max(target_bounds_wgs84[0], dem_bounds_wgs84[0])
        bottom = max(target_bounds_wgs84[1], dem_bounds_wgs84[1])
        right = min(target_bounds_wgs84[2], dem_bounds_wgs84[2])
        top = min(target_bounds_wgs84[3], dem_bounds_wgs84[3])
        if left < right and bottom < top:
            return path

    return None


def reproject_dem_to_grid(dem_path: Path, geo: GeoMetadata, shape: tuple[int, int]) -> np.ndarray:
    """Reproject a DEM/reference raster onto the target grid (`geo`'s CRS/
    transform, `shape` rows x cols). Shared by `calibrate_with_srtm` and
    `app/validation/metrics.py` so both use the exact same resampling
    behaviour when comparing against a reference DEM. Raises on any
    GDAL/reprojection failure -- callers are expected to catch and report
    "unavailable" rather than silently continuing with an unreprojected DEM.
    """
    with rasterio.open(dem_path) as dem:
        reference = np.full(shape, np.nan, dtype=np.float32)
        reproject(
            source=rasterio.band(dem, 1),
            destination=reference,
            src_transform=dem.transform,
            src_crs=dem.crs,
            src_nodata=dem.nodata,
            dst_transform=rasterio.Affine(*geo.transform),
            dst_crs=geo.crs,
            dst_nodata=np.nan,
            resampling=Resampling.bilinear,
        )
    return reference


def calibrate_with_srtm(
    relative_height: np.ndarray,
    geo: GeoMetadata,
    srtm_dir: Path,
) -> CalibrationResult:
    dem_path = _find_overlapping_dem(srtm_dir, geo)
    if dem_path is None:
        return CalibrationResult(
            status="unavailable",
            note=(
                f"No reference DEM covering this image's footprint was found under {srtm_dir}. "
                "Place an SRTM 30m (or equivalent) GeoTIFF/HGT tile there to enable calibration."
            ),
        )

    try:
        reference = reproject_dem_to_grid(dem_path, geo, relative_height.shape)
    except Exception as exc:  # noqa: BLE001 -- any GDAL/reprojection failure is a real, reportable calibration failure
        logger.exception("SRTM reprojection failed for %s", dem_path)
        return CalibrationResult(
            status="unavailable",
            note=f"Found reference DEM {dem_path.name} but reprojection failed: {exc}",
        )

    valid = np.isfinite(relative_height) & np.isfinite(reference)
    if valid.sum() < 100:
        return CalibrationResult(
            status="unavailable",
            note=f"Reference DEM {dem_path.name} overlaps the footprint but yields too few valid pixels ({int(valid.sum())}) after reprojection/masking.",
        )

    x = relative_height[valid].astype(np.float64)
    y = reference[valid].astype(np.float64)
    design = np.vstack([x, np.ones_like(x)]).T
    (scale, offset), *_ = np.linalg.lstsq(design, y, rcond=None)

    if not np.isfinite(scale) or not np.isfinite(offset):
        return CalibrationResult(
            status="unavailable",
            note=f"Regression against {dem_path.name} did not converge to a finite scale/offset.",
        )

    calibrated = (scale * relative_height + offset).astype(np.float32)
    calibrated = np.where(np.isfinite(relative_height), calibrated, np.nan).astype(np.float32)

    return CalibrationResult(
        status="calibrated",
        note=f"Calibrated against {dem_path.name} using {int(valid.sum())} overlapping valid pixels.",
        calibrated_height=calibrated,
        scale=float(scale),
        offset=float(offset),
        reference_source=dem_path.name,
    )
