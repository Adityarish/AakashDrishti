from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class GeoMetadataOut(BaseModel):
    crs: str
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int
    bounds: tuple[float, float, float, float]
    resolution: tuple[float, float]
    nodata: Optional[float]
    band_count: int


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    width: int
    height: int
    band_count: int
    dtype: str
    is_georeferenced: bool
    geo: Optional[GeoMetadataOut] = None
    mode: str = "relative"
    file_format: str = "unknown"
    bit_depth: int = 8
    size_bytes: int = 0
    gsd_m: Optional[float] = None
    sun_azimuth_deg: Optional[float] = None
    sun_elevation_deg: Optional[float] = None
    bounds_wgs84: Optional[tuple[float, float, float, float]] = None
    notes: list[str] = []
    is_sample: bool = False
    sample_id: Optional[str] = None
