"""DEM tile management (FR-12): find or fetch SRTM-derived 1-arcsec tiles covering the scene
footprint, mosaic them, and reproject onto the image grid as the bare-earth terrain (DTM).

Tiles are cached under SRTM_DATA_DIR so an installation can be pre-seeded for offline use.
Downloads use the public AWS terrain-tile mirror of SRTM (no key); they are skipped when
DEM_AUTO_DOWNLOAD=false or when the machine is offline.
"""

from __future__ import annotations

import gzip
import math
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import rasterio
from rasterio.merge import merge
from rasterio.warp import Resampling, reproject, transform_bounds
from scipy import ndimage

from app.core.logging import get_logger
from app.input.detect import GeoMetadata

logger = get_logger(__name__)

_DEM_EXTENSIONS = {".tif", ".tiff", ".hgt"}
SKADI_URL = "https://s3.amazonaws.com/elevation-tiles-prod/skadi/{ns}{lat:02d}/{ns}{lat:02d}{ew}{lon:03d}.hgt.gz"


@dataclass
class DemResult:
    status: str  # "ok" | "unavailable"
    note: str
    dem_on_grid: Optional[np.ndarray] = None  # HxW float32, NaN where missing
    sources: Optional[list[str]] = None


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def _bounds_wgs84(geo: GeoMetadata) -> tuple[float, float, float, float]:
    return transform_bounds(geo.crs, "EPSG:4326", *geo.bounds)


def _local_dem_paths(dem_dir: Path, geo: GeoMetadata) -> list[Path]:
    if not dem_dir.exists():
        return []
    west, south, east, north = _bounds_wgs84(geo)
    found: list[Path] = []
    for path in dem_dir.rglob("*"):
        if path.suffix.lower() not in _DEM_EXTENSIONS:
            continue
        try:
            with rasterio.open(path) as dem:
                if dem.crs is None:
                    continue
                d_west, d_south, d_east, d_north = transform_bounds(dem.crs, "EPSG:4326", *dem.bounds)
        except rasterio.errors.RasterioIOError:
            continue
        if max(west, d_west) < min(east, d_east) and max(south, d_south) < min(north, d_north):
            found.append(path)
    return found


def _download_tile(lat: int, lon: int, dem_dir: Path) -> Optional[Path]:
    import httpx

    name = _tile_name(lat, lon)
    target = dem_dir / f"{name}.hgt"
    if target.exists():
        return target
    url = SKADI_URL.format(ns="N" if lat >= 0 else "S", lat=abs(lat), ew="E" if lon >= 0 else "W", lon=abs(lon))
    dem_dir.mkdir(parents=True, exist_ok=True)
    partial = dem_dir / f"{name}.hgt.gz.part"
    try:
        with httpx.stream("GET", url, timeout=60.0, follow_redirects=True) as response:
            if response.status_code != 200:
                logger.warning("DEM tile %s unavailable (HTTP %s)", name, response.status_code)
                return None
            with partial.open("wb") as handle:
                for chunk in response.iter_bytes():
                    handle.write(chunk)
        with gzip.open(partial, "rb") as gz, target.open("wb") as out:
            shutil.copyfileobj(gz, out)
        return target
    except Exception as exc:  # noqa: BLE001 - offline or blocked: caller degrades gracefully
        logger.warning("DEM tile download failed for %s: %s", name, exc)
        target.unlink(missing_ok=True)
        return None
    finally:
        partial.unlink(missing_ok=True)


def fetch_dem_paths(
    geo: GeoMetadata, dem_dir: Path, allow_download: bool, log: Optional[Callable[[str], None]] = None
) -> tuple[list[Path], str]:
    paths = _local_dem_paths(dem_dir, geo)
    if paths:
        return paths, "local DEM tiles"
    if not allow_download:
        return [], "no local DEM covers the footprint and auto-download is disabled"

    west, south, east, north = _bounds_wgs84(geo)
    downloaded: list[Path] = []
    for lat in range(math.floor(south), math.floor(north - 1e-9) + 1):
        for lon in range(math.floor(west), math.floor(east - 1e-9) + 1):
            if log:
                log(f"Fetching SRTM tile {_tile_name(lat, lon)}")
            tile = _download_tile(lat, lon, dem_dir)
            if tile is not None:
                downloaded.append(tile)
    if downloaded:
        return downloaded, "downloaded SRTM 1-arcsec tiles"
    return [], "no DEM tile could be found or downloaded (offline?)"


def reproject_paths_to_grid(paths: list[Path], geo: GeoMetadata, shape: tuple[int, int]) -> np.ndarray:
    """Mosaic one or more DEM files and reproject them (bilinear) onto the scene grid."""
    out = np.full(shape, np.nan, dtype=np.float32)
    if len(paths) == 1:
        datasets = [rasterio.open(paths[0])]
        try:
            reproject(
                source=rasterio.band(datasets[0], 1),
                destination=out,
                src_transform=datasets[0].transform,
                src_crs=datasets[0].crs,
                src_nodata=datasets[0].nodata,
                dst_transform=rasterio.Affine(*geo.transform),
                dst_crs=geo.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
        finally:
            datasets[0].close()
    else:
        datasets = [rasterio.open(path) for path in paths]
        try:
            mosaic, transform = merge(datasets, nodata=datasets[0].nodata)
            reproject(
                source=mosaic[0].astype(np.float32),
                destination=out,
                src_transform=transform,
                src_crs=datasets[0].crs,
                src_nodata=datasets[0].nodata,
                dst_transform=rasterio.Affine(*geo.transform),
                dst_crs=geo.crs,
                dst_nodata=np.nan,
                resampling=Resampling.bilinear,
            )
        finally:
            for dataset in datasets:
                dataset.close()
    out[out < -500] = np.nan
    return out


def smooth_dtm(dem: np.ndarray, sigma_px: float) -> np.ndarray:
    """Light smoothing removes the 30 m grid's stair-stepping without inventing detail."""
    if not np.isfinite(dem).any() or sigma_px <= 0.3:
        return dem
    filled = np.where(np.isfinite(dem), dem, np.nanmedian(dem))
    smoothed = ndimage.gaussian_filter(filled, sigma=sigma_px, mode="nearest")
    return np.where(np.isfinite(dem), smoothed, np.nan).astype(np.float32)


def build_dtm(
    geo: GeoMetadata,
    shape: tuple[int, int],
    dem_dir: Path,
    allow_download: bool,
    log: Optional[Callable[[str], None]] = None,
) -> DemResult:
    try:
        paths, origin = fetch_dem_paths(geo, dem_dir, allow_download, log)
    except Exception as exc:  # noqa: BLE001
        return DemResult("unavailable", f"DEM lookup failed: {exc}")
    if not paths:
        return DemResult("unavailable", f"No reference DEM: {origin}.")
    try:
        grid = reproject_paths_to_grid(paths, geo, shape)
    except Exception as exc:  # noqa: BLE001
        return DemResult("unavailable", f"DEM reprojection failed: {exc}")
    valid = np.isfinite(grid)
    if valid.sum() < 100:
        return DemResult("unavailable", "The DEM overlaps the scene but has too few valid pixels there.")
    gsd = float(np.mean(geo.resolution))
    pixel_ratio = 30.0 / max(gsd if not geo.crs.upper().endswith("4326") else gsd * 111_320.0, 1e-3)
    dtm = smooth_dtm(grid, sigma_px=min(pixel_ratio * 0.5, 40.0))
    names = [p.name for p in paths]
    return DemResult("ok", f"Terrain from {origin}: {', '.join(names)}", dem_on_grid=dtm, sources=names)
