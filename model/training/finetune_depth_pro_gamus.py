"""Fine-tune Apple Depth Pro on GAMUS (nadir aerial RGB -> AGL height).

Mirrors finetune_da_v2_full.py: same dataset pairing (gamus_dataset.index_split),
same scale-and-shift-invariant L1 loss and aligned metrics (ssi_loss.py), same
per-epoch best/last checkpointing and JSONL log.

Differences from the DA V2 pipeline, all forced by Depth Pro's design:
  - The network only accepts 1536x1536 inputs normalized with mean=std=0.5
    (not ImageNet stats), so this file has its own small Dataset.
  - forward() returns (canonical_inverse_depth, fov_deg). Inverse depth is a
    "closeness" field like DA V2's output (larger = nearer the sensor = taller
    for nadir imagery), so the SSI loss applies to it directly. The FOV head is
    not supervised by GAMUS and is frozen.
  - The model is ~1.9B params at 1536px. To fit consumer VRAM we freeze the
    image/FOV encoders by default, train the patch encoder at a tiny LR plus the
    decoder/head at a larger one, use bf16 autocast, batch size 1 and heavy
    gradient accumulation, and optionally gradient-checkpoint the ViT blocks.

Usage:
    python ml/training/finetune_depth_pro_gamus.py [--gamus-root PATH] [--epochs N]
"""

from __future__ import annotations

import argparse
import gc
import json
import sys
import time
from pathlib import Path

import cv2
import h5py
import numpy as np
import torch
from torch.utils.checkpoint import checkpoint
from torch.utils.data import DataLoader, Dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO_ROOT / "ml" / "ml-depth-pro-main" / "src"))

from gamus_dataset import index_split  # noqa: E402
from ssi_loss import scale_shift_invariant_l1, aligned_metrics  # noqa: E402
from depth_pro.depth_pro import DEFAULT_MONODEPTH_CONFIG_DICT, DepthProConfig, create_model_and_transforms  # noqa: E402

# --- config ---
DEFAULT_GAMUS_ROOT = Path(r"D:\Datasets\GAMUS")
BASE_CHECKPOINT = REPO_ROOT / "ml" / "ml-depth-pro-main" / "checkpoints" / "depth_pro.pt"
INPUT_SIZE = 1536  # fixed by DepthPro.forward (asserts H == W == img_size)

BATCH_SIZE = 1
GRAD_ACCUM_STEPS = 8
EPOCHS = 5
LR_PATCH_ENCODER = 1e-6
LR_DECODER_HEAD = 1e-5
NUM_WORKERS = 2
GRAD_CLIP_NORM = 1.0
FREEZE_IMAGE_ENCODER = True
GRADIENT_CHECKPOINTING = True

RUN_DIR = REPO_ROOT / "ml" / "training" / "runs" / "depth_pro_gamus"
LOG_FILE = RUN_DIR / "train_log.jsonl"
BEST_CHECKPOINT = REPO_ROOT / "ml" / "ml-depth-pro-main" / "checkpoints" / "depth_pro_gamus_best.pt"
LAST_CHECKPOINT = REPO_ROOT / "ml" / "ml-depth-pro-main" / "checkpoints" / "depth_pro_gamus_last.pt"


