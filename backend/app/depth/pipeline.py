"""Sequential DA V2 (tiled + TTA) and optional Depth Pro inference, VRAM-safe.

Each network is loaded, run and unloaded before the next one loads. Depth Pro is an optional
ensemble member: it is used as a sharp-edge guide, and it is skipped (with a logged reason)
if it cannot run on the available GPU memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import json
import subprocess
import sys

import cv2
import numpy as np

from app.core.logging import get_logger
from app.depth.da_v2_adapter import ProgressFn, TiledDepthResult, run_tiled_da_v2

logger = get_logger(__name__)

DEPTH_PRO_MAX_SIDE = 1536
DEPTH_PRO_MIN_FREE_COMMIT_GB = 6.0
DEPTH_PRO_TIMEOUT_S = 900

# Predicted heights depend strongly on how large objects appear at the network's 518 px input, and the
# fine-tuned checkpoint was trained on satellite tiles (0.5 m/px). Fed a 0.076 m/px aerial scene as-is,
# houses looked several times larger than in training and the 95th-percentile house height came out ~21 m.
# Measured against reference house heights (1 floor 4.5-5.5 m, 2 floors 6-7.5 m, 3 floors 9-10.5 m):
# an effective input resolution of ~0.5 m/px (0.25 m/px image, 1024 px tiles squeezed to 518) matches
# them, ~1 m/px reads too low and ~0.15 m/px far too high. Finer inputs are therefore resampled to
# INFERENCE_GSD_M for inference only.
INFERENCE_GSD_M = 0.25
# Building segmentation thresholds (watershed spacing, minimum area, kernels) are tuned for 0.5 m/px.
SEGMENTATION_GSD_M = 0.5
RESAMPLE_BELOW_GSD_M = 0.35


def inference_scale(gsd_m: Optional[float]) -> float:
    """Linear factor (<= 1) applied to the image before inference; 1.0 when the GSD is unknown or not finer than INFERENCE_GSD_M."""
    if gsd_m is None or not np.isfinite(gsd_m) or gsd_m <= 0 or gsd_m >= INFERENCE_GSD_M:
        return 1.0
    return float(gsd_m / INFERENCE_GSD_M)


def segmentation_scale(gsd_m: Optional[float]) -> float:
    """Linear factor (<= 1) for running building segmentation at its tuned ~0.5 m/px resolution."""
    if gsd_m is None or not np.isfinite(gsd_m) or gsd_m <= 0 or gsd_m >= RESAMPLE_BELOW_GSD_M:
        return 1.0
    return float(gsd_m / SEGMENTATION_GSD_M)


def free_commit_gb() -> float | None:
    """Free virtual memory (commit) available to a new process, in GB; None if it cannot be determined."""
    try:
        if sys.platform == "win32":
            import ctypes

            class _Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total_phys", ctypes.c_ulonglong),
                            ("avail_phys", ctypes.c_ulonglong), ("total_page", ctypes.c_ulonglong),
                            ("avail_page", ctypes.c_ulonglong), ("total_virtual", ctypes.c_ulonglong),
                            ("avail_virtual", ctypes.c_ulonglong), ("avail_ext", ctypes.c_ulonglong)]

            status = _Status()
            status.length = ctypes.sizeof(_Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.avail_page / 1e9
        with open("/proc/meminfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) / 1e6
    except Exception:  # noqa: BLE001
        return None
    return None


def _run_depth_pro_isolated(small_path: Path, checkpoint: Path, precision: str, device: str, work_dir: Path) -> dict:
    free = free_commit_gb()
    if free is not None and free < DEPTH_PRO_MIN_FREE_COMMIT_GB:
        raise RuntimeError(f"only {free:.1f} GB of memory is free and Depth Pro needs about {DEPTH_PRO_MIN_FREE_COMMIT_GB:.0f} GB")
    prefix = str(work_dir / "depth_pro_out")
    command = [sys.executable, "-m", "app.depth.depth_pro_worker", str(small_path), str(checkpoint), precision, device, prefix]
    backend_root = Path(__file__).resolve().parents[2]
    result = subprocess.run(command, cwd=backend_root, capture_output=True, timeout=DEPTH_PRO_TIMEOUT_S)
    if result.returncode != 0:
        tail = result.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["worker exited abnormally"]
        raise RuntimeError(f"Depth Pro worker failed (exit {result.returncode}): {tail[0][:200]}")
    depth = np.load(prefix + ".npy")
    focal = json.loads(Path(prefix + ".json").read_text(encoding="utf-8"))["focallength_px"]
    for suffix in (".npy", ".json"):
        Path(prefix + suffix).unlink(missing_ok=True)
    return {"depth": depth, "focallength_px": focal}


@dataclass
class DepthStackResult:
    da: TiledDepthResult
    depth_pro_metric_depth: Optional[np.ndarray]  # HxW float32 metres at full resolution, or None
    depth_pro_focallength_px: Optional[float]
    depth_pro_skipped_reason: Optional[str]


def run_depth_stack(
    rgb: np.ndarray,
    work_dir: Path,
    da_v2_checkpoint: Path,
    da_v2_encoder: str,
    depth_pro_checkpoint: Path,
    depth_pro_precision: str,
    device_preference: str,
    tile_size: int,
    overlap: float,
    tta: bool,
    use_depth_pro: bool,
    on_tiles_planned: Optional[Callable[[int, int], None]] = None,
    on_da_progress: Optional[ProgressFn] = None,
    on_depth_pro_start: Optional[Callable[[], None]] = None,
    gsd_m: Optional[float] = None,
) -> DepthStackResult:
    height, width = rgb.shape[:2]
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    factor = inference_scale(gsd_m)
    if factor < 1.0:
        bgr = cv2.resize(bgr, (max(1, round(width * factor)), max(1, round(height * factor))), interpolation=cv2.INTER_AREA)
        logger.info("Resampled %dx%d -> %dx%d for inference (GSD %.3f m/px -> %.2f m/px)",
                    width, height, bgr.shape[1], bgr.shape[0], gsd_m, INFERENCE_GSD_M)

    da_result = run_tiled_da_v2(
        image_bgr=bgr,
        checkpoint_path=da_v2_checkpoint,
        encoder=da_v2_encoder,
        device_preference=device_preference,
        tile_size=tile_size,
        overlap=overlap,
        tta=tta,
        on_progress=on_da_progress,
        on_tiles_planned=on_tiles_planned,
    )
    if factor < 1.0:
        da_result.mean = cv2.resize(da_result.mean, (width, height), interpolation=cv2.INTER_CUBIC).astype(np.float32)
        da_result.std = np.maximum(cv2.resize(da_result.std, (width, height), interpolation=cv2.INTER_LINEAR), 0.0).astype(np.float32)

    if not use_depth_pro:
        return DepthStackResult(da_result, None, None, "Ensemble disabled by the user.")

    if on_depth_pro_start:
        on_depth_pro_start()

    scale = min(1.0, DEPTH_PRO_MAX_SIDE / max(height, width))
    small = rgb if scale >= 1.0 else cv2.resize(
        rgb, (int(round(width * scale)), int(round(height * scale))), interpolation=cv2.INTER_AREA
    )
    small_path = work_dir / "depth_pro_input.png"
    cv2.imwrite(str(small_path), cv2.cvtColor(small, cv2.COLOR_RGB2BGR))

    try:
        result = _run_depth_pro_isolated(small_path, depth_pro_checkpoint, depth_pro_precision, device_preference, work_dir)
    except Exception as exc:  # noqa: BLE001 - OOM or missing weights degrade to DA V2 only
        logger.warning("Depth Pro skipped: %s", exc)
        return DepthStackResult(da_result, None, None, f"Depth Pro unavailable on this machine: {exc}")
    finally:
        small_path.unlink(missing_ok=True)

    depth = result["depth"]
    if depth.shape != (height, width):
        depth = cv2.resize(depth, (width, height), interpolation=cv2.INTER_CUBIC)
    return DepthStackResult(da_result, depth.astype(np.float32), float(result["focallength_px"]), None)
