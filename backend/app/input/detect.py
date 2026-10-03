"""Input ingestion: format sniffing, georeferencing detection, metadata extraction.

FR-01: PNG/JPG/TIFF/BigTIFF/GeoTIFF validated by magic bytes.
FR-02: CRS, geotransform, bounds, bit depth, band count and GSD detected; mode is
       "absolute" when georeferenced, otherwise "relative".
FR-03: GSD / CRS / sun azimuth / sun elevation can be overridden by the user.
FR-04: 2-98 percentile stretch and RGB band selection for multi-band input.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.enums import ColorInterp
from rasterio.errors import RasterioIOError
from rasterio.warp import transform_bounds

STRETCH_PERCENTILES = (2.0, 98.0)


class UnsupportedInputError(ValueError):
    """Raised when the input file cannot be read as an image or GeoTIFF."""


@dataclass
class GeoMetadata:
    crs: str
    transform: tuple[float, float, float, float, float, float]
    width: int
    height: int
    bounds: tuple[float, float, float, float]  # left, bottom, right, top
    resolution: tuple[float, float]  # pixel size x, y
    nodata: Optional[float]
    band_count: int


@dataclass
class InputDescriptor:
    """Result of inspecting an uploaded image."""

    path: Path
    is_georeferenced: bool
    width: int
    height: int
    band_count: int
    dtype: str
    geo: Optional[GeoMetadata]
    file_format: str = "unknown"
    bit_depth: int = 8
    size_bytes: int = 0
    gsd_m: Optional[float] = None
    sun_azimuth_deg: Optional[float] = None
    sun_elevation_deg: Optional[float] = None
    bounds_wgs84: Optional[tuple[float, float, float, float]] = None
    notes: list[str] = field(default_factory=list)


def sniff_format(path: Path) -> str:
    """Identify the container from magic bytes (never from the extension)."""
    with path.open("rb") as handle:
        head = handle.read(16)
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "tiff"
    if head[:4] in (b"II+\x00", b"MM\x00+"):
        return "bigtiff"
    return "unknown"


def _meters_per_pixel(crs: CRS, resolution: tuple[float, float], bounds: tuple[float, float, float, float]) -> float:
    res_x, res_y = resolution
    if crs.is_geographic:
        mean_lat = (bounds[1] + bounds[3]) / 2.0
        dx = res_x * 111_320.0 * math.cos(math.radians(mean_lat))
        dy = res_y * 110_574.0
        return float((dx + dy) / 2.0)
    unit_factor = crs.linear_units_factor[1] if crs.linear_units_factor else 1.0
    return float((res_x + res_y) / 2.0 * unit_factor)


def get_sun_from_metadata(path: Path) -> tuple[Optional[float], Optional[float]]:
    """Return (azimuth_deg, elevation_deg) from raster tags when present, else (None, None)."""
    azimuth: Optional[float] = None
    elevation: Optional[float] = None
    try:
        with rasterio.open(path) as dataset:
            sources = [dataset.tags(), dataset.tags(ns="IMAGE_STRUCTURE") or {}]
            for tags in sources:
                for key, value in tags.items():
                    upper = key.upper()
                    if "SUN" not in upper:
                        continue
                    try:
                        number = float(value)
                    except (TypeError, ValueError):
                        continue
                    if "ELEV" in upper and elevation is None:
                        elevation = number
                    elif "AZIM" in upper and azimuth is None:
                        azimuth = number
    except Exception:  # noqa: BLE001 - metadata probing is best-effort
        pass
    if elevation is None:
        # No universal GeoTIFF/EXIF tag for solar elevation; opportunistically check Pillow
        # EXIF tags too (rarely present, but plain JPEG/TIFF carry no rasterio-readable tags).
        try:
            from PIL import ExifTags, Image

            with Image.open(path) as img:
                exif = img.getexif()
                if exif:
                    tag_map = {ExifTags.TAGS.get(k, k): v for k, v in exif.items()}
                    for key in ("SunElevation", "GPSAltitude"):
                        if key in tag_map:
                            try:
                                elevation = float(tag_map[key])
                                break
                            except (TypeError, ValueError):
                                continue
        except Exception:  # noqa: BLE001 - metadata probing is best-effort
            pass
    return azimuth, elevation


def detect_input(path: Path) -> InputDescriptor:
    if not path.exists():
        raise UnsupportedInputError(f"File does not exist: {path}")

    file_format = sniff_format(path)
    if file_format == "unknown":
        raise UnsupportedInputError(
            "File content is not a PNG, JPEG, TIFF or BigTIFF image (magic-byte check failed)."
        )

    try:
        with rasterio.open(path) as dataset:
            width, height = dataset.width, dataset.height
            band_count = dataset.count
            dtype = dataset.dtypes[0] if dataset.dtypes else "uint8"
            has_crs = dataset.crs is not None
            is_georeferenced = has_crs and not dataset.transform.is_identity

            geo: Optional[GeoMetadata] = None
            gsd_m: Optional[float] = None
            bounds_wgs84 = None
            if is_georeferenced:
                bounds = dataset.bounds
                geo = GeoMetadata(
                    crs=dataset.crs.to_string(),
                    transform=tuple(dataset.transform)[:6],
                    width=width,
                    height=height,
                    bounds=(bounds.left, bounds.bottom, bounds.right, bounds.top),
                    resolution=(abs(dataset.transform.a), abs(dataset.transform.e)),
                    nodata=dataset.nodata,
                    band_count=band_count,
                )
                gsd_m = _meters_per_pixel(dataset.crs, geo.resolution, geo.bounds)
                try:
                    bounds_wgs84 = tuple(transform_bounds(dataset.crs, "EPSG:4326", *geo.bounds))
                except Exception:  # noqa: BLE001
                    bounds_wgs84 = None
    except RasterioIOError as exc:
        raise UnsupportedInputError(f"Could not read file as an image or GeoTIFF: {path}") from exc

    sun_az, sun_el = get_sun_from_metadata(path)
    bit_depth = int(np.dtype(dtype).itemsize * 8) if str(dtype).startswith(("uint", "int")) else 32
    notes: list[str] = []
    if file_format in ("png", "jpeg") and not is_georeferenced:
        notes.append("Plain image: no spatial metadata, output will be a relative DSM.")

    return InputDescriptor(
        path=path,
        is_georeferenced=is_georeferenced,
        width=width,
        height=height,
        band_count=band_count,
        dtype=str(dtype),
        geo=geo,
        file_format="geotiff" if (is_georeferenced and file_format in ("tiff", "bigtiff")) else file_format,
        bit_depth=bit_depth,
        size_bytes=path.stat().st_size,
        gsd_m=gsd_m,
        sun_azimuth_deg=sun_az,
        sun_elevation_deg=sun_el,
        bounds_wgs84=bounds_wgs84,
        notes=notes,
    )


def apply_overrides(
    descriptor: InputDescriptor,
    gsd_m: Optional[float] = None,
    crs: Optional[str] = None,
    origin_x: Optional[float] = None,
    origin_y: Optional[float] = None,
    sun_azimuth_deg: Optional[float] = None,
    sun_elevation_deg: Optional[float] = None,
) -> InputDescriptor:
    """Apply user overrides (FR-03). A supplied CRS + GSD + origin turns a plain image into
    a georeferenced one; a GSD alone only sets the metric pixel size."""
    if sun_azimuth_deg is not None:
        descriptor.sun_azimuth_deg = sun_azimuth_deg
    if sun_elevation_deg is not None:
        descriptor.sun_elevation_deg = sun_elevation_deg
    if gsd_m is not None:
        descriptor.gsd_m = gsd_m
        descriptor.notes.append(f"GSD overridden to {gsd_m:g} m/px by the user.")

    if crs and descriptor.gsd_m and origin_x is not None and origin_y is not None:
        target_crs = CRS.from_user_input(crs)
        res = descriptor.gsd_m
        if target_crs.is_geographic:
            res = descriptor.gsd_m / 111_320.0
        left, top = origin_x, origin_y
        right, bottom = left + res * descriptor.width, top - res * descriptor.height
        descriptor.geo = GeoMetadata(
            crs=target_crs.to_string(),
            transform=(res, 0.0, left, 0.0, -res, top),
            width=descriptor.width,
            height=descriptor.height,
            bounds=(left, bottom, right, top),
            resolution=(res, res),
            nodata=None,
            band_count=descriptor.band_count,
        )
        descriptor.is_georeferenced = True
        try:
            descriptor.bounds_wgs84 = tuple(transform_bounds(target_crs, "EPSG:4326", left, bottom, right, top))
        except Exception:  # noqa: BLE001
            descriptor.bounds_wgs84 = None
        descriptor.notes.append(f"Georeferenced from user-supplied CRS {crs}, GSD and origin.")
    elif crs and descriptor.geo is not None and descriptor.geo.crs != crs:
        descriptor.notes.append("CRS override ignored: the file already carries its own CRS.")
    return descriptor


def _select_rgb_bands(dataset: rasterio.io.DatasetReader) -> list[int]:
    count = dataset.count
    if count <= 3:
        return list(range(1, count + 1))
    interp = list(dataset.colorinterp)
    wanted = [ColorInterp.red, ColorInterp.green, ColorInterp.blue]
    if all(item in interp for item in wanted):
        return [interp.index(item) + 1 for item in wanted]
    descriptions = [(text or "").lower() for text in dataset.descriptions]
    named = {"red": None, "green": None, "blue": None}
    for index, text in enumerate(descriptions, start=1):
        for color in named:
            if color in text and named[color] is None:
                named[color] = index
    if all(named.values()):
        return [named["red"], named["green"], named["blue"]]  # type: ignore[list-item]
    return [1, 2, 3]


def read_rgb_array(path: Path) -> np.ndarray:
    """HxWx3 uint8 RGB array: RGB band selection for multi-band rasters, replication of
    single-band rasters, and a 2-98 percentile stretch for anything that is not 8-bit."""
    with rasterio.open(path) as dataset:
        bands = _select_rgb_bands(dataset)
        arr = dataset.read(bands)

    arr = np.transpose(arr, (1, 2, 0))
    if arr.shape[-1] == 1:
        arr = np.repeat(arr, 3, axis=-1)
    elif arr.shape[-1] == 2:
        arr = np.concatenate([arr, arr[..., :1]], axis=-1)

    if arr.dtype != np.uint8:
        arr = _to_uint8(arr)
    return arr


def _to_uint8(arr: np.ndarray) -> np.ndarray:
    lo_pct, hi_pct = STRETCH_PERCENTILES
    out = np.empty(arr.shape, dtype=np.uint8)
    for band in range(arr.shape[-1]):
        channel = arr[..., band].astype(np.float64)
        finite = channel[np.isfinite(channel)]
        if finite.size == 0:
            out[..., band] = 0
            continue
        lo, hi = np.percentile(finite, [lo_pct, hi_pct])
        if hi <= lo:
            lo, hi = finite.min(), finite.max()
        if hi <= lo:
            out[..., band] = 0
            continue
        out[..., band] = (np.clip((channel - lo) / (hi - lo), 0, 1) * 255).astype(np.uint8)
    return out