class DepthProGamusDataset(Dataset):
    """Yields (image, height, valid_mask) with Depth Pro's 0.5/0.5 normalization at 1536x1536."""

    def __init__(self, root: Path, split: str, max_samples: int | None = None, augment: bool = False) -> None:
        self.pairs = index_split(Path(root), split)
        if not self.pairs:
            raise FileNotFoundError(f"No GAMUS pairs found under {root} for split '{split}'")
        if max_samples is not None:
            self.pairs = self.pairs[:max_samples]
        self.augment = augment

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, index: int):
        pair = self.pairs[index]
        with h5py.File(pair.image_path, "r") as f:
            image = f["image"][...]
        with h5py.File(pair.height_path, "r") as f:
            height = f["image"][...].astype(np.float32)

        image = cv2.resize(image, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_CUBIC)
        height = cv2.resize(height, (INPUT_SIZE, INPUT_SIZE), interpolation=cv2.INTER_NEAREST)

        if self.augment:  # nadir imagery has no canonical orientation: flips / 90-degree turns are label-safe
            if np.random.rand() < 0.5:
                image, height = image[:, ::-1], height[:, ::-1]
            if np.random.rand() < 0.5:
                image, height = image[::-1], height[::-1]
            k = np.random.randint(4)
            image, height = np.rot90(image, k), np.rot90(height, k)

        valid = np.isfinite(height) & (height >= 0)
        height = np.nan_to_num(height, nan=0.0, posinf=0.0, neginf=0.0)

        image_f = (image.astype(np.float32) / 255.0 - 0.5) / 0.5
        image_chw = np.transpose(image_f, (2, 0, 1))
        return (
            torch.from_numpy(image_chw.copy()).float(),
            torch.from_numpy(height.copy()).float(),
            torch.from_numpy(valid.copy()),
        )


def log(record: dict) -> None:
    record["ts"] = time.time()
    print(record, flush=True)
    with LOG_FILE.open("a") as f:
        f.write(json.dumps(record) + "\n")


def build_model(device: torch.device):
    config = DepthProConfig(
        patch_encoder_preset=DEFAULT_MONODEPTH_CONFIG_DICT.patch_encoder_preset,
        image_encoder_preset=DEFAULT_MONODEPTH_CONFIG_DICT.image_encoder_preset,
        decoder_features=DEFAULT_MONODEPTH_CONFIG_DICT.decoder_features,
        checkpoint_uri=str(BASE_CHECKPOINT),
        fov_encoder_preset=DEFAULT_MONODEPTH_CONFIG_DICT.fov_encoder_preset,
        use_fov_head=True,
    )
    model, _ = create_model_and_transforms(config=config, device=device, precision=torch.float32)
    return model


def configure_trainable(model) -> list[dict]:
    """Freeze FOV head (+ optionally image encoder); return optimizer param groups."""
    for p in model.parameters():
        p.requires_grad = False

    patch_params = list(model.encoder.patch_encoder.parameters())
    decoder_head_params = list(model.decoder.parameters()) + list(model.head.parameters())
    # Upsampling/projection layers inside the encoder that are not ViT backbones.
    other_encoder_params = [
        p for n, p in model.encoder.named_parameters()
        if not n.startswith(("patch_encoder.", "image_encoder."))
    ]
    groups = [
        {"params": patch_params, "lr": LR_PATCH_ENCODER},
        {"params": decoder_head_params + other_encoder_params, "lr": LR_DECODER_HEAD},
    ]
    if not FREEZE_IMAGE_ENCODER:
        groups.append({"params": list(model.encoder.image_encoder.parameters()), "lr": LR_PATCH_ENCODER})
    for g in groups:
        for p in g["params"]:
            p.requires_grad = True
    return groups


def enable_gradient_checkpointing(model) -> None:
    """Wrap each ViT block's forward in torch.utils.checkpoint to trade compute for VRAM."""
    vits = [model.encoder.patch_encoder]
    if not FREEZE_IMAGE_ENCODER:
        vits.append(model.encoder.image_encoder)
    for vit in vits:
        for block in getattr(vit, "blocks", []):
            orig_forward = block.forward

            def make_forward(fn):
                def wrapped(*args, **kwargs):
                    return checkpoint(fn, *args, use_reentrant=False, **kwargs)
                return wrapped

            block.forward = make_forward(orig_forward)


def predict(model, img: torch.Tensor) -> torch.Tensor:
    inverse_depth, _ = model(img)  # (B, 1, H, W)
    return inverse_depth.squeeze(1)


