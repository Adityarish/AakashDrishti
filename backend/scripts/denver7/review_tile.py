"""Render one review tile: the 0.5 m/px mosaic with a labelled 50 m grid and the numbered roof polygons."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import MOSAIC  # noqa: E402

TILES = 6   # review grid; tile (i,j) covers rows i*880.. and cols j*880..
SCALE = 1.5


def render(mosaic_npy: str, roofs_json: str, i: int, j: int, out_png: str, extra_json: str | None = None) -> None:
    mosaic = np.load(mosaic_npy, mmap_mode="r")
    size = MOSAIC // TILES
    r0, c0 = i * size, j * size
    img = np.ascontiguousarray(mosaic[r0:r0 + size, c0:c0 + size])
    img = cv2.resize(img, None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    roofs = json.loads(Path(roofs_json).read_text(encoding="utf-8"))
    for k, roof in enumerate(roofs):
        poly = np.array(roof["polygon"])
        cx, cy = poly[:, 0].mean(), poly[:, 1].mean()
        if not (c0 - 5 <= cx < c0 + size + 5 and r0 - 5 <= cy < r0 + size + 5):
            continue
        pts = np.round((poly - [c0, r0]) * SCALE).astype(np.int32)
        cv2.polylines(img, [pts], True, (0, 0, 255), 1)
        label = str(k)
        pos = (int((cx - c0) * SCALE) - 14, int((cy - r0) * SCALE) + 6)
        cv2.putText(img, label, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
        cv2.putText(img, label, pos, cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    if extra_json:
        for seed in json.loads(Path(extra_json).read_text(encoding="utf-8")):
            poly = np.array(seed["polygon"])
            cx, cy = poly[:, 0].mean(), poly[:, 1].mean()
            if c0 - 5 <= cx < c0 + size + 5 and r0 - 5 <= cy < r0 + size + 5:
                cv2.polylines(img, [np.round((poly - [c0, r0]) * SCALE).astype(np.int32)], True, (0, 255, 0), 1)
    for g in range((c0 // 100) * 100, c0 + size + 100, 100):
        x = int((g - c0) * SCALE)
        if 0 <= x < img.shape[1]:
            cv2.line(img, (x, 0), (x, img.shape[0]), (255, 255, 0), 1)
            cv2.putText(img, str(g), (x + 2, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    for g in range((r0 // 100) * 100, r0 + size + 100, 100):
        y = int((g - r0) * SCALE)
        if 0 <= y < img.shape[0]:
            cv2.line(img, (0, y), (img.shape[1], y), (255, 255, 0), 1)
            cv2.putText(img, str(g), (2, y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 255), 1)
    cv2.imwrite(out_png, img)


if __name__ == "__main__":
    render(sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), sys.argv[5], sys.argv[6] if len(sys.argv) > 6 else None)
