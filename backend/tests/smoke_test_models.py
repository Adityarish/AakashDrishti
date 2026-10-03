"""One-off smoke test: real inference with both depth backbones, sequential-load VRAM pattern.

Not part of the pytest suite (models/weights aren't available in CI). Run manually:
    .venv/Scripts/python.exe tests/smoke_test_models.py
"""

from __future__ import annotations

import gc
import time
from pathlib import Path

import cv2
import numpy as np
import torch

REPO_ROOT = Path(__file__).resolve().parents[2]
DA_V2_CHECKPOINT = REPO_ROOT / "model" / "depth_anything_v2_vitb.pth"
DEPTH_PRO_CHECKPOINT = REPO_ROOT / "model" / "ml-depth-pro-main" / "checkpoints" / "depth_pro.pt"
SAMPLE_IMAGE = REPO_ROOT / "model" / "ml-depth-pro-main" / "data" / "example.jpg"

DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")


def report_vram(label: str) -> None:
    if not torch.cuda.is_available():
        print(f"[{label}] CUDA not available")
        return
    allocated = torch.cuda.memory_allocated() / 1024**2
    reserved = torch.cuda.memory_reserved() / 1024**2
    print(f"[{label}] VRAM allocated={allocated:.1f}MB reserved={reserved:.1f}MB")


def run_depth_anything_v2() -> np.ndarray:
    from depth_anything_v2.dpt import DepthAnythingV2

    model_configs = {
        "vitb": {"encoder": "vitb", "features": 128, "out_channels": [96, 192, 384, 768]},
    }

    print("\n=== Depth Anything V2 (vitb) ===")
    t0 = time.time()
    model = DepthAnythingV2(**model_configs["vitb"])
    state_dict = torch.load(DA_V2_CHECKPOINT, map_location="cpu")
    model.load_state_dict(state_dict)
    model = model.to(DEVICE).eval()
    print(f"Loaded weights in {time.time() - t0:.2f}s")
    report_vram("after DA V2 load")

    raw_image = cv2.imread(str(SAMPLE_IMAGE))
    if raw_image is None:
        raise FileNotFoundError(SAMPLE_IMAGE)

    t0 = time.time()
    with torch.inference_mode():
        depth = model.infer_image(raw_image, input_size=518)
    print(f"Inference in {time.time() - t0:.2f}s, output shape={depth.shape}, dtype={depth.dtype}")
    print(f"depth stats: min={depth.min():.4f} max={depth.max():.4f} mean={depth.mean():.4f}")

    del model
    gc.collect()
    torch.cuda.empty_cache()
    report_vram("after DA V2 unload")
    return depth


def run_depth_pro() -> dict:
    import depth_pro

    print("\n=== Depth Pro ===")
    t0 = time.time()
    config = depth_pro.depth_pro.DepthProConfig(
        patch_encoder_preset="dinov2l16_384",
        image_encoder_preset="dinov2l16_384",
        checkpoint_uri=str(DEPTH_PRO_CHECKPOINT),
        decoder_features=256,
        use_fov_head=True,
        fov_encoder_preset="dinov2l16_384",
    )
    model, transform = depth_pro.create_model_and_transforms(
        config=config, device=DEVICE, precision=torch.float16
    )
    model.eval()
    print(f"Loaded weights in {time.time() - t0:.2f}s")
    report_vram("after Depth Pro load")

    image, _, f_px = depth_pro.load_rgb(str(SAMPLE_IMAGE))
    image_tensor = transform(image)

    t0 = time.time()
    prediction = model.infer(image_tensor, f_px=f_px)
    depth_m = prediction["depth"].detach().cpu().numpy()
    print(f"Inference in {time.time() - t0:.2f}s, output shape={depth_m.shape}, dtype={depth_m.dtype}")
    print(f"depth (metric, m): min={depth_m.min():.3f} max={depth_m.max():.3f} mean={depth_m.mean():.3f}")
    print(f"focal length (px): {float(prediction['focallength_px']):.2f}")

    del model
    gc.collect()
    torch.cuda.empty_cache()
    report_vram("after Depth Pro unload")
    return {"depth": depth_m, "focallength_px": prediction["focallength_px"]}


if __name__ == "__main__":
    print(f"Device: {DEVICE}")
    assert DA_V2_CHECKPOINT.exists(), f"missing {DA_V2_CHECKPOINT}"
    assert DEPTH_PRO_CHECKPOINT.exists(), f"missing {DEPTH_PRO_CHECKPOINT}"
    assert SAMPLE_IMAGE.exists(), f"missing {SAMPLE_IMAGE}"

    da_v2_depth = run_depth_anything_v2()
    depth_pro_result = run_depth_pro()

    print("\n=== Summary ===")
    print(f"DA V2 relative depth shape: {da_v2_depth.shape}")
    print(f"Depth Pro metric depth shape: {depth_pro_result['depth'].shape}")
    print("Both backbones ran sequentially without holding VRAM simultaneously.")
