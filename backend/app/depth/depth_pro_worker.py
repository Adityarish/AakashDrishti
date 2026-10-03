"""Runs Depth Pro in its own process: python -m app.depth.depth_pro_worker <image> <checkpoint> <precision> <device> <out_prefix>.

Isolation matters: on memory-constrained machines the model load can abort the interpreter, and that
must never take the API server down with it."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np


def main() -> int:
    image, checkpoint, precision, device, out_prefix = sys.argv[1:6]
    import torch

    original_load = torch.load
    # memory-map the ~2 GB checkpoint instead of copying it into RAM (file-backed pages, far less commit)
    torch.load = lambda *args, **kwargs: original_load(*args, **{**kwargs, "mmap": True, "weights_only": False})
    from app.depth.depth_pro_adapter import run_depth_pro

    result = run_depth_pro(Path(image), Path(checkpoint), device_preference=device, precision=precision)
    np.save(out_prefix + ".npy", result["depth"])
    Path(out_prefix + ".json").write_text(json.dumps({"focallength_px": result["focallength_px"]}), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
