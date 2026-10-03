"""Raster exports and derived layers: COG GeoTIFFs, slope/aspect/hillshade, 16-bit rDSM PNG with
world file, colour-mapped previews and the 16-bit height PNG the browser tools read."""

from __future__ import annotations

import json
import math
import shutil
import tempfile
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.shutil import copy as rio_copy

from app.input.detect import GeoMetadata

NODATA = -9999.0

# Antarctica Light colormaps (hex stops, evenly spaced)
HEIGHT_STOPS = ["#0B2545", "#1F5F8B", "#5B9BC8", "#A9CDE6", "#FFFFFF", "#F7D9B5"]
ERROR_STOPS = ["#1F5F8B", "#FAFCFE", "#E4574B"]
UNCERTAINTY_STOPS = ["#FAFCFE", "#F26B21"]
SLOPE_STOPS = ["#F2C94C", "#E4574B"]
SLOPE_HAZARD_THRESHOLD_DEG = 30.0


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)


def apply_colormap(values01: np.ndarray, stops: list[str]) -> np.ndarray:
    """Map [0,1] values (NaN -> lowest colour) to HxWx3 uint8 through a 1024-entry lookup table.

    np.interp on the full raster builds float64 intermediates (several GiB at 12k x 14k px); the LUT keeps the
    working set at one uint16 index plus the uint8 output."""
    palette = np.array([_hex_to_rgb(s) for s in stops], dtype=np.float32)
    positions = np.linspace(0.0, 1.0, len(stops))
    grid = np.linspace(0.0, 1.0, 1024)
    lut = np.stack([np.interp(grid, positions, palette[:, c]) for c in range(3)], axis=-1).astype(np.uint8)
    index = np.clip(np.nan_to_num(values01, nan=0.0), 0.0, 1.0)
    index = np.rint(index * 1023.0).astype(np.uint16)
    return lut[index]


def normalise(arr: np.ndarray, low_pct: float = 2.0, high_pct: float = 98.0) -> np.ndarray:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros_like(arr, dtype=np.float32)
    lo, hi = np.percentile(finite, [low_pct, high_pct])
    if hi <= lo:
        lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo:
        return np.zeros_like(arr, dtype=np.float32)
    return np.clip((arr - lo) / (hi - lo), 0.0, 1.0).astype(np.float32)


