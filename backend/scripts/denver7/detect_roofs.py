"""Stage 1 for the hand-verified 7.tif scene: roof footprints by classical image processing (no ML models).

Works on the 0.5 m/px RGB array. Evidence used, all of it measurable in the picture itself:
  * roofs are SMOOTH (low local lightness/chroma variance) and bounded by edges,
  * they are ELEVATED, so they cast a shadow on their north/east side (the sun is south-west in this scene),
  * they are not green, not tiny, and roughly rectilinear.
Smooth components are classified with that evidence, facets of the same roof are merged (they differ in
lightness but share chroma), driveways are cut off with a morphological opening, and the outline is simplified
to a polygon. Output is a list of polygons in 0.5 m/px pixel coordinates plus the features that justified them.
"""

from __future__ import annotations

import numpy as np
import cv2

SHADOW_V = 72           # HSV value below which a pixel is "in shadow"
SMOOTH_STD = 3.6        # local lightness std (5x5) for "smooth"
SMOOTH_CSTD = 2.6       # local chroma std
MIN_SHORT_SIDE_PX = 9      # 4.5 m
MAX_ASPECT = 5.0
MIN_AREA_PX = 120        # 30 m2 at 0.5 m/px
MAX_AREA_PX = 180000    # 45,000 m2 (big-box roofs)
NE_MIN = 0.10           # share of the NE strip that is shadow
CHROMA_MERGE = 9.0      # |da|,|db| tolerance when merging facets of one roof


def _local_std(x: np.ndarray, k: int = 5) -> np.ndarray:
    m = cv2.blur(x, (k, k))
    return np.sqrt(np.maximum(cv2.blur(x * x, (k, k)) - m * m, 0))


