"""Bundled sample scenes: real GAMUS test tiles (RGB + reference height + land cover).

The tiles carry no geotransform, so the georeferenced variant is placed at an *illustrative*
UTM location (documented in the GeoTIFF tags). A sun elevation is fitted from the tile's own
reference heights and shadows (also tagged as fitted) so the shadow cross-check can be demoed.
"""

from __future__ import annotations

import math
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import rasterio
from PIL import Image
from rasterio.crs import CRS

from app.buildings.segment import segment_buildings_agl
from app.buildings.shadow import analyze_shadows
from app.core.config import Settings

SAMPLE_GSD_M = 0.5
FEATURED = ["DC_38_25", "DC_03_26", "NYC_01106", "NYC_04584", "NYC_05854", "DC_18_36"]
CITY_NAMES = {"DC": "Washington DC", "NYC": "New York City"}
LANDSCAPE_TEXT = {
    "urban": "Dense urban blocks", "forested": "Wooded residential", "sparse": "Open ground",
    "mixed": "Mixed suburban", "water": "Waterfront",
}


@dataclass
class Sample:
    sample_id: str
    city: str
    landscape: str
    title: str
    rgb_path: Path
    agl_path: Path
    cls_path: Path
    featured: bool


def _dir(settings: Settings) -> Path:
    return settings.samples_dir_path / "gamus"


def _landscape(cls: np.ndarray) -> str:
    building, tree, water = float((cls == 3).mean()), float((cls == 6).mean()), float((cls == 4).mean())
    if water > 0.4:
        return "water"
    if building > 0.2:
        return "urban"
    if tree > 0.4:
        return "forested"
    if building < 0.05:
        return "sparse"
    return "mixed"


def list_samples(settings: Settings) -> list[Sample]:
    root = _dir(settings)
    out: list[Sample] = []
    if not root.is_dir():
        return out
    for rgb in sorted(root.glob("*_rgb.png")):
        stem = rgb.name[:-8]
        agl, cls = root / f"{stem}_agl.npy", root / f"{stem}_cls.png"
        if not agl.is_file() or not cls.is_file():
            continue
        city = stem.split("_")[0]
        landscape = _landscape(np.array(Image.open(cls)))
        title = f"{CITY_NAMES.get(city, city)} - {LANDSCAPE_TEXT[landscape]}"
        out.append(Sample(stem, city, landscape, title, rgb, agl, cls, stem in FEATURED))
    out.sort(key=lambda s: (FEATURED.index(s.sample_id) if s.sample_id in FEATURED else 99, s.sample_id))
    return out


def get_sample(settings: Settings, sample_id: str) -> Optional[Sample]:
    return next((s for s in list_samples(settings) if s.sample_id == sample_id), None)


def _placement(sample_id: str) -> tuple[float, float]:
    """Illustrative UTM 18N origin (upper-left) from the tile index."""
    parts = sample_id.split("_")
    tile = 1024 * SAMPLE_GSD_M
    if parts[0] == "DC" and len(parts) == 3:
        row, col = int(parts[1]), int(parts[2])
        return 316_000.0 + col * tile, 4_313_000.0 - row * tile
    number = int(parts[-1]) if parts[-1].isdigit() else 0
    return 585_000.0 + (number % 40) * tile, 4_520_000.0 - (number // 40) * tile


def fit_sun_elevation(rgb: np.ndarray, agl: np.ndarray) -> Optional[float]:
    seg = segment_buildings_agl(rgb, agl)
    if len(seg.footprints) < 5:
        return None
    analysis = analyze_shadows(rgb, seg.footprints, seg.labels, None, 45.0, SAMPLE_GSD_M)
    ratios: list[float] = []
    for estimate in analysis.estimates:
        if estimate.shadow_length_px and estimate.shadow_length_px > 3:
            height = float(np.percentile(agl[seg.labels == estimate.building_id], 90))
            if height > 3:
                ratios.append(height / (estimate.shadow_length_px * SAMPLE_GSD_M))
    if len(ratios) < 5:
        return None
    return float(np.clip(math.degrees(math.atan(float(np.median(ratios)))), 10.0, 80.0))


def write_sample_input(sample: Sample, dest_dir: Path, variant: str) -> Path:
    rgb = np.array(Image.open(sample.rgb_path).convert("RGB"))
    if variant == "png":
        dest = dest_dir / "source.png"
        shutil.copyfile(sample.rgb_path, dest)
        return dest
    agl = np.load(sample.agl_path).astype(np.float32)
    sun_elevation = fit_sun_elevation(rgb, agl)
    x0, y0 = _placement(sample.sample_id)
    transform = rasterio.Affine(SAMPLE_GSD_M, 0, x0, 0, -SAMPLE_GSD_M, y0)
    dest = dest_dir / "source.tif"
    with rasterio.open(dest, "w", driver="GTiff", height=rgb.shape[0], width=rgb.shape[1], count=3, dtype="uint8",
                       crs=CRS.from_epsg(32618), transform=transform, compress="deflate") as out:
        out.write(np.transpose(rgb, (2, 0, 1)))
        tags = {"SAMPLE": f"GAMUS test tile {sample.sample_id}", "PLACEMENT": "illustrative UTM 18N position (tile has no geotransform)"}
        if sun_elevation is not None:
            tags["SUN_ELEVATION"] = f"{sun_elevation:.2f}"
            tags["SUN_ELEVATION_SOURCE"] = "fitted to the tile's reference heights and shadows (demo scene)"
        out.update_tags(**tags)
    return dest


def attach_reference(sample: Sample, dest_dir: Path) -> None:
    shutil.copyfile(sample.agl_path, dest_dir / "sample_reference.npy")


def thumbnail_jpeg(sample: Sample, size: int = 480) -> bytes:
    image = cv2.imread(str(sample.rgb_path))
    scale = size / max(image.shape[:2])
    image = cv2.resize(image, (int(image.shape[1] * scale), int(image.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 86])
    return buffer.tobytes()
