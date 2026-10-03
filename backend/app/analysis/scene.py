"""Loads the arrays a finished job persisted (arrays.npz) for the analysis endpoints."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform

from app.export.rasters import pixel_size_m
from app.input.detect import GeoMetadata


@dataclass
class Scene:
    job_id: str
    dsm: np.ndarray  # absolute metres, pseudo-metric nDSM, or relative units
    ndsm: np.ndarray  # height above ground (metres if metric else relative)
    terrain: np.ndarray  # bare-earth surface = dsm - ndsm
    labels: np.ndarray  # uint8 land-cover ids
    building_labels: np.ndarray  # int32, 0 = none
    slope: np.ndarray
    uncertainty_m: np.ndarray
    px_m: float
    is_metric: bool
    kind: str
    geo: Optional[GeoMetadata]
    unit: str

    @property
    def shape(self) -> tuple[int, int]:
        return self.dsm.shape

    def pixel_to_lonlat(self, col: float, row: float) -> Optional[tuple[float, float]]:
        if self.geo is None:
            return None
        x, y = rasterio.Affine(*self.geo.transform) * (col + 0.5, row + 0.5)
        if self.geo.crs.upper().endswith("4326"):
            return float(x), float(y)
        lon, lat = warp_transform(self.geo.crs, "EPSG:4326", [x], [y])
        return float(lon[0]), float(lat[0])

    def lonlat_to_pixel(self, lon: float, lat: float) -> Optional[tuple[float, float]]:
        if self.geo is None:
            return None
        if self.geo.crs.upper().endswith("4326"):
            x, y = lon, lat
        else:
            xs, ys = warp_transform("EPSG:4326", self.geo.crs, [lon], [lat])
            x, y = xs[0], ys[0]
        col, row = ~rasterio.Affine(*self.geo.transform) * (x, y)
        return float(col), float(row)


def _load(job_dir: str, mtime: float) -> Scene:
    root = Path(job_dir)
    data = np.load(root / "arrays.npz")
    meta = json.loads((root / "metadata.json").read_text(encoding="utf-8"))
    geo = None
    geo_meta = meta.get("geo")
    if geo_meta:
        geo = GeoMetadata(
            crs=geo_meta["crs"], transform=tuple(geo_meta["transform"]), width=geo_meta["width"],
            height=geo_meta["height"], bounds=tuple(geo_meta["bounds"]), resolution=tuple(geo_meta["resolution"]),
            nodata=None, band_count=3,
        )
    is_metric = bool(meta.get("dsm_is_metric", False))
    dsm = data["dsm"].astype(np.float32)
    ndsm = data["ndsm"].astype(np.float32)
    px_m = float(meta.get("pixel_size_m") or pixel_size_m(geo, meta.get("gsd_m")))
    return Scene(
        job_id=meta["job_id"], dsm=dsm, ndsm=ndsm, terrain=(dsm - ndsm).astype(np.float32),
        labels=data["labels"].astype(np.uint8), building_labels=data["building_labels"].astype(np.int32),
        slope=data["slope"].astype(np.float32), uncertainty_m=data["uncertainty"].astype(np.float32),
        px_m=px_m, is_metric=is_metric, kind=meta.get("dsm_kind", "relative"), geo=geo,
        unit="m" if is_metric else "relative units",
    )


@lru_cache(maxsize=4)
def _cached(job_dir: str, mtime: float) -> Scene:
    return _load(job_dir, mtime)


def load_scene(job_dir: Path) -> Scene:
    arrays = job_dir / "arrays.npz"
    if not arrays.is_file():
        raise FileNotFoundError("This job has no analysis arrays yet (still running, failed, or created before this version).")
    return _cached(str(job_dir), arrays.stat().st_mtime)


def overlay_rgba(mask: np.ndarray, rgb: tuple[int, int, int], alpha: float | np.ndarray) -> np.ndarray:
    out = np.zeros(mask.shape + (4,), dtype=np.uint8)
    out[..., 0], out[..., 1], out[..., 2] = rgb
    if isinstance(alpha, np.ndarray):
        out[..., 3] = np.where(mask, np.clip(alpha, 0, 1) * 255, 0).astype(np.uint8)
    else:
        out[..., 3] = np.where(mask, int(alpha * 255), 0).astype(np.uint8)
    return out


def png_base64(rgba: np.ndarray, max_side: int = 1024) -> str:
    import base64

    import cv2

    h, w = rgba.shape[:2]
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        rgba = cv2.resize(rgba, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_NEAREST)
    ok, buffer = cv2.imencode(".png", cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return "data:image/png;base64," + base64.b64encode(buffer.tobytes()).decode("ascii")
