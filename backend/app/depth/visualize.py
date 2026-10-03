"""Depth map -> colorized PNG preview, for UI display and quick inspection."""

from __future__ import annotations

from pathlib import Path

import matplotlib
import numpy as np
from PIL import Image


def save_depth_preview(depth: np.ndarray, out_path: Path, cmap_name: str = "Spectral_r") -> None:
    """Colourise through a 256-entry uint8 lookup table.

    Calling the colormap on the whole array allocates an H x W x 4 *float64* RGBA array (5.45 GiB for a
    12688 x 14403 scene) and failed with MemoryError; the LUT path stays at one byte per pixel per channel."""
    finite = depth[np.isfinite(depth)]
    index = np.zeros(depth.shape, dtype=np.uint8)
    if finite.size:
        lo, hi = float(finite.min()), float(finite.max())
        if hi > lo:
            scaled = (depth - np.float32(lo)) / np.float32(hi - lo)
            np.nan_to_num(scaled, copy=False, nan=0.0)
            np.clip(scaled, 0.0, 1.0, out=scaled)
            index = np.rint(scaled * 255.0).astype(np.uint8)
            del scaled
    cmap = matplotlib.colormaps.get_cmap(cmap_name)
    lut = (cmap(np.linspace(0.0, 1.0, 256))[:, :3] * 255).astype(np.uint8)
    Image.fromarray(lut[index]).save(out_path)