def run_validation(model, val_loader, device) -> dict[str, float]:
    model.eval()
    agg = {"rmse_m": [], "mae_m": [], "correlation": []}
    with torch.no_grad():
        for img, height, mask in val_loader:
            img, height, mask = img.to(device), height.to(device), mask.to(device)
            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=(device.type == "cuda")):
                pred = predict(model, img)
            m = aligned_metrics(pred.float(), height, mask)
            for k in agg:
                agg[k].append(m[k])
    return {k: float(np.mean(v)) for k, v in agg.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gamus-root", type=Path, default=DEFAULT_GAMUS_ROOT)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    parser.add_argument("--max-train", type=int, default=None, help="cap train pairs (smoke test)")
    parser.add_argument("--max-val", type=int, default=None, help="cap val pairs (smoke test)")
    args = parser.parse_args()

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    BEST_CHECKPOINT.parent.mkdir(parents=True, exist_ok=True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    log({"event": "start", "device": str(device), "config": {
        "input_size": INPUT_SIZE, "batch_size": BATCH_SIZE, "grad_accum_steps": GRAD_ACCUM_STEPS,
        "epochs": args.epochs, "lr_patch_encoder": LR_PATCH_ENCODER, "lr_decoder_head": LR_DECODER_HEAD,
        "freeze_image_encoder": FREEZE_IMAGE_ENCODER, "gradient_checkpointing": GRADIENT_CHECKPOINTING,
    }})

    train_ds = DepthProGamusDataset(args.gamus_root, "train", max_samples=args.max_train, augment=True)
    val_ds = DepthProGamusDataset(args.gamus_root, "val", max_samples=args.max_val)
    log({"event": "data", "train_pairs": len(train_ds), "val_pairs": len(val_ds)})

    train_loader = DataLoader(
        train_ds, batch_size=BATCH_SIZE, shuffle=True, num_workers=NUM_WORKERS,
        drop_last=True, persistent_workers=NUM_WORKERS > 0,
    )
    val_loader = DataLoader(
        val_ds, batch_size=BATCH_SIZE, shuffle=False, num_workers=NUM_WORKERS,
        persistent_workers=NUM_WORKERS > 0,
    )

    model = build_model(device)
    param_groups = configure_trainable(model)
    if GRADIENT_CHECKPOINTING:
        enable_gradient_checkpointing(model)
    optimizer = torch.optim.AdamW(param_groups)

    baseline = run_validation(model, val_loader, device)
    log({"event": "baseline", **baseline})
    best_rmse = baseline["rmse_m"]
    torch.save(model.state_dict(), BEST_CHECKPOINT)

    for epoch in range(1, args.epochs + 1):
        model.train()
        epoch_start = time.time()
        losses: list[float] = []
        optimizer.zero_grad(set_to_none=True)

        for step, (img, height, mask) in enumerate(train_loader):
            img, height, mask = img.to(device), height.to(device), mask.to(device)

            with torch.autocast(device_type=device.type, dtype=torch.bfloat16, enabled=(device.type == "cuda")):
                pred = predict(model, img)
            loss = scale_shift_invariant_l1(pred.float(), height, mask) / GRAD_ACCUM_STEPS

            loss.backward()  # bf16 needs no GradScaler
            losses.append(loss.item() * GRAD_ACCUM_STEPS)

            if (step + 1) % GRAD_ACCUM_STEPS == 0:
                torch.nn.utils.clip_grad_norm_(
                    [p for g in param_groups for p in g["params"]], max_norm=GRAD_CLIP_NORM
                )
                optimizer.step()
                optimizer.zero_grad(set_to_none=True)

            if step % 100 == 0:
                log({"event": "step", "epoch": epoch, "step": step, "loss": float(np.mean(losses[-20:]))})

        val_metrics = run_validation(model, val_loader, device)
        log({
            "event": "epoch_end", "epoch": epoch, "train_loss": float(np.mean(losses)),
            **val_metrics, "epoch_time_min": (time.time() - epoch_start) / 60,
        })

        torch.save(model.state_dict(), LAST_CHECKPOINT)
        if val_metrics["rmse_m"] < best_rmse:
            best_rmse = val_metrics["rmse_m"]
            torch.save(model.state_dict(), BEST_CHECKPOINT)
            log({"event": "new_best", "epoch": epoch, "rmse_m": best_rmse})

    log({"event": "done", "best_rmse_m": best_rmse, "baseline_rmse_m": baseline["rmse_m"]})

    del model
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
