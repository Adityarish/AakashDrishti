"""Vehicles by classical image processing (no ML): oriented-rectangle matched filtering on pavement.

A car is a ~4.6 x 1.9 m patch whose colour differs from the asphalt around it. For every orientation (every 10 degrees)
the "difference from local pavement colour" map is correlated with a rectangle kernel (inner mean minus surrounding-ring
mean). Local maxima above a threshold, inside paved areas and outside roofs, are cars; overlapping ones are suppressed.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

PX = 0.1524
CAR_LEN_M, CAR_WID_M = 4.6, 1.9
ANGLES = list(range(0, 180, 10))
MIN_INNER = 24.0         # mean colour distance from asphalt inside the rectangle
MIN_CONTRAST = 11.0      # inner minus ring


def pavement_mask(img: np.ndarray, roof_mask: np.ndarray | None = None) -> np.ndarray:
    """Asphalt / concrete: grey-or-warm, mid brightness, not green, not under a roof."""
    soft = cv2.GaussianBlur(img, (0, 0), 2.5)   # asphalt is speckled; judge colour on a smoothed copy
    hsv = cv2.cvtColor(soft, cv2.COLOR_RGB2HSV)
    f = soft.astype(np.float32)
    green = f[..., 1] - 0.5 * (f[..., 0] + f[..., 2])
    base = (hsv[..., 1] < 90) & (green < 7) & (hsv[..., 2] > 70) & (hsv[..., 2] < 215)
    if roof_mask is not None:
        base &= ~(cv2.dilate(roof_mask, np.ones((3, 3), np.uint8)).astype(bool))
    base = base.astype(np.uint8)
    base = cv2.morphologyEx(base, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(base, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] > 6000
    return keep[lbl].astype(np.uint8)


def colour_distance_map(img: np.ndarray, pave: np.ndarray) -> np.ndarray:
    """Colour distance from the LOCAL ASPHALT colour (mean of pavement pixels in a 61 px window), so a car on a
    narrow road is compared with the road, not with the lawns beside it."""
    lab = cv2.cvtColor(cv2.GaussianBlur(img, (0, 0), 1.0), cv2.COLOR_RGB2LAB).astype(np.float32)
    w = pave.astype(np.float32)
    den = np.maximum(cv2.blur(w, (61, 61)), 1e-3)
    bg = np.stack([cv2.blur(lab[..., c] * w, (61, 61)) / den for c in range(3)], -1)
    d = np.sqrt(((lab - bg) ** 2).sum(-1))
    return np.minimum(d, 70.0)


def _rect_kernel(angle_deg: float, length_px: float, width_px: float, ring_px: float) -> tuple[np.ndarray, np.ndarray]:
    size = (int(math.ceil(length_px + 2 * ring_px)) | 1) + 4
    inner = np.zeros((size, size), np.uint8)
    outer = np.zeros((size, size), np.uint8)
    c = (size / 2.0, size / 2.0)
    for arr, extra in ((inner, 0.0), (outer, ring_px)):
        box = cv2.boxPoints((c, (length_px + 2 * extra, width_px + 2 * extra), angle_deg))
        cv2.fillPoly(arr, [np.round(box).astype(np.int32)], 1)
    ring = outer.astype(np.float32) - inner.astype(np.float32)
    inner = inner.astype(np.float32)
    return inner / inner.sum(), ring / max(ring.sum(), 1)


def detect_cars(img: np.ndarray, roof_mask: np.ndarray | None = None) -> list[dict]:
    H, W = img.shape[:2]
    pave = pavement_mask(img, roof_mask)
    near_pave = cv2.morphologyEx(pave, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (31, 31)))
    # Parking areas are wide paved expanses; streets are narrow ribbons where curbs and gutters mimic cars. Only the
    # wide expanses (inscribed radius >= 10 m) are searched, so every detection is a confident one.
    depth = cv2.distanceTransform(near_pave, cv2.DIST_L2, 5)
    wide = (depth >= 10.0 / PX).astype(np.uint8)
    zone = cv2.dilate(wide, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (101, 101))).astype(bool) & near_pave.astype(bool)
    if roof_mask is not None:
        zone &= ~(cv2.erode(roof_mask, np.ones((7, 7), np.uint8)).astype(bool))
    if not zone.any():
        return []
    dist = colour_distance_map(img, pave)

    length_px, width_px = CAR_LEN_M / PX, CAR_WID_M / PX
    best = np.full((H, W), -1e9, np.float32)
    best_angle = np.zeros((H, W), np.float32)
    best_inner = np.zeros((H, W), np.float32)
    for angle in ANGLES:
        k_in, k_ring = _rect_kernel(angle, length_px, width_px, 6.0)
        inner = cv2.filter2D(dist, -1, k_in, borderType=cv2.BORDER_REFLECT)
        ring = cv2.filter2D(dist, -1, k_ring, borderType=cv2.BORDER_REFLECT)
        score = inner - ring
        better = score > best
        best[better] = score[better]
        best_angle[better] = angle
        best_inner[better] = inner[better]

    # exclusion: the 1.8 m beside walls (shadow strips and roof edges mimic cars) and non-paved ground
    if roof_mask is not None:
        zone &= ~(cv2.dilate(roof_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (25, 25))).astype(bool))
    binary = (dist > 18).astype(np.float32)
    cand = (best > MIN_CONTRAST) & (best_inner > MIN_INNER) & zone
    # local maxima only
    peak = best == cv2.dilate(best, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15)))
    cand &= peak
    ys, xs = np.nonzero(cand)
    order = np.argsort(-best[ys, xs])
    taken = np.zeros((H, W), np.uint8)
    out = []
    for idx in order:
        y, x = int(ys[idx]), int(xs[idx])
        angle = float(best_angle[y, x])
        box = cv2.boxPoints(((x, y), (length_px, width_px), angle))
        poly = np.round(box).astype(np.int32)
        x0, y0 = np.maximum(poly.min(0) - 8, 0)
        x1, y1 = np.minimum(poly.max(0) + 9, [W, H])
        local = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(local, [poly - [x0, y0]], 1)
        if (taken[y0:y1, x0:x1] & local).sum() > 0.25 * local.sum():
            continue
        grown = cv2.dilate(local, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (13, 13)))
        ring = grown - local
        fb = binary[y0:y1, x0:x1]
        inner_fill = float(fb[local > 0].mean())
        ring_fill = float(fb[ring > 0].mean()) if ring.sum() else 0.0
        ring_pave = float(near_pave[y0:y1, x0:x1][ring > 0].mean()) if ring.sum() else 0.0
        if inner_fill < 0.55 or ring_fill > 0.55 * inner_fill + 0.1 or ring_pave < 0.7:
            continue
        taken[y0:y1, x0:x1] |= local
        out.append({"polygon": box.round(1).tolist(), "center": [float(x), float(y)], "angle": angle, "length_m": CAR_LEN_M,
                    "width_m": CAR_WID_M, "score": float(best[y, x]), "inner": float(best_inner[y, x]), "fill": inner_fill})
    for car in out:
        poly = np.round(np.array(car["polygon"])).astype(np.int32)
        x0, y0 = np.maximum(poly.min(0), 0)
        x1, y1 = np.minimum(poly.max(0) + 1, [W, H])
        m = np.zeros((y1 - y0, x1 - x0), np.uint8)
        cv2.fillPoly(m, [poly - [x0, y0]], 1)
        pix = img[y0:y1, x0:x1][m.astype(bool)]
        car["rgb"] = [float(v) for v in np.median(pix, axis=0)] if len(pix) else [128.0, 128.0, 128.0]
    return out
