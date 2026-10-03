"""Shared constants and helpers for the hand-verified 7.tif scene (all coordinates documented here).

Mosaic pixel (col,row) at 0.5 ft/px  <->  scene metres (x east, z north, origin = south-west corner)  <->  map coordinates.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[3]
TIF = REPO / "test-data" / "7.tif"
# 7.tif is in EPSG:6428 (NAD83(2011) / Colorado Central, US SURVEY FEET): its 0.25 "unit" pixel is 0.25 ft = 0.0762 m,
# so the 10560 px image is 2640 ft = 804.7 m wide. The working mosaic halves it: 0.5 ft = 0.1524 m per pixel.
FT_M = 0.3048006096
HALF_PX_M = 0.5 * FT_M               # metres per pixel of the working mosaic (0.1524 m)
MOSAIC = 5280                        # pixels per side of the 0.5 m/px mosaic (2640 m)
WORLD_M = MOSAIC * HALF_PX_M        # 804.67 m


def px_to_scene(col: float, row: float) -> list[float]:
    """Mosaic pixel -> scene metres (x east, z north), origin at the south-west corner."""
    return [round(col * HALF_PX_M, 3), round((MOSAIC - row) * HALF_PX_M, 3)]


def polygon_area_m2(poly: np.ndarray) -> float:
    x, y = poly[:, 0], poly[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))) * HALF_PX_M ** 2
