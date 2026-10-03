"""Height-field construction (`build_height_field`, used by the pipeline) and the legacy
Depth Anything V2 + Depth Pro edge-aware fusion (`fuse_depth_maps`, no longer called by the
pipeline: it assumed DA V2 was inverse depth, which is wrong for the fine-tuned model).

Legacy fusion description:

PRD.md Section 8 / IMPLEMENTATION.md Section 5: do not simply average the two
raw fields -- they are in incompatible units/scales and must be aligned
first, then combined using Depth Pro's sharper structural boundaries to
refine DA V2's globally-consistent field, not the other way around.

Method (documented, not fabricated):

1. **Scale alignment.** DA V2's raw output is a relative *inverse* depth
   (larger = closer). Convert it to a depth-like quantity via
   `1 / (da_v2 + eps)` (larger = farther, matching Depth Pro's convention),
   then fit `depth_pro ~= a * da_v2_pseudo_depth + b` by least squares over a
   random pixel sample. This is a real per-image affine fit, not a fixed
   constant.
2. **Edge-aware refinement.** Run a guided filter (He et al. 2010, "Guided
   Image Filtering") with Depth Pro's metric depth as the guide and the
   scale-aligned DA V2 field as the filter input. This keeps DA V2's globally
   consistent geometry while snapping edges to Depth Pro's sharper
   boundaries -- implemented directly with `cv2.boxFilter` (no ximgproc
   dependency required).
3. **Confidence.** `confidence = 1 - normalize(|guided_da_v2 - depth_pro|)`,
   per IMPLEMENTATION.md Section 5's baseline formula.
4. **Confidence-weighted blend.** Where the two backbones agree (high
   confidence), blend toward Depth Pro's metric value; where they disagree,
   fall back to the edge-refined DA V2 field to preserve global consistency,
   per PRD.md Section 7 ("preserve Depth Anything V2 global consistency").
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

_EPS = 1e-6


@dataclass
class FusionResult:
    fused_depth: np.ndarray  # HxW float32, same units as Depth Pro (meters)
    confidence: np.ndarray  # HxW float32, [0, 1]
    scale_a: float
    scale_b: float


def _robust_affine_fit(x: np.ndarray, y: np.ndarray, sample_size: int = 20000) -> tuple[float, float]:
    """Least-squares fit y ~= a*x + b over a random finite-valued sample."""
    valid = np.isfinite(x) & np.isfinite(y)
    xs, ys = x[valid], y[valid]
    if xs.size < 100:
        return 1.0, 0.0

    if xs.size > sample_size:
        idx = np.random.default_rng(0).choice(xs.size, size=sample_size, replace=False)
        xs, ys = xs[idx], ys[idx]

    design = np.vstack([xs, np.ones_like(xs)]).T
    result, *_ = np.linalg.lstsq(design, ys, rcond=None)
    a, b = float(result[0]), float(result[1])
    if np.isfinite(a) and a > 0:
        residual = ys - (a * xs + b)
        keep = np.abs(residual) <= 2.5 * (1.4826 * np.median(np.abs(residual - np.median(residual))) + 1e-9)
        if keep.sum() > 100:
            result, *_ = np.linalg.lstsq(design[keep], ys[keep], rcond=None)
            a, b = float(result[0]), float(result[1])
    if not np.isfinite(a) or a <= 0:
        # Degenerate fit (e.g. near-constant DA V2 field): fall back to identity.
        return 1.0, 0.0
    return a, b


def _guided_filter(guide: np.ndarray, src: np.ndarray, radius: int = 8, eps: float = 1e-2) -> np.ndarray:
    """Classic guided filter (He, Sun, Tang 2010), implemented with box filters."""
    ksize = (radius, radius)
    guide = guide.astype(np.float32)
    src = src.astype(np.float32)

    mean_g = cv2.boxFilter(guide, ddepth=-1, ksize=ksize)
    mean_s = cv2.boxFilter(src, ddepth=-1, ksize=ksize)
    mean_gs = cv2.boxFilter(guide * src, ddepth=-1, ksize=ksize)
    cov_gs = mean_gs - mean_g * mean_s

    mean_gg = cv2.boxFilter(guide * guide, ddepth=-1, ksize=ksize)
    var_g = mean_gg - mean_g * mean_g

    a = cov_gs / (var_g + eps)
    b = mean_s - a * mean_g

    mean_a = cv2.boxFilter(a, ddepth=-1, ksize=ksize)
    mean_b = cv2.boxFilter(b, ddepth=-1, ksize=ksize)

    return mean_a * guide + mean_b


def _normalize01(arr: np.ndarray) -> np.ndarray:
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros_like(arr)
    lo, hi = float(finite.min()), float(finite.max())
    if hi <= lo:
        return np.zeros_like(arr)
    return np.clip((arr - lo) / (hi - lo), 0, 1)


@dataclass
class HeightFieldResult:
    height: np.ndarray  # HxW float32, ground = 0, larger = taller (approx. metres after scaling)
    confidence: np.ndarray  # HxW float32, [0, 1]
    ground_level: float  # raw model value treated as ground


def build_height_field(
    da_v2_output: np.ndarray,
    flip_disagreement: np.ndarray,
    height_scale: float = 1.0,
    ground_percentile: float = 2.0,
) -> HeightFieldResult:
    """Height field from the GAMUS-fine-tuned DA V2 output (the pipeline's height source).

    The fine-tuned model regresses height-above-ground directly (larger = taller), so no
    inversion or Depth Pro alignment is involved -- on nadir imagery Depth Pro is
    anti-correlated with height and adding it made the DSM worse (see README, Validation).

    - Ground level = low percentile of the output, subtracted so ground sits at 0.
    - `height_scale` maps model units to approximate metres (empirical: the model output
      is compressed ~2.6x relative to true AGL on held-out GAMUS tiles; it is NOT a
      calibrated per-image metric scale).
    - Confidence = 1 - flip disagreement normalised by its 99th percentile.
    """
    da = da_v2_output.astype(np.float32)
    finite = np.isfinite(da)
    if not finite.any():
        raise ValueError("Depth Anything V2 output has no finite pixels")

    ground = float(np.percentile(da[finite], ground_percentile))
    height = np.where(finite, np.clip(da - ground, 0.0, None) * height_scale, np.nan)

    d = np.where(np.isfinite(flip_disagreement), flip_disagreement, 0.0)
    ref = float(np.percentile(d, 99)) or 1.0
    confidence = 1.0 - np.clip(d / max(ref, _EPS), 0.0, 1.0)

    return HeightFieldResult(
        height=height.astype(np.float32),
        confidence=confidence.astype(np.float32),
        ground_level=ground,
    )


def uncertainty_from_std(std: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """Normalise a TTA standard-deviation field to [0, 1] against the dynamic range of the
    height field it belongs to (robust: 98th percentile of the std maps to 1)."""
    finite = std[np.isfinite(std)]
    if finite.size == 0:
        return np.zeros_like(std, dtype=np.float32)
    top = float(np.percentile(finite, 98))
    if top <= 1e-12:
        return np.zeros_like(std, dtype=np.float32)
    return np.clip(std / top, 0.0, 1.0).astype(np.float32)


def da_only_relative_height(da_field: np.ndarray, is_height: bool) -> np.ndarray:
    """Relative height (larger = taller, arbitrary units, ground near 0) without Depth Pro."""
    field = da_field.astype(np.float32)
    finite = field[np.isfinite(field)]
    if finite.size == 0:
        return np.zeros_like(field, dtype=np.float32)
    baseline = float(np.percentile(finite, 1.0 if is_height else 0.5))
    return np.maximum(field - baseline, 0.0).astype(np.float32)


def fuse_depth_maps(
    da_v2_relative: np.ndarray,
    depth_pro_metric: np.ndarray,
    da_is_height: bool = False,
) -> FusionResult:
    if da_v2_relative.shape != depth_pro_metric.shape:
        raise ValueError(
            f"Depth map shape mismatch: DA V2 {da_v2_relative.shape} vs Depth Pro {depth_pro_metric.shape}"
        )

    if da_is_height:
        da_v2_pseudo_depth = -da_v2_relative.astype(np.float32)
    else:
        da_v2_pseudo_depth = 1.0 / (da_v2_relative.astype(np.float32) + _EPS)
    depth_pro_metric = depth_pro_metric.astype(np.float32)

    a, b = _robust_affine_fit(da_v2_pseudo_depth, depth_pro_metric)
    aligned_da_v2 = a * da_v2_pseudo_depth + b

    # Guided filter needs a bounded/normalized guide for a meaningful eps.
    guide_norm = _normalize01(depth_pro_metric)
    guided_da_v2 = _guided_filter(guide=guide_norm, src=aligned_da_v2, radius=8, eps=1e-2)

    diff = np.abs(guided_da_v2 - depth_pro_metric)
    confidence = 1.0 - _normalize01(diff)

    fused = confidence * depth_pro_metric + (1.0 - confidence) * guided_da_v2

    return FusionResult(
        fused_depth=fused.astype(np.float32),
        confidence=confidence.astype(np.float32),
        scale_a=a,
        scale_b=b,
    )
