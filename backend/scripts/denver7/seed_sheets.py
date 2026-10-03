"""Contact sheets for the seeds that could not be resolved automatically: local crops with an absolute-coordinate grid so
the roof can be traced precisely. usage: python seed_sheets.py <rgb_half.npy> <out_dir> [per_sheet=6]"""

import json
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
mosaic = np.load(sys.argv[1], mmap_mode="r")
out = Path(sys.argv[2])
per = int(sys.argv[3]) if len(sys.argv) > 3 else 6
failed = json.loads((HERE / "data" / "failed_seeds.json").read_text(encoding="utf-8"))
final = json.loads((HERE / "data" / "buildings_final.json").read_text(encoding="utf-8"))
HALF, SC, STEP = 110, 2.8, 20


def tile(idx, col, row, radius):
    x0 = int(min(max(0, col - HALF), 5280 - 2 * HALF))
    y0 = int(min(max(0, row - HALF), 5280 - 2 * HALF))
    img = cv2.cvtColor(np.ascontiguousarray(mosaic[y0:y0 + 2 * HALF, x0:x0 + 2 * HALF]), cv2.COLOR_RGB2BGR)
    img = cv2.resize(img, None, fx=SC, fy=SC, interpolation=cv2.INTER_CUBIC)
    for o in final:
        p = np.array(o["polygon"])
        if p[:, 0].max() < x0 or p[:, 0].min() > x0 + 2 * HALF or p[:, 1].max() < y0 or p[:, 1].min() > y0 + 2 * HALF:
            continue
        cv2.polylines(img, [np.round((p - [x0, y0]) * SC).astype(np.int32)], True, (0, 200, 0), 1)
    for g in range((x0 // STEP + 1) * STEP, x0 + 2 * HALF, STEP):
        X = int((g - x0) * SC)
        cv2.line(img, (X, 0), (X, img.shape[0]), (255, 255, 0) if g % 100 == 0 else (160, 160, 0), 1)
        if g % 40 == 0:
            cv2.putText(img, str(g), (X + 2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
    for g in range((y0 // STEP + 1) * STEP, y0 + 2 * HALF, STEP):
        Y = int((g - y0) * SC)
        cv2.line(img, (0, Y), (img.shape[1], Y), (255, 255, 0) if g % 100 == 0 else (160, 160, 0), 1)
        if g % 40 == 0:
            cv2.putText(img, str(g), (2, Y - 2), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
    cx, cy = int((col - x0) * SC), int((row - y0) * SC)
    cv2.circle(img, (cx, cy), int(radius * SC), (0, 0, 255), 1)
    cv2.putText(img, f"#{idx} seed({col},{row})", (6, img.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
    return img


tiles = [tile(i, *f) for i, f in enumerate(failed)]
side = int(2 * HALF * SC)
cols = 4 if per >= 12 else (3 if per >= 6 else 2)
for s in range(0, len(tiles), per):
    chunk = tiles[s:s + per]
    while len(chunk) % cols:
        chunk.append(np.zeros((side, side, 3), np.uint8))
    rows = [np.hstack(chunk[i:i + cols]) for i in range(0, len(chunk), cols)]
    cv2.imwrite(str(out / f"fs_{s // per}.png"), np.vstack(rows))
print(len(tiles), "tiles,", (len(tiles) + per - 1) // per, "sheets")
