"""Adapter around the vendored Apple Depth Pro model (model/ml-depth-pro-main).

Produces *metric* depth in meters when it can estimate (or is given) a focal
length; otherwise the metric scale is only as good as its internal FOV
estimate. We still treat it as "structural/detail" input per PRD Section 7 --
its main contribution to the fused output is sharp boundaries, not the
absolute scale (that comes from SRTM/GCP calibration downstream).
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import torch

from app.core.logging import get_logger
from app.depth.device import cuda_scope, resolve_device

logger = get_logger(__name__)

_PRECISION_MAP = {
    "float16": torch.float16,
    "float32": torch.float32,
    "bfloat16": torch.bfloat16,
}


class DepthProUnavailable(RuntimeError):
    """Raised when the checkpoint or model source is missing."""


def run_depth_pro(
    image_path: Path,
    checkpoint_path: Path,
    device_preference: str = "cuda",
    precision: str = "float16",
    f_px: Optional[float] = None,
) -> dict:
    """Run Depth Pro inference on an image file.

    Args:
        image_path: path to the source image (Depth Pro reads it directly to
            preserve EXIF-based focal length hints where available).
        checkpoint_path: path to depth_pro.pt.
        device_preference: "cuda" or "cpu".
        precision: "float16" | "float32" | "bfloat16".
        f_px: optional known focal length in pixels; overrides Depth Pro's
            own FOV-head estimate when provided (e.g. from GeoTIFF/sensor metadata).

    Returns:
        dict with:
          "depth": HxW float32 metric depth in meters,
          "focallength_px": float, focal length used (estimated or provided).
    """
    if not checkpoint_path.exists():
        raise DepthProUnavailable(
            f"Depth Pro checkpoint not found at {checkpoint_path}. "
            "Set DEPTH_PRO_CHECKPOINT in .env to a valid local path."
        )

    try:
        import depth_pro
    except ImportError as exc:
        raise DepthProUnavailable(
            "depth_pro package not importable. Install it with "
            "`pip install -e model/ml-depth-pro-main --no-deps` from the repo root."
        ) from exc

    device = resolve_device(device_preference)
    torch_precision = _PRECISION_MAP.get(precision, torch.float16)
    if device.type == "cpu":
        # fp16 matmul kernels are unreliable/unsupported on CPU for this model.
        torch_precision = torch.float32

    with cuda_scope("DepthPro"):
        config = depth_pro.depth_pro.DepthProConfig(
            patch_encoder_preset="dinov2l16_384",
            image_encoder_preset="dinov2l16_384",
            checkpoint_uri=str(checkpoint_path),
            decoder_features=256,
            use_fov_head=True,
            fov_encoder_preset="dinov2l16_384",
        )
        model, transform = depth_pro.create_model_and_transforms(
            config=config, device=device, precision=torch_precision
        )
        model.eval()
        logger.info("Loaded Depth Pro from %s", checkpoint_path)

        image, _, exif_f_px = depth_pro.load_rgb(str(image_path))
        image_tensor = transform(image)

        focal_length = f_px if f_px is not None else exif_f_px

        with torch.inference_mode():
            prediction = model.infer(image_tensor, f_px=focal_length)

        depth = prediction["depth"].detach().float().cpu().numpy()
        focallength_px = float(prediction["focallength_px"])

        del model
    return {"depth": depth.astype(np.float32), "focallength_px": focallength_px}
