"""Shared single-band float32 GeoTIFF writer.

Used for every raster the pipeline produces (depth maps, fused depth,
confidence, DSM/rDSM). CRS/transform are embedded whenever the source input
was georeferenced, per CLAUDE.md Section 6 ("never silently discard
georeferencing") -- this does not by itself imply the pixel values are
metric-calibrated; that is tracked separately in metadata.json.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.crs import CRS

from app.input.detect import GeoMetadata


def write_float32_geotiff(array: np.ndarray, out_path: Path, geo: Optional[GeoMetadata]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    kwargs = dict(
        driver="GTiff",
        height=array.shape[0],
        width=array.shape[1],
        count=1,
        dtype="float32",
        nodata=np.nan,
    )
    if geo is not None:
        kwargs["crs"] = CRS.from_string(geo.crs)
        kwargs["transform"] = rasterio.Affine(*geo.transform)

    with rasterio.open(out_path, "w", **kwargs) as dst:
        dst.write(array.astype(np.float32), 1)
