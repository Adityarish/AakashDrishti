"""Stage 2: final building footprints = auto roofs kept after manual review + grown seeds + hand-traced polygons.

Inputs (all in data/):
  roofs_auto.json     candidate roofs from detect_roofs.py (index = position in file)
  manual_edits.json   {"remove": [indices], "add": [[col,row,radius_px], ...], "polys": [{label, kind, polygon}, ...]}
All coordinates are 0.5 ft/px mosaic pixels, read off the labelled review tiles.
Output: data/buildings_final.json  [{"id", "kind", "polygon", "source", "label"}]
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
from common import MOSAIC, polygon_area_m2  # noqa: E402
from detect_roofs import detect_roofs, refine_with_grabcut, roof_evidence  # noqa: E402


def grow_seed(mosaic: np.ndarray, col: float, row: float, radius: float) -> np.ndarray | None:
    """Grow a roof from a seed by colour: pixels within a loose lightness / tight chroma tolerance of the seed colour,
    not in shadow, inside 1.4 x radius, then opened to cut driveways and lawns off, keeping the part holding the seed.

    GrabCut was tried first and leaked into lawns and driveways of similar colour; this version is bounded and
    falls back to the seed's own colour region (never to a guess)."""
    H, W = mosaic.shape[:2]
    pad = int(radius * 1.6) + 16
    x0, y0 = max(0, int(col) - pad), max(0, int(row) - pad)
    x1, y1 = min(W, int(col) + pad), min(H, int(row) + pad)
    crop = np.ascontiguousarray(mosaic[y0:y1, x0:x1])
    cx, cy = col - x0, row - y0
    yy, xx = np.mgrid[0:crop.shape[0], 0:crop.shape[1]]
    d = np.hypot(xx - cx, yy - cy)
    soft = cv2.bilateralFilter(crop, 7, 20, 5)
    lab = cv2.cvtColor(soft, cv2.COLOR_RGB2LAB).astype(np.float32)
    hsv = cv2.cvtColor(soft, cv2.COLOR_RGB2HSV)
    core = d < max(4.0, radius * 0.35)
    ref = np.median(lab[core].reshape(-1, 3), axis=0)
    ok = (np.abs(lab[..., 0] - ref[0]) < 26) & (np.abs(lab[..., 1] - ref[1]) < 8) & (np.abs(lab[..., 2] - ref[2]) < 8) & (hsv[..., 2] > 70) & (d < radius * 1.4)
    m = ok.astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(m)
    cv2.drawContours(filled, cnts, -1, 1, -1)
    ksz = max(9, int(radius * 0.45) | 1)
    opened = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz)))
    opened = cv2.dilate(opened, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, lbl = cv2.connectedComponents(opened, connectivity=4)
    label = lbl[int(min(max(cy, 0), lbl.shape[0] - 1)), int(min(max(cx, 0), lbl.shape[1] - 1))]
    if label == 0:
        return None
    comp = (lbl == label).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    solid = area / max(cv2.contourArea(cv2.convexHull(c)), 1)
    if area < 0.3 * np.pi * radius ** 2 or area > 3.2 * np.pi * radius ** 2 or solid < 0.72:
        return None
    poly = cv2.approxPolyDP(c, 1.6, True).reshape(-1, 2) + [x0, y0]
    return poly.astype(float) if len(poly) >= 3 else None


def grabcut_seed(block: np.ndarray, col: float, row: float, radius: float) -> np.ndarray | None:
    """Last resort for complex roofs: GrabCut from the seed disc, clipped to 1.3 x radius, opened and kept if roof-coloured."""
    H, W = block.shape[:2]
    pad = int(radius * 1.8) + 14
    x0, y0 = max(0, int(col) - pad), max(0, int(row) - pad)
    x1, y1 = min(W, int(col) + pad), min(H, int(row) + pad)
    crop = np.ascontiguousarray(block[y0:y1, x0:x1])
    cx, cy = col - x0, row - y0
    yy, xx = np.mgrid[0:crop.shape[0], 0:crop.shape[1]]
    d = np.hypot(xx - cx, yy - cy)
    mask = np.full(crop.shape[:2], cv2.GC_BGD, np.uint8)
    mask[d < radius * 1.6] = cv2.GC_PR_BGD
    mask[d < radius * 1.0] = cv2.GC_PR_FGD
    mask[d < radius * 0.4] = cv2.GC_FGD
    bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
    try:
        cv2.grabCut(crop, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    except cv2.error:
        return None
    res = (((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)) & (d < radius * 1.3)).astype(np.uint8)
    ksz = max(9, int(radius * 0.4) | 1)
    res = cv2.morphologyEx(res, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (ksz, ksz)))
    res = cv2.morphologyEx(res, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7)))
    n, lbl = cv2.connectedComponents(res, connectivity=4)
    label = lbl[int(min(max(cy, 0), lbl.shape[0] - 1)), int(min(max(cx, 0), lbl.shape[1] - 1))]
    if label == 0:
        return None
    comp = (lbl == label).astype(np.uint8)
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    c = max(cnts, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.3 * np.pi * radius ** 2:
        return None
    poly = cv2.approxPolyDP(c, 1.6, True).reshape(-1, 2) + [x0, y0]
    return poly.astype(float) if len(poly) >= 3 else None


def regularize(poly: np.ndarray, kernel: int = 9, eps: float = 3.2) -> np.ndarray:
    """Make a blobby outline rectilinear: rotate to the roof's own axes, close/open with rectangles, then snap edges to H/V.

    Returns the original polygon if the result drifts by more than 15% in area (round or oblique roofs stay as they are)."""
    pts = np.asarray(poly, np.float32)
    x0, y0 = np.floor(pts.min(0)).astype(int) - 12
    x1, y1 = np.ceil(pts.max(0)).astype(int) + 13
    w, h = x1 - x0, y1 - y0
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [np.round(pts - [x0, y0]).astype(np.int32)], 1)
    (cx, cy), (rw, rh), ang = cv2.minAreaRect((pts - [x0, y0]).astype(np.float32))
    side = int(math.hypot(w, h)) + 8
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    M[0, 2] += side / 2 - w / 2
    M[1, 2] += side / 2 - h / 2
    rot = cv2.warpAffine(mask, M, (side, side), flags=cv2.INTER_NEAREST)
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel, kernel))
    rot = cv2.morphologyEx(rot, cv2.MORPH_CLOSE, k)
    rot = cv2.morphologyEx(rot, cv2.MORPH_OPEN, k)
    cnts, _ = cv2.findContours(rot, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return np.asarray(poly, float)
    c = max(cnts, key=cv2.contourArea)
    ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2).astype(np.float64)
    if len(ap) < 4:
        return np.asarray(poly, float)
    n = len(ap)
    horiz = []
    for i in range(n):
        d = ap[(i + 1) % n] - ap[i]
        horiz.append(abs(d[0]) >= abs(d[1]))
    # merge consecutive edges of the same orientation, then intersect alternating H/V edges
    edges = []
    for i in range(n):
        a, b = ap[i], ap[(i + 1) % n]
        if edges and edges[-1][0] == horiz[i]:
            edges[-1][1].extend([a, b])
        else:
            edges.append([horiz[i], [a, b]])
    if len(edges) > 1 and edges[0][0] == edges[-1][0]:
        edges[0][1] = edges[-1][1] + edges[0][1]
        edges.pop()
    if len(edges) < 4 or len(edges) % 2:
        return np.asarray(poly, float)
    lines = [(isH, float(np.mean([p[1] if isH else p[0] for p in pts_]))) for isH, pts_ in edges]
    verts = []
    for i in range(len(lines)):
        (h1, v1), (h2, v2) = lines[i - 1], lines[i]
        verts.append((v1, v2) if not h1 else (v2, v1))  # (x, y): vertical edge gives x, horizontal edge gives y
    verts = np.array(verts, np.float64)
    Minv = cv2.invertAffineTransform(M)
    back = (Minv @ np.vstack([verts.T, np.ones(len(verts))])).T + [x0, y0]
    a0 = abs(cv2.contourArea(np.asarray(poly, np.float32)))
    a1 = abs(cv2.contourArea(back.astype(np.float32)))
    if a0 == 0 or not (0.85 <= a1 / a0 <= 1.15):
        return np.asarray(poly, float)
    return back


