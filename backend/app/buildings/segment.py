"""Heuristic building-footprint extraction from RGB + height/depth data.

This is deliberately classical computer vision (`cv2` contour/morphology
operations), NOT a trained instance-segmentation network -- CLAUDE.md
Section 5's 8GB VRAM budget is already spent on DA V2 + Depth Pro, and
loading a third model (e.g. Mask R-CNN/SAM) resident alongside them is
exactly what that rule forbids. Treat every footprint here as a heuristic
candidate, not a certified detection -- there is no accuracy number backing
these polygons because no labelled dataset was used to produce them.

Method:
  1. "Elevated" mask: pixels whose height is meaningfully above a local
     neighborhood baseline (approximated with a large-window mean via
     `scipy.ndimage.uniform_filter`, which stands in for "local ground
     level" -- a real ground-classification step would need a bare-earth
     DTM, which we don't have).
  2. Morphological close/open to merge fragmented roof pixels and drop
     speckle noise.
  3. External contours on the cleaned mask, filtered by:
       - minimum pixel area (drops noise-scale blobs), and
       - fill ratio = contour_area / min_area_rect_area (buildings tend to
         be rectilinear -> high fill ratio; trees/vegetation canopies are
         irregular -> low fill ratio). This is a cheap, explainable
         discriminator, not a learned classifier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import cv2
import numpy as np
from scipy import ndimage

DEFAULT_LOCAL_WINDOW_PX = 51
DEFAULT_MIN_AREA_PX = 150
# Was 0.75 -- verified massively under-detecting on a real dense residential
# scene (DC_03_28_RGB.png, 1024x1024): of 49 border-filtered, correctly-sized
# candidates whose "elevated" blobs visually matched real rooftops in the
# DSM preview (cross-checked by eye against the source photo), the median
# fill_ratio was only 0.61 and fully half fell between 0.40-0.60 -- common
# for L-shaped/multi-wing house footprints, which are NOT close to their own
# rotated bounding-box area even though they're real rectilinear buildings.
# 0.75 kept only 9 of those 49 (an ~82% false-negative rate on real
# buildings). Lowered to 0.45, which keeps 45 of the same 49 -- still well
# above typical tree/vegetation-canopy fill ratios (irregular, star-shaped
# outlines score far lower), just no longer rejecting ordinary complex-shaped
# houses. See context/decisions-log.md for the full diagnostic.
DEFAULT_MIN_FILL_RATIO = 0.45
DEFAULT_APPROX_EPSILON_FRAC = 0.015
# Monocular depth models (DA V2, Depth Pro) have a well-known degraded/less-reliable
# prediction band right at the image border (receptive-field edge effects, no context
# beyond the frame). A footprint whose contour touches that border cannot be
# distinguished, by local statistics alone, from a real elevated structure -- and if it
# IS real, the footprint is cut off/incomplete anyway. Reject both cases rather than
# report an untrustworthy height. Verified against a real photo (Dubai skyline test
# image), iteratively: an initial fixed 2px margin only removed 4 of 18 candidates,
# leaving several ~17-19px from the edge that were still clearly border artifacts (an
# evenly-spaced vertical run of small blobs hugging the left edge) -- the border band is
# resolution-relative, not a fixed pixel count, so `segment_buildings` computes it as 1%
# of the shorter image side by default when `border_margin_px` isn't given explicitly.
# See context/decisions-log.md for the full before/after data.


@dataclass
class BuildingSegmentation:
    mask: np.ndarray  # HxW bool: union of all accepted footprints
    labels: np.ndarray  # HxW int32: 0 = background, 1..N = footprint id
    footprints: list[list[tuple[float, float]]] = field(default_factory=list)
    """Polygon vertices in pixel (x, y) coordinates, index i -> label id i+1."""
    method_note: str = (
        "Heuristic classical-CV segmentation (elevation-above-local-baseline + "
        "morphology + contour rectilinearity filter). Not a trained instance "
        "segmentation model; no accuracy guarantee."
    )


DEFAULT_BASELINE_PERCENTILE = 20.0


def _local_baseline(
    height_map: np.ndarray, window_px: int, percentile: float = DEFAULT_BASELINE_PERCENTILE
) -> np.ndarray:
    """Approximate local "ground level" as a low percentile (default: 20th)
    of each window's valid values, via `scipy.ndimage.percentile_filter`.

    A low percentile, rather than the window mean, is used deliberately: the
    mean is pulled in BOTH directions by nearby outliers (a building raises
    it, a depression lowers it), which would spuriously flag ordinary flat
    ground next to a local low point as "elevated relative to baseline". A
    low percentile stays anchored near the true surrounding ground level
    even when a depression or building sits partway inside the window,
    since only a minority of window pixels need to be at/near ground level
    for it to dominate the low percentile. This is a real geomorphometric
    technique (local minimum/percentile filter for bare-earth
    approximation), not a fabricated shortcut -- but it remains an
    approximation, not a trained ground-classification model.

    Invalid (NoData) pixels are pushed to +inf before filtering so they
    never influence a low percentile unless a window is almost entirely
    invalid, in which case the output baseline is NaN there.

    Known limitation: if a large-scale depression/pit (e.g. a genuine
    terrain basin, not a building) occupies a large fraction of a single
    window, it can pull the low percentile down enough that ordinary flat
    ground at the depression's rim looks "elevated" relative to that
    artificially-lowered baseline, producing a false-positive footprint
    candidate there. This is a real, documented shortcoming of a
    single-window heuristic (there is no bare-earth ground-truth to check
    against) -- `min_fill_ratio` in `segment_buildings` filters out most
    such irregularly-shaped artifacts, but does not guarantee zero false
    positives. `local_window_px` should stay small relative to expected
    building size (not scene-wide terrain features) to limit this.
    """
    valid = np.isfinite(height_map)
    filled = np.where(valid, height_map, np.inf).astype(np.float32)
    factor = max(1, int(np.ceil(max(filled.shape) / 1024)))
    if factor > 1:
        # percentile_filter is O(window^2) per pixel; run it on a decimated copy for big scenes.
        small = np.where(np.isfinite(filled), filled, np.nan)
        small = cv2.resize(np.nan_to_num(small, nan=np.nanmax(small) if np.isfinite(small).any() else 0.0),
                           (filled.shape[1] // factor, filled.shape[0] // factor), interpolation=cv2.INTER_AREA)
        small_baseline = ndimage.percentile_filter(
            small.astype(np.float32), percentile=percentile, size=max(3, window_px // factor), mode="nearest"
        )
        baseline = cv2.resize(small_baseline, (filled.shape[1], filled.shape[0]), interpolation=cv2.INTER_LINEAR)
    else:
        baseline = ndimage.percentile_filter(filled, percentile=percentile, size=window_px, mode="nearest")
    baseline = np.where(np.isfinite(baseline), baseline, np.nan)
    return baseline.astype(np.float32)


def segment_buildings(
    rgb_image: np.ndarray,
    height_map: np.ndarray,
    confidence: Optional[np.ndarray] = None,
    local_window_px: int = DEFAULT_LOCAL_WINDOW_PX,
    min_area_px: int = DEFAULT_MIN_AREA_PX,
    min_fill_ratio: float = DEFAULT_MIN_FILL_RATIO,
    elevation_margin: Optional[float] = None,
    border_margin_px: Optional[int] = None,
    max_area_px: Optional[int] = None,
) -> BuildingSegmentation:
    """Extract candidate building footprints.

    `elevation_margin` is the minimum height-above-local-baseline (same units
    as `height_map`) to be considered "elevated". If not given, it defaults
    to 0.5x the robust (median-absolute-deviation based) spread of the
    height field -- a data-driven default, not a fixed physical constant,
    since relative (uncalibrated) DSMs have no fixed meaning for "0.5 m".

    `max_area_px`: rejects a contour LARGER than this -- lowering
    `min_fill_ratio` (see that constant's comment) to stop discarding real,
    non-rectangular single buildings also let through a different failure
    mode: in a dense scene, morphological closing can fuse several adjacent
    buildings (and the street/yard between them) into one sprawling blob
    that's still irregular enough to have a moderate fill_ratio. Verified on
    the same real test image used to tune `min_fill_ratio`: single-building
    candidates topped out at 6190px, then there was a sharp, clean jump to
    11864px+ (up to 119586px -- ~11% of the whole 1024x1024 image, clearly
    several buildings and a road segment fused together) with nothing in
    between -- a real, not arbitrary, gap. Defaults to 1% of the image's
    total pixel count (resolution-relative, same convention as
    `border_margin_px`), which sits cleanly inside that gap.
    """
    if height_map.shape != rgb_image.shape[:2]:
        raise ValueError(
            f"height_map shape {height_map.shape} does not match rgb_image shape {rgb_image.shape[:2]}"
        )

    h, w = height_map.shape
    if max_area_px is None:
        max_area_px = round(0.01 * h * w)
    if border_margin_px is None:
        # Resolution-relative, not a fixed pixel count: verified against a real
        # 4141x2761 photo that a fixed 2px margin was too narrow -- the depth-model
        # border-artifact band left several false-positive footprints ~17-19px from
        # the edge (see context/decisions-log.md). 1% of the shorter side scales
        # sensibly across image sizes without needing per-image tuning.
        border_margin_px = max(4, round(0.01 * min(h, w)))
    finite = np.isfinite(height_map)
    empty = BuildingSegmentation(mask=np.zeros((h, w), dtype=bool), labels=np.zeros((h, w), dtype=np.int32))
    if finite.sum() < min_area_px:
        return empty

    baseline = _local_baseline(height_map, local_window_px)
    residual = height_map - baseline

    if elevation_margin is None:
        finite_residual = residual[finite]
        med = float(np.median(finite_residual))
        mad = float(np.median(np.abs(finite_residual - med)))
        # On a mostly-flat scene (majority of pixels near the same height,
        # e.g. open ground dominating a few buildings) the MAD alone can
        # collapse to ~0, which would flag ordinary floating-point noise in
        # the local-baseline filter as "elevated". Floor the margin at a
        # small fraction of the scene's own finite height range so a
        # near-zero MAD can't produce a near-zero threshold.
        finite_range = float(finite_residual.max() - finite_residual.min()) if finite_residual.size else 0.0
        elevation_margin = max(1.5 * mad, 0.02 * finite_range, 1e-6)

    elevated = finite & (residual > elevation_margin)
    if not elevated.any():
        return empty

    elevated_u8 = (elevated.astype(np.uint8)) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    closed = cv2.morphologyEx(elevated_u8, cv2.MORPH_CLOSE, kernel)
    opened = cv2.morphologyEx(closed, cv2.MORPH_OPEN, kernel)

    contours, _ = cv2.findContours(opened, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    labels = np.zeros((h, w), dtype=np.int32)
    footprints: list[list[tuple[float, float]]] = []
    label_id = 0

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < min_area_px:
            continue
        if area > max_area_px:
            # Almost certainly several buildings (and/or a street/yard
            # between them) fused into one blob by the morphological close
            # -- see max_area_px's docstring note. A real single building
            # this large would need a proper split (e.g. watershed on the
            # elevated mask), not a size cap silently dropping it; that's a
            # further improvement, not something to fake here.
            continue

        xs = contour[:, 0, 0]
        ys = contour[:, 0, 1]
        touches_border = (
            xs.min() <= border_margin_px
            or ys.min() <= border_margin_px
            or xs.max() >= (w - 1 - border_margin_px)
            or ys.max() >= (h - 1 - border_margin_px)
        )
        if touches_border:
            # See DEFAULT_BORDER_MARGIN_PX docstring note -- border-adjacent depth
            # predictions are unreliable and/or the footprint is cut off.
            continue

        rect = cv2.minAreaRect(contour)
        (rw, rh) = rect[1]
        rect_area = float(rw) * float(rh)
        fill_ratio = area / rect_area if rect_area > 0 else 0.0
        if fill_ratio < min_fill_ratio:
            # Irregular blob (typical of tree canopies) -- reject as "not building-like".
            continue

        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, DEFAULT_APPROX_EPSILON_FRAC * peri, True)
        if len(approx) < 3:
            continue

        label_id += 1
        cv2.drawContours(labels, [contour], -1, label_id, thickness=cv2.FILLED)
        footprints.append([(float(pt[0][0]), float(pt[0][1])) for pt in approx])

    mask = labels > 0
    return BuildingSegmentation(mask=mask, labels=labels, footprints=footprints)


# Largest plausible single-building footprint, as a fraction of the image. See the area check in
# segment_buildings_agl for why an oversized region is rejected unless it is a near-perfect rectangle.
MAX_BUILDING_AREA_FRACTION = 0.05


def segment_buildings_agl(
    rgb_image: np.ndarray,
    height_agl: np.ndarray,
    elevated_thr: float = 3.0,
    min_area_px: int = 120,
) -> BuildingSegmentation:
    """Footprints for height fields that already regress metres above ground (GAMUS fine-tune).

    Elevated pixels are split into individual objects with a distance-transform watershed;
    each object is kept as a building if it is compact/rectilinear, has a smooth roof (low
    height variation) and is not dominated by vegetation colour. Trees, which are round and
    height-rough, are rejected. Objects touching the frame are kept (the fine-tuned network has
    no border artefact band)."""
    from skimage.feature import peak_local_max
    from skimage.segmentation import watershed

    from app.landcover.classify import above_ground_height

    h, w = height_agl.shape
    above = above_ground_height(height_agl, True)
    img = rgb_image.astype(np.float32) / 255.0
    total = img.sum(axis=2) + 1e-6
    exg = (2 * img[..., 1] - img[..., 0] - img[..., 2]) / total
    vegetation = exg > 0.06

    candidate = (above > elevated_thr).astype(np.uint8)
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    candidate = cv2.morphologyEx(candidate, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    if not candidate.any():
        return BuildingSegmentation(mask=np.zeros((h, w), bool), labels=np.zeros((h, w), np.int32))

    distance = cv2.distanceTransform(candidate, cv2.DIST_L2, 5)
    peaks = peak_local_max(distance, min_distance=10, threshold_abs=3.0, labels=candidate.astype(int), exclude_border=False)
    markers = np.zeros((h, w), dtype=np.int32)
    for index, (r, c) in enumerate(peaks, start=1):
        markers[r, c] = index
    if len(peaks):
        regions = watershed(-distance, markers, mask=candidate.astype(bool))
    else:
        # No watershed peaks (e.g. every candidate blob is too small/flat to clear threshold_abs):
        # label connected components individually so disconnected buildings aren't merged into
        # one region (a raw binary mask would give every blob the same id).
        regions, _ = ndimage.label(candidate.astype(bool))

    gradient = np.hypot(cv2.Sobel(above, cv2.CV_32F, 1, 0), cv2.Sobel(above, cv2.CV_32F, 0, 1))
    labels = np.zeros((h, w), dtype=np.int32)
    footprints: list[list[tuple[float, float]]] = []
    next_id = 0
    max_building_area_px = int(MAX_BUILDING_AREA_FRACTION * h * w)
    # Crop every region to its bounding box before any per-pixel work: at full resolution on a
    # dense scene there can be thousands of regions, and doing `regions == id` / cv2.erode /
    # boolean indexing against the FULL h x w arrays for each one is O(regions * h * w) -- minutes
    # to hours on a large image instead of milliseconds. ndimage.find_objects gives every
    # region's (row_slice, col_slice) in one pass, so each region only touches its own crop.
    bboxes = ndimage.find_objects(regions)
    for region_id, bbox in enumerate(bboxes, start=1):
        if bbox is None:
            continue
        row_slice, col_slice = bbox
        regions_crop = regions[row_slice, col_slice]
        mask = regions_crop == region_id
        area = int(mask.sum())
        if area < min_area_px:
            continue
        contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        rect_w, rect_h = cv2.minAreaRect(contour)[1]
        rect_area = float(rect_w) * float(rect_h)
        contour_area = float(cv2.contourArea(contour))
        fill = contour_area / rect_area if rect_area > 0 else 0.0
        solidity = contour_area / max(float(cv2.contourArea(cv2.convexHull(contour))), 1.0)
        interior = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
        interior = interior if interior.sum() > 20 else mask
        above_crop, gradient_crop, vegetation_crop = above[row_slice, col_slice], gradient[row_slice, col_slice], vegetation[row_slice, col_slice]
        values = above_crop[interior]
        roughness = float(values.std() / max(values.mean(), 1e-6))
        slope_mean = float(gradient_crop[interior].mean())
        green = float(vegetation_crop[mask].mean())
        building_like = (slope_mean < 4.5) + (solidity >= 0.80) + (fill >= 0.62) + (roughness <= 0.16)
        large_compact = area >= 1500 and solidity >= 0.88 and fill >= 0.68 and slope_mean < 7.0 and roughness < 0.3
        # A single building rarely covers more than a few percent of an aerial tile. Bare winter
        # woodland on a slope passes every shape/greenness test here (leafless trees are not green,
        # and the model smooths their canopy into a plausible-looking flat plateau), so an oversized
        # region is only kept if it is a near-perfect rectangle -- the shape of a real large roof.
        is_near_rectangle = solidity >= 0.97 and fill >= 0.90
        if area > max_building_area_px and not is_near_rectangle:
            continue
        if (building_like < 3 and not large_compact) or green > 0.55:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, DEFAULT_APPROX_EPSILON_FRAC * peri, True)
        if len(approx) < 3:
            continue
        next_id += 1
        labels[row_slice, col_slice][mask] = next_id
        row_off, col_off = row_slice.start, col_slice.start
        footprints.append([(float(pt[0][0] + col_off), float(pt[0][1] + row_off)) for pt in approx])

    return BuildingSegmentation(
        mask=labels > 0,
        labels=labels,
        footprints=footprints,
        method_note=(
            "Heuristic classical-CV segmentation on the fine-tuned height field: elevation threshold, "
            "distance-transform watershed, compactness + roof-smoothness filters. Not a trained model."
        ),
    )


def segment_at_scale(segment_fn, rgb_image: np.ndarray, height_map: np.ndarray, factor: float) -> BuildingSegmentation:
    """Run a segmentation function at `factor` (<1) of full resolution, then map the result back.

    The pixel-based parameters (watershed spacing, minimum area, morphology kernels) are tuned for
    ~0.5 m/px imagery; on much finer data they shatter each roof into fragments. Labels are restored
    with nearest-neighbour resampling and footprints are rescaled, so ids still line up."""
    if factor >= 1.0:
        return segment_fn(rgb_image, height_map)
    h, w = height_map.shape
    size = (max(1, round(w * factor)), max(1, round(h * factor)))
    small = segment_fn(cv2.resize(rgb_image, size, interpolation=cv2.INTER_AREA),
                       cv2.resize(height_map, size, interpolation=cv2.INTER_AREA))
    labels = cv2.resize(small.labels.astype(np.int32), (w, h), interpolation=cv2.INTER_NEAREST)
    sx, sy = w / size[0], h / size[1]
    footprints = [[(x * sx, y * sy) for x, y in polygon] for polygon in small.footprints]
    return BuildingSegmentation(mask=labels > 0, labels=labels, footprints=footprints,
                                method_note=small.method_note + f" Run at {factor:.2f}x resolution and mapped back.")
