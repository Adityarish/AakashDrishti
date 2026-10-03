"""Sun direction and per-object height from shadow length (no models).

Geometry (flat ground, vertical edge of height H, sun elevation e): shadow length on the ground = H / tan(e),
measured from the edge along the direction pointing AWAY from the sun.
Mosaic pixel directions: +col = east, +row = south, so "north" is -row.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import HALF_PX_M  # noqa: E402

SHADOW_V = 72


def shadow_mask(img: np.ndarray) -> np.ndarray:
    """Shadow = markedly darker than the lit ground around it (relative test, so it also works on dark lawns/asphalt)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    v = cv2.GaussianBlur(hsv[..., 2], (0, 0), 1.0).astype(np.float32)
    lit = cv2.blur(np.where(v > 70, v, np.nan_to_num(np.float32(0))), (101, 101)) / np.maximum(cv2.blur((v > 70).astype(np.float32), (101, 101)), 1e-3)
    sh = (v < 0.60 * lit) & (v < 115)
    sh = cv2.morphologyEx(sh.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    return sh


def shadow_direction(mosaic: np.ndarray, polys: list[np.ndarray], samples: int = 400, seed: int = 3) -> dict:
    """Azimuth (deg clockwise from north) the SHADOWS point toward, found by testing 72 directions.

    For each direction the score is the shadow fraction of a 4-12 px strip just outside the footprint on the side
    facing that direction, averaged over buildings. The true shadow direction maximises it."""
    rng = np.random.default_rng(seed)
    chosen = [polys[i] for i in rng.permutation(len(polys))[:samples]]
    scores = np.zeros(72)
    count = 0
    for poly in chosen:
        p = np.round(poly).astype(np.int32)
        x0, y0 = p.min(0) - 40
        x1, y1 = p.max(0) + 41
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(mosaic.shape[1], x1), min(mosaic.shape[0], y1)
        crop = np.ascontiguousarray(mosaic[y0:y1, x0:x1])
        sh = shadow_mask(crop)
        fill = np.zeros(crop.shape[:2], np.uint8)
        cv2.fillPoly(fill, [p - [x0, y0]], 1)
        outside = 1 - cv2.dilate(fill, np.ones((5, 5), np.uint8))
        for k in range(72):
            az = math.radians(k * 5)
            dx, dy = math.sin(az), -math.cos(az)
            strip = np.zeros_like(fill)
            for dist in (5, 8, 11):
                M = np.float32([[1, 0, dx * dist], [0, 1, dy * dist]])
                strip |= cv2.warpAffine(fill, M, (fill.shape[1], fill.shape[0]), flags=cv2.INTER_NEAREST)
            strip &= outside
            if strip.sum() > 30:
                scores[k] += float(sh[strip > 0].mean())
        count += 1
    scores /= max(count, 1)
    best = int(np.argmax(scores))
    # refine with a parabola through the peak
    a, b, c = scores[(best - 1) % 72], scores[best], scores[(best + 1) % 72]
    shift = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
    return {"shadow_azimuth_deg": (best + shift) * 5 % 360, "scores": scores.round(4).tolist(), "buildings_used": count}


def shadow_length_m(sh: np.ndarray, fill: np.ndarray, az_deg: float, max_px: int = 220) -> tuple[float, int]:
    """Median length (m) of shadow cast beyond the footprint edge, marching along the shadow direction."""
    az = math.radians(az_deg)
    dx, dy = math.sin(az), -math.cos(az)
    edge = fill - cv2.erode(fill, np.ones((3, 3), np.uint8))
    ys, xs = np.nonzero(edge)
    lengths = []
    H, W = fill.shape
    for y, x in zip(ys[::2], xs[::2]):
        # start only from boundary pixels whose next step leaves the footprint (the sun-away side)
        sx, sy = x + dx * 2.5, y + dy * 2.5
        ix, iy = int(round(sx)), int(round(sy))
        if not (0 <= ix < W and 0 <= iy < H) or fill[iy, ix]:
            continue
        run = 0
        gap = 0
        for step in range(2, max_px):
            px, py = int(round(x + dx * step)), int(round(y + dy * step))
            if not (0 <= px < W and 0 <= py < H):
                break
            if fill[py, px]:
                break
            if sh[py, px]:
                run = step
                gap = 0
            else:
                gap += 1
                if gap > 4:
                    break
        if run > 4:
            lengths.append(run)
    if len(lengths) < 5:
        return float("nan"), len(lengths)
    return float(np.median(lengths)) * HALF_PX_M, len(lengths)


def sun_elevation_from_cars(mosaic: np.ndarray, cars: list[dict], az_deg: float) -> dict:
    """Elevation from car shadows: a car is ~1.5 m tall, so e = atan(1.5 / shadow_length)."""
    vals = []
    for car in cars:
        p = np.round(np.array(car["polygon"])).astype(np.int32)
        x0, y0 = p.min(0) - 40
        x1, y1 = p.max(0) + 41
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(mosaic.shape[1], x1), min(mosaic.shape[0], y1)
        crop = np.ascontiguousarray(mosaic[y0:y1, x0:x1])
        sh = shadow_mask(crop)
        fill = np.zeros(crop.shape[:2], np.uint8)
        cv2.fillPoly(fill, [p - [x0, y0]], 1)
        length, n = shadow_length_m(sh, fill, az_deg, max_px=40)
        if n >= 8 and 0.4 < length < 4.0:
            vals.append(length)
    if len(vals) < 10:
        return {"elevation_deg": None, "cars_used": len(vals)}
    med = float(np.median(vals))
    return {"elevation_deg": math.degrees(math.atan2(1.5, med)), "median_shadow_m": med, "cars_used": len(vals)}
