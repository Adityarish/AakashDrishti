"""Download a handful of real GAMUS test tiles (RGB + AGL height + land-cover) for
local end-to-end testing and the validation-lab demo.

Usage:  python scripts/fetch_gamus_samples.py [count]
Output: data/samples/gamus/<tile_id>_{rgb.png,agl.npy,cls.png}  (gitignored)
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

import h5py
import numpy as np
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT = REPO_ROOT / "data" / "samples" / "gamus"
BASE = "https://huggingface.co/datasets/earthflow/GAMUS/resolve/main"


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        return response.read()


def _list(path: str) -> list[str]:
    url = f"https://huggingface.co/api/datasets/earthflow/GAMUS/tree/main/{path}"
    return [item["path"] for item in json.loads(_get(url))]


def _read_h5(blob: bytes) -> np.ndarray:
    with h5py.File(io.BytesIO(blob), "r") as handle:
        return np.array(handle["image"])


def main() -> None:
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    OUT.mkdir(parents=True, exist_ok=True)
    image_paths = _list("images/test")
    step = max(1, len(image_paths) // count)
    chosen = image_paths[::step][:count]
    for image_path in chosen:
        name = image_path.rsplit("/", 1)[-1]
        stem = name.rsplit("_", 1)[0]
        target = OUT / f"{stem}_rgb.png"
        if target.exists():
            continue
        try:
            rgb = _read_h5(_get(f"{BASE}/{image_path}"))
            agl = _read_h5(_get(f"{BASE}/heights/test/{stem}_AGL.h5"))
            cls = _read_h5(_get(f"{BASE}/classes/test/{stem}_CLS.h5"))
        except Exception as exc:  # noqa: BLE001
            print("skip", stem, exc)
            continue
        Image.fromarray(rgb.astype(np.uint8)).save(target)
        np.save(OUT / f"{stem}_agl.npy", agl.astype(np.float32))
        Image.fromarray(cls.astype(np.uint8)).save(OUT / f"{stem}_cls.png")
        print("saved", stem, rgb.shape, float(np.nanmax(agl)), np.unique(cls))


if __name__ == "__main__":
    main()
