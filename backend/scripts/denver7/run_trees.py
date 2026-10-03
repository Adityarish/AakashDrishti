"""Run the tree-crown detector over the whole 0.5 ft/px mosaic -> data/trees_auto.json (crowns, no heights yet)."""

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
from detect_cars import pavement_mask  # noqa: E402
from detect_trees import canopy_mask, split_crowns  # noqa: E402


def main(mosaic_npy: str, classes_npy: str) -> None:
    mosaic = np.load(mosaic_npy, mmap_mode="r")
    buildings = json.loads((HERE / "data" / "buildings_final.json").read_text(encoding="utf-8"))
    cars = json.loads((HERE / "data" / "cars_auto.json").read_text(encoding="utf-8"))
    core, margin = MOSAIC // 4, 120
    found = []
    classes = np.zeros((MOSAIC, MOSAIC), np.uint8)   # 0 other, 1 pavement, 2 canopy, 3 building, 4 vehicle
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
            roofs = cv2.dilate(roofs, np.ones((5, 5), np.uint8))
            car_mask = np.zeros_like(roofs)
            for c in cars:
                p = np.array(c["polygon"]) - [ca, ra]
                if p[:, 0].max() < 0 or p[:, 1].max() < 0 or p[:, 0].min() > block.shape[1] or p[:, 1].min() > block.shape[0]:
                    continue
                cv2.fillPoly(car_mask, [np.round(p).astype(np.int32)], 1)
            canopy = canopy_mask(block, roofs, car_mask)
            pave = pavement_mask(block, roofs)
            near_car = cv2.dilate(car_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
            pave_c = cv2.morphologyEx(pave, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
            cls = np.zeros(block.shape[:2], np.uint8)
            cls[pave > 0] = 1
            cls[canopy > 0] = 2
            cls[roofs > 0] = 3
            cls[car_mask > 0] = 4
            classes[r0:r0 + core, c0:c0 + core] = cls[r0 - ra:r0 - ra + core, c0 - ca:c0 - ca + core]
            for crown in split_crowns(canopy):
                cx, cy = crown["center"][0] + ca, crown["center"][1] + ra
                if not (r0 <= cy < r0 + core and c0 <= cx < c0 + core):
                    continue
                x, y, r = int(crown["center"][0]), int(crown["center"][1]), crown["radius_px"]
                disc = np.zeros(block.shape[:2], np.uint8)
                cv2.circle(disc, (x, y), max(2, int(r)), 1, -1)
                d = disc.astype(bool)
                rgb = np.median(block[d].reshape(-1, 3), axis=0)
                found.append({"center": [cx, cy], "radius_px": r, "rgb": [float(v) for v in rgb],
                              "car_frac": float(near_car[d].mean()), "pave_frac": float(pave_c[d].mean())})
            print(f"block {bi},{bj}: {len(found)} crowns ({time.time() - t0:.0f}s)", flush=True)
    (HERE / "data" / "trees_auto.json").write_text(json.dumps(found), encoding="utf-8")
    np.save(classes_npy, classes)
    print("crowns", len(found))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
