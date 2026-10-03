"""Tree crowns by classical image processing (no ML).

Canopy = textured foliage (evergreen: dark and green; deciduous in early spring: bare, brown-grey, high local variance)
that is not a roof, not paving and not plain shadow. Individual crowns come from a watershed on the distance transform
of the canopy mask (one crown per rounded blob); each crown's radius is its inscribed radius."""

from __future__ import annotations

import cv2
import numpy as np

PX = 0.1524


def canopy_mask(img: np.ndarray, roofs: np.ndarray, cars: np.ndarray | None = None) -> np.ndarray:
    f = img.astype(np.float32)
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = cv2.GaussianBlur(lab[..., 0], (0, 0), 0.7)
    m = cv2.blur(L, (7, 7))
    std = np.sqrt(np.maximum(cv2.blur(L * L, (7, 7)) - m * m, 0))
    green = f[..., 1] - 0.5 * (f[..., 0] + f[..., 2])
    soft = cv2.GaussianBlur(f, (0, 0), 2.0)
    soft_green = soft[..., 1] - 0.5 * (soft[..., 0] + soft[..., 2])

    evergreen = (hsv[..., 2] < 100) & (soft_green > 2.0) & (std > 6.5)
    bare = (std > 15.0) & (hsv[..., 2] > 45) & (hsv[..., 2] < 150) & (hsv[..., 1] < 150) & (soft_green < 9)
    canopy = evergreen | bare
    canopy = canopy.astype(np.uint8)
    canopy[roofs > 0] = 0
    if cars is not None:
        canopy[cars > 0] = 0
    canopy = cv2.morphologyEx(canopy, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    canopy = cv2.morphologyEx(canopy, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21)))
    return canopy


def split_crowns(canopy: np.ndarray, min_radius_px: int = 11) -> list[dict]:
    """One crown per distance-transform peak (watershed); returns centre and inscribed radius in pixels."""
    dist = cv2.distanceTransform(canopy, cv2.DIST_L2, 5)
    smooth = cv2.GaussianBlur(dist, (0, 0), 2.0)
    peaks = (smooth == cv2.dilate(smooth, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * min_radius_px + 1, 2 * min_radius_px + 1)))) & (smooth >= min_radius_px)
    ys, xs = np.nonzero(peaks)
    crowns = []
    taken = np.zeros(canopy.shape, np.uint8)
    for y, x in sorted(zip(ys, xs), key=lambda p: -smooth[p[0], p[1]]):
        r = float(smooth[y, x])
        if taken[y, x]:
            continue
        cv2.circle(taken, (int(x), int(y)), int(r * 0.8), 1, -1)
        crowns.append({"center": [float(x), float(y)], "radius_px": r})
    return crowns