def write_cog(array: np.ndarray, out_path: Path, geo: Optional[GeoMetadata]) -> None:
    """Float32 Cloud-Optimized GeoTIFF: DEFLATE + predictor 3, nodata -9999, overviews."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = np.where(np.isfinite(array), array, NODATA).astype(np.float32)
    profile = dict(driver="GTiff", height=data.shape[0], width=data.shape[1], count=1, dtype="float32",
                   nodata=NODATA, tiled=True, blockxsize=256, blockysize=256)  # staged uncompressed; the COG copy compresses once
    if geo is not None:
        profile["crs"] = CRS.from_string(geo.crs)
        profile["transform"] = rasterio.Affine(*geo.transform)
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "staged.tif"
        with rasterio.open(staged, "w", **profile) as dst:
            dst.write(data, 1)
        try:
            rio_copy(staged, out_path, driver="COG", COMPRESS="DEFLATE", PREDICTOR="3", OVERVIEW_RESAMPLING="AVERAGE",
                     BLOCKSIZE=256, NUM_THREADS="ALL_CPUS")
        except Exception:  # noqa: BLE001 - COG driver missing: fall back to a tiled GTiff with overviews
            shutil.copyfile(staged, out_path)
            with rasterio.open(out_path, "r+") as dst:
                factors = [f for f in (2, 4, 8, 16) if min(dst.width, dst.height) // f >= 64]
                if factors:
                    dst.build_overviews(factors, rasterio.enums.Resampling.average)


def pixel_size_m(geo: Optional[GeoMetadata], gsd_m: Optional[float]) -> float:
    if gsd_m is not None:
        return float(gsd_m)
    if geo is not None:
        res_x, res_y = geo.resolution
        if geo.crs.upper().endswith("4326"):
            lat = (geo.bounds[1] + geo.bounds[3]) / 2.0
            return float((res_x * 111_320.0 * math.cos(math.radians(lat)) + res_y * 110_574.0) / 2.0)
        return float((res_x + res_y) / 2.0)
    return 1.0


def slope_aspect(dsm: np.ndarray, px_m: float) -> tuple[np.ndarray, np.ndarray]:
    """Slope in degrees and aspect in degrees clockwise from north (downslope direction)."""
    filled = np.where(np.isfinite(dsm), dsm, np.nanmedian(dsm) if np.isfinite(dsm).any() else 0.0).astype(np.float32)
    dz_dy, dz_dx = np.gradient(filled, px_m)
    slope = np.degrees(np.arctan(np.hypot(dz_dx, dz_dy)))
    aspect = (np.degrees(np.arctan2(dz_dy, -dz_dx)) + 360.0) % 360.0
    slope = np.where(np.isfinite(dsm), slope, np.nan).astype(np.float32)
    aspect = np.where(np.isfinite(dsm), aspect, np.nan).astype(np.float32)
    return slope, aspect


def hillshade(dsm: np.ndarray, px_m: float, azimuth_deg: float = 315.0, altitude_deg: float = 45.0) -> np.ndarray:
    filled = np.where(np.isfinite(dsm), dsm, np.nanmedian(dsm) if np.isfinite(dsm).any() else 0.0).astype(np.float32)
    dz_dy, dz_dx = np.gradient(filled, px_m)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(dz_dy, -dz_dx)
    azimuth = math.radians(360.0 - azimuth_deg + 90.0)
    zenith = math.radians(90.0 - altitude_deg)
    shaded = math.cos(zenith) * np.cos(slope) + math.sin(zenith) * np.sin(slope) * np.cos(azimuth - aspect)
    return (np.clip(shaded, 0.0, 1.0) * 255).astype(np.uint8)


def save_png(image: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if image.ndim == 3 and image.shape[2] == 3:
        cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
    elif image.ndim == 3 and image.shape[2] == 4:
        cv2.imwrite(str(path), cv2.cvtColor(image, cv2.COLOR_RGBA2BGRA))
    else:
        cv2.imwrite(str(path), image)


def save_rdsm_png16(rel_height: np.ndarray, path: Path, geo: Optional[GeoMetadata]) -> None:
    """16-bit rDSM normalised on the 2nd-98th percentile, with an ESRI world file when geo is known."""
    scaled = (normalise(rel_height) * 65535).astype(np.uint16)
    save_png(scaled, path)
    if geo is not None:
        a, b, c, d, e, f = geo.transform
        world = [a, d, b, e, c + a / 2.0 + b / 2.0, f + d / 2.0 + e / 2.0]
        path.with_suffix(".pgw").write_text("\n".join(f"{v:.10f}" for v in world) + "\n", encoding="utf-8")


def save_height_png16(height: np.ndarray, path: Path, meta_path: Path) -> dict:
    """Store heights as 16-bit (1..65535, 0 = nodata) plus min/max so the browser can decode."""
    finite = height[np.isfinite(height)]
    lo = float(finite.min()) if finite.size else 0.0
    hi = float(finite.max()) if finite.size else 1.0
    span = max(hi - lo, 1e-9)
    encoded = np.where(np.isfinite(height), 1 + (height - lo) / span * 65534, 0).astype(np.uint16)
    save_png(encoded, path)
    meta = {"min": lo, "max": hi, "width": int(height.shape[1]), "height": int(height.shape[0]), "float32": "height.f32"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    return meta


def height_color_image(height: np.ndarray, is_absolute_range: bool = True) -> np.ndarray:
    return apply_colormap(normalise(height, 1.0, 99.0), HEIGHT_STOPS)


def uncertainty_color_image(unc01: np.ndarray) -> np.ndarray:
    return apply_colormap(unc01, UNCERTAINTY_STOPS)


def slope_color_image(slope_deg: np.ndarray, hazard_deg: float = SLOPE_HAZARD_THRESHOLD_DEG) -> np.ndarray:
    return apply_colormap(np.clip(slope_deg / max(hazard_deg * 1.5, 1e-6), 0.0, 1.0), SLOPE_STOPS)


def world_extent(geo: Optional[GeoMetadata], width: int, height: int, px_m: float) -> dict:
    return {"width_m": width * px_m, "height_m": height * px_m,
            "bounds": list(geo.bounds) if geo else None, "crs": geo.crs if geo else None}