def main(mosaic_npy: str) -> None:
    mosaic = np.load(mosaic_npy, mmap_mode="r")
    auto = json.loads((HERE / "data" / "roofs_auto.json").read_text(encoding="utf-8"))
    edits = json.loads((HERE / "data" / "manual_edits.json").read_text(encoding="utf-8"))
    removed = set(edits["remove"])

    out: list[dict] = []
    for i, roof in enumerate(auto):
        if i in removed:
            continue
        out.append({"polygon": roof["polygon"], "kind": "house", "source": "auto", "label": f"auto-{i}"})

    failed = []
    stats = {"grown": 0, "snapped": 0}

    def plausible(img, poly):
        ev = roof_evidence(img, poly)
        return ev["ne"] >= 0.07 and ev["green"] < 7 and ev["std"] < 22 and ev["rect"] > 0.45, ev

    for col, row, radius in edits["add"]:
        pad = int(radius * 2.0) + 70
        x0, y0 = max(0, col - pad), max(0, row - pad)
        block = np.ascontiguousarray(mosaic[y0:row + pad, x0:col + pad])
        lc, lr = col - x0, row - y0
        chosen = None
        local = grow_seed(block, lc, lr, radius)
        if local is not None and plausible(block, local)[0]:
            chosen = local
            stats["grown"] += 1
        if chosen is None:  # the seed may sit beside the roof: look for the nearest roof-like blob with relaxed thresholds
            best, best_d = None, 1e9
            for cand in detect_roofs(block, ne_min=0.05, rect_min=0.4, solid_min=0.6):
                poly = np.asarray(cand["polygon"])
                if cand["area_px"] < 0.35 * np.pi * radius ** 2 or cand["area_px"] > 3.5 * np.pi * radius ** 2:
                    continue
                dist = float(np.hypot(*(poly.mean(0) - [lc, lr])))
                if dist < min(1.4 * radius + 25, best_d) and plausible(block, poly)[0]:
                    best, best_d = poly, dist
            if best is not None:
                chosen = best
                stats["snapped"] += 1
        if chosen is None:
            gc = grabcut_seed(block, lc, lr, radius)
            if gc is not None:
                ev = roof_evidence(block, gc)
                if ev["std"] < 34 and ev["rect"] > 0.45:
                    chosen = gc
                    stats["grabcut"] = stats.get("grabcut", 0) + 1
                    stats["grabcut_ids"] = stats.get("grabcut_ids", []) + [f"seed-{col}-{row}"]
        if chosen is None:
            failed.append([col, row, radius])
            continue
        out.append({"polygon": (chosen + [x0, y0]).round(1).tolist(), "kind": "house", "source": "seed", "label": f"seed-{col}-{row}"})
    stats["failed"] = len(failed)
    print("seed resolution", {k: v for k, v in stats.items() if k != "grabcut_ids"})
    (HERE / "data" / "grabcut_ids.json").write_text(json.dumps(stats.get("grabcut_ids", [])), encoding="utf-8")

    reject = set(edits.get("reject", []))
    out = [o for o in out if o["label"] not in reject]
    for p in edits["polys"]:
        out.append({"polygon": p["polygon"], "kind": p["kind"], "source": "manual", "label": p["label"]})

    # de-duplicate: a seed/auto polygon that overlaps a hand-traced one by > 40% of its own area is dropped
    manual = [o for o in out if o["source"] == "manual"]
    keep: list[dict] = []
    for o in out:
        if o["source"] == "manual":
            keep.append(o)
            continue
        poly = np.round(np.array(o["polygon"])).astype(np.int32)
        x0, y0 = poly.min(0)
        x1, y1 = poly.max(0)
        mine = np.zeros((y1 - y0 + 3, x1 - x0 + 3), np.uint8)
        cv2.fillPoly(mine, [poly - [x0 - 1, y0 - 1]], 1)
        covered = 0
        for mo in manual:
            mp = np.round(np.array(mo["polygon"])).astype(np.int32)
            if mp[:, 0].max() < x0 or mp[:, 0].min() > x1 or mp[:, 1].max() < y0 or mp[:, 1].min() > y1:
                continue
            other = np.zeros_like(mine)
            cv2.fillPoly(other, [mp - [x0 - 1, y0 - 1]], 1)
            covered = max(covered, int((mine & other).sum()))
        if covered < 0.4 * mine.sum():
            keep.append(o)

    # drop near-duplicates between seeds and kept autos (same centroid within 12 px)
    final: list[dict] = []
    centres: list[tuple[float, float]] = []
    for o in sorted(keep, key=lambda o: {"manual": 0, "auto": 1, "seed": 2}[o["source"]]):
        c = np.array(o["polygon"]).mean(0)
        if o["source"] == "seed" and any(np.hypot(c[0] - a, c[1] - b) < 12 for a, b in centres):
            continue
        centres.append((float(c[0]), float(c[1])))
        final.append(o)

    for o in final:
        if o["kind"] in ("house", "flat", "shed", "canopy") and o["source"] != "manual":
            o["polygon"] = regularize(np.asarray(o["polygon"])).round(1).tolist()
    for i, o in enumerate(final, start=1):
        o["id"] = i
        o["area_m2"] = round(polygon_area_m2(np.array(o["polygon"])), 1)
    (HERE / "data" / "buildings_final.json").write_text(json.dumps(final), encoding="utf-8")
    by = {}
    for o in final:
        by[o["source"]] = by.get(o["source"], 0) + 1
    print("buildings", len(final), by, "failed seeds", len(failed), failed)
    (HERE / "data" / "failed_seeds.json").write_text(json.dumps(failed), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
