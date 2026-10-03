"""Relative height -> metric height, fusing three independent scale sources (FR-13..FR-18).

The model predicts a relative height field h (larger = taller, arbitrary units). It is split into
a smooth ground trend g and an object part o = max(0, h - g). The metric object height is
nDSM = s * o with a single scale s that is estimated from:

  * DEM   - Huber-robust regression of the ground trend against the (bare-earth) DTM, used only
            when the scene has enough terrain relief and the trend correlates with the DEM;
  * GCPs  - weighted least squares on known elevations (weight 10 each);
  * Shadow- median of shadow-derived building height / relative building height.

The scales are fused in log space with quality weights. Absolute DSM = DTM + nDSM when a DEM (or
GCP datum) anchors the scene; otherwise the result is a pseudo-metric nDSM (metres above local
ground) or stays relative. Nothing is fabricated: with no scale evidence the output is relative, except
that a height-regressing checkpoint contributes its native metre scale as a low-weight fallback source.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import rasterio
from rasterio.warp import transform as warp_transform
from scipy import ndimage
from scipy.optimize import least_squares

from app.input.detect import GeoMetadata
from app.jobs.models import GroundControlPoint
from app.landcover.classify import CLASS_HEIGHT_CAPS, GROUND, ROAD, WATER

GCP_WEIGHT = 10.0


@dataclass
class ScaleSource:
    name: str
    scale: float
    weight: float
    detail: str


@dataclass
class CalibrationOutcome:
    kind: str  # "absolute_dsm" | "pseudo_metric" | "relative"
    scale: Optional[float] = None
    shift: float = 0.0
    sources: list[ScaleSource] = field(default_factory=list)
    ndsm_m: Optional[np.ndarray] = None
    dsm: Optional[np.ndarray] = None
    dtm: Optional[np.ndarray] = None
    ground_trend_rel: Optional[np.ndarray] = None
    ground_residual_rmse_m: Optional[float] = None
    gcp_residuals: list[dict] = field(default_factory=list)
    scale_log_sigma: Optional[float] = None
    notes: list[str] = field(default_factory=list)

    @property
    def is_metric(self) -> bool:
        return self.kind in ("absolute_dsm", "pseudo_metric")


def gcps_to_pixels(
    gcps: list[GroundControlPoint], geo: Optional[GeoMetadata], shape: tuple[int, int]
) -> list[tuple[float, float, float, str]]:
    """Return (row, col, elevation, label) for every GCP that lands inside the image."""
    out: list[tuple[float, float, float, str]] = []
    height, width = shape
    for index, gcp in enumerate(gcps):
        label = gcp.label or f"GCP {index + 1}"
        if gcp.col is not None and gcp.row is not None:
            row, col = gcp.row, gcp.col
        elif gcp.x is not None and gcp.y is not None and geo is not None:
            x, y = gcp.x, gcp.y
            if gcp.lonlat:
                xs, ys = warp_transform("EPSG:4326", geo.crs, [x], [y])
                x, y = xs[0], ys[0]
            col, row = ~rasterio.Affine(*geo.transform) * (x, y)
        else:
            continue
        if 0 <= row < height and 0 <= col < width:
            out.append((float(row), float(col), float(gcp.elevation_m), label))
    return out


def ground_trend(rel_height: np.ndarray, ground_mask: np.ndarray) -> np.ndarray:
    """Smooth ground level (relative units) via normalised convolution over ground pixels."""
    finite = np.isfinite(rel_height)
    mask = (ground_mask & finite).astype(np.float32)
    values = np.where(finite, rel_height, 0.0).astype(np.float32) * mask
    sigma = max(rel_height.shape) / 14.0
    factor = max(1, int(sigma // 12))
    if factor > 1:
        small_shape = (rel_height.shape[0] // factor, rel_height.shape[1] // factor)
        import cv2

        m = cv2.resize(mask, (small_shape[1], small_shape[0]), interpolation=cv2.INTER_AREA)
        v = cv2.resize(values, (small_shape[1], small_shape[0]), interpolation=cv2.INTER_AREA)
        num = ndimage.gaussian_filter(v, sigma / factor, mode="nearest")
        den = ndimage.gaussian_filter(m, sigma / factor, mode="nearest")
        trend_small = np.where(den > 1e-4, num / np.maximum(den, 1e-4), np.nan)
        fallback = float(np.median(rel_height[ground_mask & finite])) if (ground_mask & finite).any() else 0.0
        trend_small = np.where(np.isfinite(trend_small), trend_small, fallback)
        return cv2.resize(trend_small.astype(np.float32), (rel_height.shape[1], rel_height.shape[0]),
                          interpolation=cv2.INTER_LINEAR)
    num = ndimage.gaussian_filter(values, sigma, mode="nearest")
    den = ndimage.gaussian_filter(mask, sigma, mode="nearest")
    fallback = float(np.median(rel_height[ground_mask & finite])) if (ground_mask & finite).any() else 0.0
    return np.where(den > 1e-4, num / np.maximum(den, 1e-4), fallback).astype(np.float32)


def _dem_source(trend: np.ndarray, dtm: np.ndarray) -> Optional[ScaleSource]:
    valid = np.isfinite(trend) & np.isfinite(dtm)
    if valid.sum() < 500:
        return None
    x = trend[valid].astype(np.float64)
    y = dtm[valid].astype(np.float64)
    if x.std() < 1e-9 or y.std() < 3.0:
        return None
    corr = float(np.corrcoef(x, y)[0, 1])
    if not np.isfinite(corr) or corr < 0.6:
        return None
    idx = np.random.default_rng(1).choice(x.size, size=min(x.size, 30000), replace=False)
    xs, ys = x[idx], y[idx]
    a0 = float(y.std() / x.std())
    fit = least_squares(lambda p: p[0] * xs + p[1] - ys, x0=[a0, float(np.median(ys) - a0 * np.median(xs))],
                        loss="huber", f_scale=1.0)
    slope = float(fit.x[0])
    if not np.isfinite(slope) or slope <= 0:
        return None
    weight = float(corr**2 * min(1.0, y.std() / 30.0))
    return ScaleSource("dem", slope, weight, f"Huber fit of ground trend vs DTM (r={corr:.2f}, relief sd={y.std():.1f} m)")


def _gcp_source(
    pixels: list[tuple[float, float, float, str]], objects_rel: np.ndarray, rel_height: np.ndarray,
    dtm: Optional[np.ndarray],
) -> tuple[Optional[ScaleSource], float, list[dict]]:
    """Weighted LSQ for (s, t); returns source, shift and per-GCP residual records."""
    if not pixels:
        return None, 0.0, []
    rows = np.round([p[0] for p in pixels]).astype(int)
    cols = np.round([p[1] for p in pixels]).astype(int)
    rows = np.clip(rows, 0, rel_height.shape[0] - 1)
    cols = np.clip(cols, 0, rel_height.shape[1] - 1)
    target = np.array([p[2] for p in pixels], dtype=np.float64)
    if dtm is not None:
        ground_z = dtm[rows, cols].astype(np.float64)
        need = target - np.where(np.isfinite(ground_z), ground_z, np.nan)
        feature = objects_rel[rows, cols].astype(np.float64)
    else:
        need = target
        feature = rel_height[rows, cols].astype(np.float64)
    ok = np.isfinite(need) & np.isfinite(feature)
    if ok.sum() == 0:
        return None, 0.0, []
    need, feature = need[ok], feature[ok]
    if ok.sum() == 1 or np.ptp(feature) < 1e-6:
        if feature[0] <= 1e-6:
            return None, 0.0, []
        scale = float(np.median(need / np.maximum(feature, 1e-6)))
        shift = 0.0
    else:
        design = np.stack([feature, np.ones_like(feature)], axis=1)
        (scale, shift), *_ = np.linalg.lstsq(design * GCP_WEIGHT, need * GCP_WEIGHT, rcond=None)
        scale, shift = float(scale), float(shift)
        if scale <= 0:
            scale = float(np.median(need / np.maximum(feature, 1e-6)))
            shift = 0.0
    if not np.isfinite(scale) or scale <= 0:
        return None, 0.0, []
    residuals = []
    labels = [p[3] for p in pixels]
    kept = np.nonzero(ok)[0]
    for k, pos in enumerate(kept):
        predicted = scale * feature[k] + shift
        residuals.append({
            "label": labels[pos],
            "elevation_m": float(target[pos]),
            "predicted_m": float(predicted + (dtm[rows[pos], cols[pos]] if dtm is not None else 0.0)),
            "error_m": float(predicted - need[k]),
        })
    return ScaleSource("gcp", scale, GCP_WEIGHT * len(kept), f"{len(kept)} GCP(s), weight {GCP_WEIGHT:g} each"), shift, residuals


def _shadow_source(pairs: list[tuple[float, float]]) -> Optional[ScaleSource]:
    """pairs: (relative object height, shadow-derived metric height) per building."""
    usable = [(rel, metric) for rel, metric in pairs if rel > 1e-6 and metric > 0.5]
    if len(usable) < 3:
        return None
    ratios = np.array([metric / rel for rel, metric in usable])
    median = float(np.median(ratios))
    mad = float(np.median(np.abs(ratios - median)))
    quality = float(np.clip(1.0 - (mad / max(median, 1e-9)), 0.05, 1.0))
    weight = min(3.0, len(usable) / 8.0) * quality
    return ScaleSource("shadow", median, weight, f"{len(usable)} buildings, median H=L*tan(el); spread {mad / max(median, 1e-9):.0%}")


def apply_semantic_priors(ndsm_m: np.ndarray, labels: np.ndarray) -> np.ndarray:
    out = ndsm_m.copy()
    for class_id, cap in CLASS_HEIGHT_CAPS.items():
        mask = labels == class_id
        out[mask] = np.minimum(out[mask], cap)
    return out


def calibrate_scene(
    rel_height: np.ndarray,
    labels: np.ndarray,
    geo: Optional[GeoMetadata],
    dtm: Optional[np.ndarray],
    gcps: list[GroundControlPoint],
    shadow_pairs: list[tuple[float, float]],
    native_scale_prior: Optional[float] = None,
) -> CalibrationOutcome:
    finite = np.isfinite(rel_height)
    ground_mask = np.isin(labels, [GROUND, ROAD, WATER])
    trend = ground_trend(rel_height, ground_mask)
    objects_rel = np.where(finite, np.maximum(rel_height - trend, 0.0), np.nan).astype(np.float32)

    sources: list[ScaleSource] = []
    notes: list[str] = []
    shift = 0.0
    residuals: list[dict] = []

    if dtm is not None:
        source = _dem_source(trend, dtm)
        if source:
            sources.append(source)
        else:
            notes.append("DEM present but the scene has too little relief/correlation to fix the scale; used for terrain only.")

    pixels = gcps_to_pixels(gcps, geo, rel_height.shape)
    if gcps and not pixels:
        notes.append("None of the supplied GCPs fall inside the image.")
    gcp_source, gcp_shift, residuals = _gcp_source(pixels, objects_rel, rel_height, dtm)
    if gcp_source:
        sources.append(gcp_source)
        shift = gcp_shift

    shadow = _shadow_source(shadow_pairs)
    if shadow:
        sources.append(shadow)

    if not sources and native_scale_prior is not None:
        # The fine-tuned network regresses height above ground in (empirically scaled) metres, so its own
        # output is a far better fallback than range-normalising to an arbitrary "relative" scale, which
        # printed values like "30 m" for a single house. Without a DEM this is pseudo-metric (height above
        # local ground) rather than an absolute DSM.
        sources.append(ScaleSource("model_native", native_scale_prior, 0.4,
                                   "Fine-tuned network's native metre scale (no DEM relief, GCP or shadow evidence)"))
        notes.append("Scale rests on the network's native output scale only (trained at ~0.5 m/px); "
                     "treat heights as approximate. Supply the real GSD, GCPs or a sun elevation to tighten it.")

    if not sources:
        return CalibrationOutcome(kind="relative", ground_trend_rel=trend, notes=notes + [
            "No scale evidence (DEM relief, GCPs or shadow geometry): output stays a relative DSM."])

    logs = np.log(np.array([s.scale for s in sources]))
    weights = np.array([s.weight for s in sources])
    log_scale = float((logs * weights).sum() / weights.sum())
    scale = math.exp(log_scale)
    sigma = float(np.sqrt((weights * (logs - log_scale) ** 2).sum() / weights.sum())) if len(sources) > 1 else None

    ndsm = apply_semantic_priors((scale * objects_rel + max(shift, 0.0)).astype(np.float32), labels)
    ndsm = np.where(finite, np.maximum(ndsm, 0.0), np.nan).astype(np.float32)

    kind = "pseudo_metric"
    dsm = ndsm
    used_dtm = None
    if dtm is not None:
        dtm_filled = np.where(np.isfinite(dtm), dtm, np.nanmedian(dtm)).astype(np.float32)
        dsm = (dtm_filled + np.nan_to_num(ndsm, nan=0.0)).astype(np.float32)
        dsm = np.where(finite, dsm, np.nan)
        kind = "absolute_dsm"
        used_dtm = dtm_filled
    elif pixels and gcp_source:
        rows = np.array([int(p[0]) for p in pixels])
        cols = np.array([int(p[1]) for p in pixels])
        datum = float(np.nanmedian(np.array([p[2] for p in pixels]) - ndsm[rows, cols]))
        dsm = (ndsm + datum).astype(np.float32)
        kind = "absolute_dsm"
        used_dtm = np.full(ndsm.shape, datum, dtype=np.float32)
        notes.append("Absolute datum taken from the GCP elevations (no DEM).")

    ground_residual = None
    ground = ground_mask & finite
    if ground.any():
        ground_residual = float(np.sqrt(np.nanmean(ndsm[ground] ** 2)))

    return CalibrationOutcome(
        kind=kind,
        scale=scale,
        shift=float(shift),
        sources=sources,
        ndsm_m=ndsm,
        dsm=dsm,
        dtm=used_dtm,
        ground_trend_rel=trend,
        ground_residual_rmse_m=ground_residual,
        gcp_residuals=residuals,
        scale_log_sigma=sigma,
        notes=notes,
    )
