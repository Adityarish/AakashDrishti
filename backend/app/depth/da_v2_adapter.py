"""Depth Anything V2 adapter: tiled inference with D4 test-time augmentation.

The network returns a *relative* field (inverse depth for the stock checkpoint, height above
ground for the GAMUS fine-tuned checkpoint). Large scenes are cut into overlapping tiles;
each tile is averaged over the 8 D4 flips/rotations (valid because nadir imagery is
rotation-invariant), neighbouring tiles are affinely aligned on their overlap, and tiles are
merged with a Hann-window blend so no seams appear (FR-06, FR-07, FR-10).

The mean over TTA variants is the height estimate; the standard deviation is the uncertainty.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
import torch
import torch.nn.functional as F

from app.core.logging import get_logger
from app.depth.device import cuda_scope, resolve_device

logger = get_logger(__name__)
cv2.ocl.setUseOpenCL(False)

_MODEL_CONFIGS = {
    "vits": {"encoder": "vits", "features": 64, "out_channels": [48, 96, 192, 384]},
    "vitb": {"encoder": "vitb", "features": 128, "out_channels": [96, 192, 384, 768]},
    "vitl": {"encoder": "vitl", "features": 256, "out_channels": [256, 512, 1024, 1024]},
    "vitg": {"encoder": "vitg", "features": 384, "out_channels": [1536, 1536, 1536, 1536]},
}

ProgressFn = Callable[[float, str], None]


class DepthAnythingV2Unavailable(RuntimeError):
    """Raised when the checkpoint or model source is missing."""


@dataclass
class TiledDepthResult:
    mean: np.ndarray  # HxW float32 relative field (same convention as the checkpoint output)
    std: np.ndarray  # HxW float32, TTA standard deviation in the same units as `mean`
    tile_count: int
    tta_variants: int
    seconds: float
    checkpoint_is_height: bool


def checkpoint_outputs_height(checkpoint_path: Path) -> bool:
    """The GAMUS fine-tuned weights regress height above ground (larger = taller); the stock
    checkpoint regresses inverse depth. Both are 'larger = higher' for nadir imagery."""
    return "gamus" in checkpoint_path.name.lower()


def load_model(checkpoint_path: Path, encoder: str, device: torch.device):
    if not checkpoint_path.is_file():
        raise DepthAnythingV2Unavailable(
            f"Depth Anything V2 checkpoint not found at {checkpoint_path}. "
            "Set DEPTH_ANYTHING_V2_CHECKPOINT in .env to a valid local .pth file."
        )
    if encoder not in _MODEL_CONFIGS:
        raise ValueError(f"Unknown DA V2 encoder '{encoder}', expected one of {list(_MODEL_CONFIGS)}")
    try:
        from depth_anything_v2.dpt import DepthAnythingV2
    except ImportError as exc:
        raise DepthAnythingV2Unavailable(
            "depth_anything_v2 package not importable. Install it with "
            "`pip install --no-deps -e ml/Depth-Anything-V2`."
        ) from exc

    model = DepthAnythingV2(**_MODEL_CONFIGS[encoder])
    state_dict = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    model.load_state_dict(state_dict)
    return model.to(device).eval()


def _prepare(image_bgr: np.ndarray, input_size: int) -> tuple[torch.Tensor, tuple[int, int]]:
    """Same preprocessing as DepthAnythingV2.image2tensor but device-agnostic (stays on CPU)."""
    from depth_anything_v2.util.transform import NormalizeImage, PrepareForNet, Resize
    from torchvision.transforms import Compose

    transform = Compose([
        Resize(width=input_size, height=input_size, resize_target=False, keep_aspect_ratio=True,
               ensure_multiple_of=14, resize_method="lower_bound", image_interpolation_method=cv2.INTER_CUBIC),
        NormalizeImage(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        PrepareForNet(),
    ])
    height, width = image_bgr.shape[:2]
    rgb = cv2.cvtColor(np.ascontiguousarray(image_bgr), cv2.COLOR_BGR2RGB) / 255.0
    tensor = torch.from_numpy(transform({"image": rgb})["image"]).unsqueeze(0)
    return tensor, (height, width)


def _predict(model, image_bgr: np.ndarray, device: torch.device, input_size: int) -> np.ndarray:
    tensor, (height, width) = _prepare(image_bgr, input_size)
    use_amp = device.type == "cuda"
    with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=torch.float16, enabled=use_amp):
        depth = model.forward(tensor.to(device))
        depth = F.interpolate(depth[:, None].float(), (height, width), mode="bilinear", align_corners=True)[0, 0]
    return depth.cpu().numpy().astype(np.float32)


def _d4_forward(image: np.ndarray, k: int, flip: bool) -> np.ndarray:
    out = np.rot90(image, k)
    if flip:
        out = out[:, ::-1]
    return np.ascontiguousarray(out)


def _d4_inverse(pred: np.ndarray, k: int, flip: bool) -> np.ndarray:
    out = pred[:, ::-1] if flip else pred
    return np.ascontiguousarray(np.rot90(out, -k))


def _robust_affine(source: np.ndarray, target: np.ndarray, max_samples: int = 40000) -> tuple[float, float]:
    """Least-squares a,b with target ~ a*source + b on a subsample; falls back to identity."""
    src = source.reshape(-1)
    tgt = target.reshape(-1)
    valid = np.isfinite(src) & np.isfinite(tgt)
    src, tgt = src[valid], tgt[valid]
    if src.size < 64:
        return 1.0, 0.0
    if src.size > max_samples:
        # Strided subsample: rng.choice(replace=False) over ~1M pixels costs tens of ms per call.
        step = src.size // max_samples + 1
        src, tgt = src[::step], tgt[::step]
    src_std = float(src.std())
    if src_std < 1e-9:
        return 1.0, float(np.median(tgt) - np.median(src))
    design = np.stack([src, np.ones_like(src)], axis=1)
    coef, *_ = np.linalg.lstsq(design, tgt, rcond=None)
    a, b = float(coef[0]), float(coef[1])
    residual = tgt - (a * src + b)
    keep = np.abs(residual) <= 2.5 * (1.4826 * np.median(np.abs(residual - np.median(residual))) + 1e-9)
    if keep.sum() > 64:
        coef, *_ = np.linalg.lstsq(design[keep], tgt[keep], rcond=None)
        a, b = float(coef[0]), float(coef[1])
    if not np.isfinite(a) or a <= 0:
        return 1.0, float(np.median(tgt) - np.median(src))
    return a, b


_D4_VARIANTS = [(k, flip) for flip in (False, True) for k in range(4)]


def _robust_affine_t(source: torch.Tensor, target: torch.Tensor, max_samples: int = 40000) -> tuple[float, float]:
    """torch twin of `_robust_affine` (same two-pass MAD-trimmed least squares) that stays on the GPU."""
    src, tgt = source.reshape(-1), target.reshape(-1)
    if src.numel() > max_samples:
        step = src.numel() // max_samples + 1
        src, tgt = src[::step], tgt[::step]
    valid = torch.isfinite(src) & torch.isfinite(tgt)
    src, tgt = src[valid].double(), tgt[valid].double()
    if src.numel() < 64:
        return 1.0, 0.0
    if float(src.std()) < 1e-9:
        return 1.0, float(tgt.median() - src.median())

    def fit(s: torch.Tensor, t: torch.Tensor) -> tuple[float, float]:
        sm, tm = s.mean(), t.mean()
        var = ((s - sm) ** 2).mean()
        a = ((s - sm) * (t - tm)).mean() / var
        return float(a), float(tm - a * sm)

    a, b = fit(src, tgt)
    residual = tgt - (a * src + b)
    mad = 1.4826 * (residual - residual.median()).abs().median() + 1e-9
    keep = residual.abs() <= 2.5 * mad
    if int(keep.sum()) > 64:
        a, b = fit(src[keep], tgt[keep])
    if not np.isfinite(a) or a <= 0:
        return 1.0, float(tgt.median() - src.median())
    return a, b


def _forward_chunked(model, batch: torch.Tensor, use_amp: bool, device_type: str) -> torch.Tensor:
    """Run the batch through the network, halving the chunk size on CUDA OOM instead of failing."""
    chunk = batch.shape[0]
    while True:
        try:
            outs = []
            with torch.inference_mode(), torch.autocast(device_type=device_type, dtype=torch.float16, enabled=use_amp):
                for i in range(0, batch.shape[0], chunk):
                    outs.append(model.forward(batch[i:i + chunk]).float())
            return torch.cat(outs, dim=0)
        except torch.OutOfMemoryError:
            if chunk == 1:
                raise
            torch.cuda.empty_cache()
            chunk //= 2


def _tta_predict_batched(
    model, tile_bgr: np.ndarray, device: torch.device, input_size: int
) -> tuple[np.ndarray, np.ndarray, int]:
    """All 8 D4 views in one batched forward pass. The tile is resized/normalised once and the
    flips/rotations are applied to the (square) tensor on the GPU, so the results equal the
    per-view path while skipping 7 CPU resizes and every host round-trip except the final one."""
    tensor, (height, width) = _prepare(tile_bgr, input_size)
    tensor = tensor.to(device)
    batch = torch.cat([
        _d4_tensor(tensor, k, flip) for k, flip in _D4_VARIANTS
    ], dim=0)
    use_amp = device.type == "cuda"
    depth = _forward_chunked(model, batch, use_amp, device.type)
    depth = F.interpolate(depth[:, None], (height, width), mode="bilinear", align_corners=True)[:, 0]
    views = torch.stack([_d4_tensor_inverse(depth[i], k, flip) for i, (k, flip) in enumerate(_D4_VARIANTS)])
    reference = views[0]
    aligned = [reference]
    for i in range(1, views.shape[0]):
        a, b = _robust_affine_t(views[i], reference)
        aligned.append(a * views[i] + b)
    stack = torch.stack(aligned)
    mean = stack.mean(dim=0).cpu().numpy().astype(np.float32)
    std = stack.std(dim=0, correction=0).cpu().numpy().astype(np.float32)
    return mean, std, len(_D4_VARIANTS)


def _d4_tensor(x: torch.Tensor, k: int, flip: bool) -> torch.Tensor:
    """Tensor twin of `_d4_forward` on an NCHW batch: rot90 over (H, W), then flip columns."""
    out = torch.rot90(x, k, (2, 3))
    return out.flip(3) if flip else out


def _d4_tensor_inverse(pred: torch.Tensor, k: int, flip: bool) -> torch.Tensor:
    """Tensor twin of `_d4_inverse` on an HxW map."""
    out = pred.flip(1) if flip else pred
    return torch.rot90(out, -k, (0, 1))


def _tta_predict(
    model, tile_bgr: np.ndarray, device: torch.device, input_size: int, tta: bool
) -> tuple[np.ndarray, np.ndarray, int]:
    if not tta:
        base = _predict(model, tile_bgr, device, input_size)
        return base, np.zeros_like(base), 1

    if tile_bgr.shape[0] == tile_bgr.shape[1]:
        return _tta_predict_batched(model, tile_bgr, device, input_size)

    # Non-square edge tiles change shape under 90-degree rotation, so they cannot share a batch.
    aligned: list[np.ndarray] = []
    reference: Optional[np.ndarray] = None
    for k, flip in _D4_VARIANTS:
        pred = _d4_inverse(_predict(model, _d4_forward(tile_bgr, k, flip), device, input_size), k, flip)
        if reference is None:
            reference = pred
            aligned.append(pred)
        else:
            a, b = _robust_affine(pred, reference)
            aligned.append(a * pred + b)
    stack = np.stack(aligned, axis=0)
    return stack.mean(axis=0), stack.std(axis=0), len(_D4_VARIANTS)


def _axis_weights(length: int, blend_start: int, blend_end: int) -> np.ndarray:
    """1D weights: cosine ramp over the first/last `blend_*` samples where a neighbour exists."""
    w = np.ones(length, dtype=np.float32)
    if blend_start > 1:
        ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(blend_start) + 0.5) / blend_start)
        w[:blend_start] = np.maximum(ramp, 1e-3)
    if blend_end > 1:
        ramp = 0.5 - 0.5 * np.cos(np.pi * (np.arange(blend_end)[::-1] + 0.5) / blend_end)
        w[length - blend_end :] = np.minimum(w[length - blend_end :], np.maximum(ramp, 1e-3))
    return w


def tile_grid(height: int, width: int, tile: int, overlap: float) -> list[tuple[int, int, int, int]]:
    """Return (y0, y1, x0, x1) windows covering the image; tiles stay full-size."""
    if max(height, width) <= tile:
        return [(0, height, 0, width)]
    stride = max(1, int(tile * (1.0 - overlap)))

    def starts(size: int) -> list[int]:
        if size <= tile:
            return [0]
        out = list(range(0, size - tile + 1, stride))
        if out[-1] != size - tile:
            out.append(size - tile)
        return out

    ys, xs = starts(height), starts(width)
    return [(y, min(y + tile, height), x, min(x + tile, width)) for y in ys for x in xs]


def _is_oom(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        isinstance(exc, torch.OutOfMemoryError)
        or any(token in text for token in ("out of memory", "paging file", "cuda error", "cublas", "cudnn", "cuda driver"))
    )


def run_tiled_da_v2(
    image_bgr: np.ndarray,
    checkpoint_path: Path,
    encoder: str = "vitb",
    device_preference: str = "cuda",
    input_size: int = 518,
    tile_size: int = 1024,
    overlap: float = 0.25,
    tta: bool = True,
    on_progress: Optional[ProgressFn] = None,
    on_tiles_planned: Optional[Callable[[int, int], None]] = None,
) -> TiledDepthResult:
    height, width = image_bgr.shape[:2]
    windows = tile_grid(height, width, tile_size, overlap)
    if on_tiles_planned:
        on_tiles_planned(len(windows), 8 if tta else 1)

    device = resolve_device(device_preference)
    try:
        return _run_on_device(image_bgr, windows, checkpoint_path, encoder, device, input_size, tile_size, overlap, tta, on_progress)
    except Exception as exc:  # noqa: BLE001
        if device.type == "cuda" and _is_oom(exc):
            logger.warning("GPU failure (%s); retrying Depth Anything V2 on the CPU", str(exc).splitlines()[0][:120])
            if on_progress:
                on_progress(0.0, "GPU unavailable, falling back to CPU")
            try:
                torch.cuda.empty_cache()
            except Exception:  # noqa: BLE001 - a poisoned CUDA context must not block the CPU retry
                pass
            return _run_on_device(image_bgr, windows, checkpoint_path, encoder, torch.device("cpu"), input_size,
                                  tile_size, overlap, tta, on_progress)
        raise


def _run_on_device(
    image_bgr: np.ndarray,
    windows: list[tuple[int, int, int, int]],
    checkpoint_path: Path,
    encoder: str,
    device: torch.device,
    input_size: int,
    tile_size: int,
    overlap: float,
    tta: bool,
    on_progress: Optional[ProgressFn],
) -> TiledDepthResult:
    height, width = image_bgr.shape[:2]
    started = time.time()

    canvas = np.zeros((height, width), dtype=np.float32)
    std_canvas = np.zeros((height, width), dtype=np.float32)
    weight_sum = np.zeros((height, width), dtype=np.float32)
    variants = 1

    with cuda_scope("DepthAnythingV2"):
        model = load_model(checkpoint_path, encoder, device)
        logger.info("Loaded Depth Anything V2 (%s) from %s on %s", encoder, checkpoint_path.name, device.type)

        for index, (y0, y1, x0, x1) in enumerate(windows):
            tile_mean, tile_std, variants = _tta_predict(
                model, np.ascontiguousarray(image_bgr[y0:y1, x0:x1]), device, input_size, tta
            )

            if index > 0:
                covered = weight_sum[y0:y1, x0:x1] > 0
                if covered.sum() > 256:
                    current = canvas[y0:y1, x0:x1][covered] / weight_sum[y0:y1, x0:x1][covered]
                    a, b = _robust_affine(tile_mean[covered], current)
                    tile_mean = a * tile_mean + b
                    tile_std = a * tile_std

            th, tw = y1 - y0, x1 - x0
            left = int(overlap * tile_size) if x0 > 0 else 0
            right = int(overlap * tile_size) if x1 < width else 0
            top = int(overlap * tile_size) if y0 > 0 else 0
            bottom = int(overlap * tile_size) if y1 < height else 0
            window = np.outer(
                _axis_weights(th, min(top, th // 2), min(bottom, th // 2)),
                _axis_weights(tw, min(left, tw // 2), min(right, tw // 2)),
            )
            canvas[y0:y1, x0:x1] += window * tile_mean
            std_canvas[y0:y1, x0:x1] += window * tile_std
            weight_sum[y0:y1, x0:x1] += window

            if on_progress:
                on_progress(100.0 * (index + 1) / len(windows), f"tile {index + 1}/{len(windows)} on {device.type}")

        del model

    weight_sum = np.maximum(weight_sum, 1e-6)
    return TiledDepthResult(
        mean=(canvas / weight_sum).astype(np.float32),
        std=(std_canvas / weight_sum).astype(np.float32),
        tile_count=len(windows),
        tta_variants=variants,
        seconds=time.time() - started,
        checkpoint_is_height=checkpoint_outputs_height(checkpoint_path),
    )
