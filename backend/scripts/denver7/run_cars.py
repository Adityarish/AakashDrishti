"""Run the car detector over the whole 0.5 ft/px mosaic (4x4 blocks with overlap) -> data/cars_auto.json."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from common import MOSAIC  # noqa: E402
from detect_cars import detect_cars  # noqa: E402


def main(mosaic_npy: str) -> None:
    mosaic = np.load(mosaic_npy, mmap_mode="r")
    buildings = json.loads((HERE / "data" / "buildings_final.json").read_text(encoding="utf-8"))
    core, margin = MOSAIC // 4, 220
    found = []
    t0 = time.time()
    for bi in range(4):
        for bj in range(4):
            r0, c0 = bi * core, bj * core
            ra, ca = max(0, r0 - margin), max(0, c0 - margin)
            rb, cb = min(MOSAIC, r0 + core + margin), min(MOSAIC, c0 + core + margin)
            block = np.ascontiguousarray(mosaic[ra:rb, ca:cb])
            roofs = np.zeros(block.shape[:2], np.uint8)
            for o in buildings:
                p = np.array(o["polygon"]) - [ca, ra]
                if p[:, 0].max() < 0 or p[:, 1].max() < 0 or p[:, 0].min() > block.shape[1] or p[:, 1].min() > block.shape[0]:
                    continue
                cv2.fillPoly(roofs, [np.round(p).astype(np.int32)], 1)
            for car in detect_cars(block, roofs):
                cx, cy = car["center"][0] + ca, car["center"][1] + ra
                if not (r0 <= cy < r0 + core and c0 <= cx < c0 + core):
                    continue
                car["center"] = [cx, cy]
                car["polygon"] = (np.array(car["polygon"]) + [ca, ra]).round(1).tolist()
                found.append(car)
            print(f"block {bi},{bj}: {len(found)} cars ({time.time() - t0:.0f}s)", flush=True)
    (HERE / "data" / "cars_auto.json").write_text(json.dumps(found), encoding="utf-8")
    print("cars", len(found))


if __name__ == "__main__":
    main(sys.argv[1])
