"""Run the automatic roof detector + GrabCut refinement over the whole 0.5 m/px mosaic (4x4 blocks with overlap)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MOSAIC  # noqa: E402
from detect_roofs import detect_roofs, refine_with_grabcut  # noqa: E402


def main(mosaic_npy: str, out_json: str) -> None:
    mosaic = np.load(mosaic_npy, mmap_mode="r")
    core, margin = MOSAIC // 4, 200
    found = []
    t0 = time.time()
    for bi in range(4):
        for bj in range(4):
            r0, c0 = bi * core, bj * core
            ra, ca = max(0, r0 - margin), max(0, c0 - margin)
            rb, cb = min(MOSAIC, r0 + core + margin), min(MOSAIC, c0 + core + margin)
            block = np.ascontiguousarray(mosaic[ra:rb, ca:cb])
            for roof in detect_roofs(block):
                poly = np.asarray(roof["polygon"])
                refined = refine_with_grabcut(block, poly)
                final = refined if refined is not None else poly
                cx, cy = final[:, 0].mean() + ca, final[:, 1].mean() + ra
                if not (r0 <= cy < r0 + core and c0 <= cx < c0 + core):
                    continue  # owned by the neighbouring block
                found.append({"polygon": (final + [ca, ra]).round(1).tolist(), "refined": refined is not None,
                              "mean_rgb": [round(v, 1) for v in roof["mean_rgb"]]})
            print(f"block {bi},{bj}: total {len(found)}  ({time.time() - t0:.0f}s)", flush=True)
    Path(out_json).write_text(json.dumps(found), encoding="utf-8")
    print("wrote", out_json, len(found))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