def shadow_mask(img: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    sh = (hsv[..., 2] < SHADOW_V).astype(np.uint8)
    return cv2.morphologyEx(sh, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def smooth_mask(img: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(smooth, lab) where smooth marks interior pixels of roofs / pavement / some lawn."""
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    lab = cv2.cvtColor(img, cv2.COLOR_RGB2LAB).astype(np.float32)
    L = cv2.GaussianBlur(lab[..., 0], (0, 0), 0.8)
    a = cv2.GaussianBlur(lab[..., 1], (0, 0), 0.8)
    b = cv2.GaussianBlur(lab[..., 2], (0, 0), 0.8)
    std = _local_std(L)
    cstd = np.sqrt(_local_std(a) ** 2 + _local_std(b) ** 2)
    sm = ((std < SMOOTH_STD) & (cstd < SMOOTH_CSTD) & (hsv[..., 2] >= SHADOW_V)).astype(np.uint8)
    sm = cv2.morphologyEx(sm, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    sm = cv2.morphologyEx(sm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    return sm, lab


def _ne_evidence(filled: np.ndarray, shadow: np.ndarray, shifts) -> float:
    """Best share of the 'shifted-away' strip around a component that is shadow, over candidate sun directions."""
    h, w = filled.shape
    grown = cv2.dilate(filled, np.ones((5, 5), np.uint8))
    best = 0.0
    for dx, dy in shifts:
        strip = cv2.warpAffine(filled, np.float32([[1, 0, dx], [0, 1, dy]]), (w, h), flags=cv2.INTER_NEAREST)
        strip = (strip > 0) & (grown == 0)
        if strip.sum() > 20:
            best = max(best, float((shadow[strip] > 0).mean()))
    return best


SHIFTS = [(k, -k) for k in (4, 6, 8)] + [(0, -k) for k in (4, 6, 8)] + [(k, 0) for k in (4, 6, 8)] + [(k, -k // 2) for k in (4, 6, 8)] + [(k // 2, -k) for k in (4, 6, 8)]


def detect_roofs(img: np.ndarray, ne_min: float = NE_MIN, rect_min: float = 0.4, solid_min: float = 0.6) -> list[dict]:
    """Roof polygons in the pixel coordinates of `img` (a block of the 0.5 m/px mosaic)."""
    H, W = img.shape[:2]
    shadow = shadow_mask(img)
    smooth, lab = smooth_mask(img)
    f = img.astype(np.float32)
    green = f[..., 1] - 0.5 * (f[..., 0] + f[..., 2])
    n, lbl, stats, _ = cv2.connectedComponentsWithStats(smooth, connectivity=4)

    feats: dict[int, dict] = {}
    for i in range(1, n):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area < MIN_AREA_PX or area > MAX_AREA_PX:
            continue
        x, y, w0, h0 = (int(v) for v in stats[i, :4])
        pad = 14
        xa, ya, xb, yb = max(0, x - pad), max(0, y - pad), min(W, x + w0 + pad), min(H, y + h0 + pad)
        comp = (lbl[ya:yb, xa:xb] == i).astype(np.uint8)
        cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnt = max(cnts, key=cv2.contourArea)
        filled = np.zeros_like(comp)
        cv2.drawContours(filled, [cnt], -1, 1, -1)
        farea = int(filled.sum())
        (_, _), (rw, rh), _ = cv2.minAreaRect(cnt)
        sel = filled.astype(bool)
        feats[i] = {
            "box": (xa, ya, xb, yb), "filled": filled, "area": farea,
            "rect": farea / max(rw * rh, 1), "solid": farea / max(cv2.contourArea(cv2.convexHull(cnt)), 1),
            "aspect": max(rw, rh) / max(min(rw, rh), 1),
            "ne": _ne_evidence(filled, shadow[ya:yb, xa:xb], SHIFTS),
            "green": float(green[ya:yb, xa:xb][sel].mean()),
            "chroma": (float(lab[ya:yb, xa:xb, 1][sel].mean()), float(lab[ya:yb, xa:xb, 2][sel].mean())),
            "centroid": (x + w0 / 2, y + h0 / 2),
        }

    seeds = [i for i, v in feats.items()
             if v["ne"] >= ne_min and v["rect"] > rect_min and v["solid"] > solid_min and v["aspect"] < 7 and v["area"] >= 100 and v["green"] < 6]

    # merge facets: neighbouring smooth components sharing chroma with a seed belong to the same roof
    roof_mask = np.zeros((H, W), np.uint8)
    owner = np.zeros((H, W), np.int32)
    for i in seeds:
        roof_mask[lbl == i] = 1
        owner[lbl == i] = i
    grown_seed = cv2.dilate(roof_mask, np.ones((7, 7), np.uint8))
    adjacent = set(np.unique(lbl[(grown_seed > 0) & (roof_mask == 0)])) - {0}
    for j in adjacent:
        if j in seeds or j not in feats:
            continue
        v = feats[j]
        if v["green"] > 6 or v["area"] > 25000:
            continue
        comp = lbl == j
        touching = np.unique(owner[cv2.dilate(comp.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool) & (owner > 0)])
        for s in touching:
            dc = np.hypot(feats[s]["chroma"][0] - v["chroma"][0], feats[s]["chroma"][1] - v["chroma"][1])
            if dc < CHROMA_MERGE:
                roof_mask[comp] = 1
                owner[comp] = s
                break

    # close facet seams, fill holes, cut driveways (narrow strips) off with an opening, regrow 1 m
    roof_mask = cv2.morphologyEx(roof_mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    cnts, _ = cv2.findContours(roof_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(roof_mask)
    cv2.drawContours(filled, cnts, -1, 1, -1)
    opened = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11)))
    opened = cv2.dilate(opened, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))

    out = []
    cnts, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cnts:
        area = cv2.contourArea(c)
        if area < MIN_AREA_PX:
            continue
        eps = 1.4 if area < 4000 else 2.4
        poly = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
        if len(poly) < 3:
            continue
        (_, _), (rw, rh), _ = cv2.minAreaRect(c)
        # roads' lane arrows/markings and kerb strips are thin: a roof is at least ~4.5 m across and not a sliver
        if min(rw, rh) < MIN_SHORT_SIDE_PX or max(rw, rh) / max(min(rw, rh), 1) > MAX_ASPECT:
            continue
        mask = np.zeros((H, W), np.uint8)
        cv2.drawContours(mask, [c], -1, 1, -1)
        sel = mask.astype(bool)
        out.append({
            "polygon": poly.astype(float).tolist(), "area_px": float(area),
            "rect": float(area / max(rw * rh, 1)),
            "mean_rgb": [float(f[..., k][sel].mean()) for k in range(3)],
        })
    return out


def refine_with_grabcut(img: np.ndarray, polygon: np.ndarray, grow_px: int = 5, shrink_px: int = 4) -> np.ndarray | None:
    """Snap a rough roof polygon to the real roof edge with GrabCut.

    Sure foreground = the polygon eroded; sure background = everything beyond the polygon grown by `grow_px`
    plus shadow; the band in between is decided by the colour models. Returns the new outline or None."""
    H, W = img.shape[:2]
    poly = np.round(np.asarray(polygon, dtype=np.float64)).astype(np.int32)
    x0, y0 = max(0, int(poly[:, 0].min()) - 20), max(0, int(poly[:, 1].min()) - 20)
    x1, y1 = min(W, int(poly[:, 0].max()) + 21), min(H, int(poly[:, 1].max()) + 21)
    crop = np.ascontiguousarray(img[y0:y1, x0:x1])
    base = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(base, [poly - [x0, y0]], 1)
    fg = cv2.erode(base, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * shrink_px + 1, 2 * shrink_px + 1)))
    if fg.sum() < 12:
        fg = cv2.erode(base, np.ones((3, 3), np.uint8))
    near = cv2.dilate(base, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * grow_px + 1, 2 * grow_px + 1)))
    mask = np.full(crop.shape[:2], cv2.GC_BGD, np.uint8)
    mask[near > 0] = cv2.GC_PR_BGD
    mask[base > 0] = cv2.GC_PR_FGD
    mask[fg > 0] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
    try:
        cv2.grabCut(crop, mask, None, bgd, fgd, 4, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    result = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8)
    result = cv2.morphologyEx(result, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    result = cv2.morphologyEx(result, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    cnts, _ = cv2.findContours(result, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.5 * base.sum() or cv2.contourArea(c) > 2.0 * base.sum():
        return None
    approx = cv2.approxPolyDP(c, 1.3 if cv2.contourArea(c) < 4000 else 2.2, True).reshape(-1, 2) + [x0, y0]
    return approx.astype(float) if len(approx) >= 3 else None


def roof_evidence(img: np.ndarray, polygon: np.ndarray) -> dict:
    """Measured evidence that a polygon is a roof: shadow on the sun-away side, not green, smooth, not paving-coloured."""
    H, W = img.shape[:2]
    poly = np.round(np.asarray(polygon)).astype(np.int32)
    x0, y0 = np.maximum(poly.min(0) - 16, 0)
    x1, y1 = np.minimum(poly.max(0) + 17, [W, H])
    crop = np.ascontiguousarray(img[y0:y1, x0:x1])
    fill = np.zeros(crop.shape[:2], np.uint8)
    cv2.fillPoly(fill, [poly - [x0, y0]], 1)
    sh = shadow_mask(crop)
    ne = _ne_evidence(fill, sh, SHIFTS)
    sel = cv2.erode(fill, np.ones((5, 5), np.uint8)).astype(bool)
    if sel.sum() < 20:
        sel = fill.astype(bool)
    f = crop.astype(np.float32)
    green = float((f[..., 1] - 0.5 * (f[..., 0] + f[..., 2]))[sel].mean())
    lab = cv2.cvtColor(crop, cv2.COLOR_RGB2LAB).astype(np.float32)
    std = float(lab[..., 0][sel].std())
    area = float(fill.sum())
    (_, _), (rw, rh), _ = cv2.minAreaRect(poly.astype(np.float32))
    return {"ne": ne, "green": green, "std": std, "area": area, "rect": area / max(rw * rh, 1)}
