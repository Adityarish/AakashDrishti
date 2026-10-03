"""Convert fused depth into a DSM/rDSM height raster and write it as GeoTIFF.

FR-7/FR-11 / PRD.md Section 11:
  - non-georeferenced input -> relative rDSM, no absolute-unit claim.
  - georeferenced input -> DSM with CRS/transform preserved; pixel values are
    only in real metric elevation units if `calibrated=True` was passed in
    (see app/calibration/srtm.py) -- otherwise they remain relative, and the
    GeoTIFF is written purely to preserve spatial framing, not accuracy.

Convention: for a near-nadir capture, a pixel closer to the camera (smaller
depth) corresponds to higher relative elevation, so
`height = max(depth) - depth`. This is a deterministic, documented transform
of the real fused depth field -- not a fabricated value.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np

from app.geospatial.raster_io import write_float32_geotiff
from app.input.detect import GeoMetadata


def depth_to_relative_height(fused_depth: np.ndarray) -> np.ndarray:
    finite_mask = np.isfinite(fused_depth)
    if not finite_mask.any():
        return np.zeros_like(fused_depth, dtype=np.float32)
    dmax = float(fused_depth[finite_mask].max())
    height = np.where(finite_mask, dmax - fused_depth, np.nan)
    return height.astype(np.float32)


def write_height_geotiff(height: np.ndarray, out_path: Path, geo: Optional[GeoMetadata]) -> None:
    """Write the DSM/rDSM raster. CRS/transform are embedded when `geo` is
    available, regardless of whether the values are calibrated to metric
    elevation -- see module docstring."""
    write_float32_geotiff(height, out_path, geo)
