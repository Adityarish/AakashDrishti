"""Scenario bundles for the Unity WebGL viewer.

The prebuilt viewer loads `<base>/unity_scene.json` and paints its `disaster_zones` polygons (three levels:
low / medium / high) onto the terrain. A scenario is therefore shown in 3D by writing a copy of the job's
scene file whose zones are the scenario result (flood depth, blast bands, landing sites, drop reach) and
pointing the viewer at that copy. The heightmap and texture are linked (or copied) next to it because the
viewer resolves every file relative to the scene file's folder.

Zone coordinates follow app/export/unity.py: metres, x = east, z = north, origin at the terrain's
bottom-left corner.
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

BUNDLE_DIR = "unity_scenarios"
MAX_BUNDLES = 40
MAX_POLYGONS = 400
_SLUG = re.compile(r"[^a-z0-9_.-]+")

LEVEL_COLORS = {"low": "#ffeb33", "medium": "#ff8c1a", "high": "#e61a1a"}


def slugify(text: str) -> str:
    return _SLUG.sub("_", text.lower()).strip("_")[:80] or "scenario"


class Zones:
    """Accumulates zone polygons in pixel space; converted to scene metres on write."""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, kind: str, level: str, polygon_px: list[tuple[float, float]]) -> None:
        if len(polygon_px) >= 3:
            self.items.append({"type": kind, "level": level, "polygon_px": polygon_px})

    def add_disc(self, kind: str, level: str, col: float, row: float, radius_px: float, segments: int = 48) -> None:
        radius_px = max(radius_px, 1.0)
        self.add(kind, level, [(col + radius_px * math.cos(2 * math.pi * i / segments),
                                row + radius_px * math.sin(2 * math.pi * i / segments)) for i in range(segments)])

    def add_ring(self, kind: str, level: str, col: float, row: float, radius_px: float, width_px: float,
                 segments: int = 72) -> None:
        """Thin annulus as one polygon: outer circle, a zero-width slit, then the inner circle backwards
        (the viewer fills polygons even-odd, so the slit cancels out)."""
        outer = max(radius_px + width_px / 2.0, 2.0)
        inner = max(radius_px - width_px / 2.0, 0.5)
        pts = [(col + outer * math.cos(2 * math.pi * i / segments), row + outer * math.sin(2 * math.pi * i / segments))
               for i in range(segments + 1)]
        pts += [(col + inner * math.cos(2 * math.pi * i / segments), row + inner * math.sin(2 * math.pi * i / segments))
                for i in range(segments, -1, -1)]
        self.add(kind, level, pts)

    def add_mask(self, kind: str, level: str, mask: np.ndarray, max_side: int = 768) -> None:
        """Outer contours of a boolean mask, simplified, as zone polygons (holes are filled)."""
        if not mask.any():
            return
        h, w = mask.shape
        step = max(1, math.ceil(max(h, w) / max_side))
        small = mask[::step, ::step].astype(np.uint8) if step > 1 else mask.astype(np.uint8)
        contours, _ = cv2.findContours(small, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        contours = sorted(contours, key=cv2.contourArea, reverse=True)[:MAX_POLYGONS]
        for contour in contours:
            if cv2.contourArea(contour) < 2.0:
                continue
            approx = cv2.approxPolyDP(contour, 0.75, True)
            if len(approx) < 3:
                continue
            # a contour point is a cell index; map it to the cell centre in full-resolution pixel space
            self.add(kind, level, [((float(p[0][0]) + 0.5) * step, (float(p[0][1]) + 0.5) * step) for p in approx])


def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def _prune(root: Path) -> None:
    bundles = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime)
    for old in bundles[:-MAX_BUNDLES]:
        shutil.rmtree(old, ignore_errors=True)


def write_bundle(job_dir: Path, job_id: str, slug: str, zones: Zones, shape: tuple[int, int],
                 scenario: Optional[dict] = None) -> dict:
    """Write the scenario scene next to the job's own and return {"job_param", "zones"}.

    `job_param` is what the viewer takes as its `job` argument: it builds
    `<api>/api/pipeline/output/<job_param URL-encoded>/unity_scene.json`, which the backend resolves to
    `<job>/unity_scenarios/<slug>/unity_scene.json`.
    """
    base_file = job_dir / "unity_scene.json"
    if not base_file.is_file():
        raise FileNotFoundError("This scene has no Unity bundle (it predates the 3D viewer export). Re-run it to view scenarios in 3D.")
    base = json.loads(base_file.read_text(encoding="utf-8"))

    size_x = float(base["world_size_m"]["x"])
    size_z = float(base["world_size_m"]["z"])
    src_h, src_w = shape

    def to_scene(col: float, row: float) -> list[float]:
        return [round(min(max(col, 0.0), src_w) / src_w * size_x, 3), round((src_h - min(max(row, 0.0), src_h)) / src_h * size_z, 3)]

    zone_out = [{"id": i, "type": z["type"], "level": z["level"], "polygon": [to_scene(c, r) for c, r in z["polygon_px"]]}
                for i, z in enumerate(zones.items, start=1)]

    scene = dict(base)
    scene["disaster_zones"] = zone_out
    if scenario:
        scene["scenario"] = scenario

    root = job_dir / BUNDLE_DIR
    root.mkdir(exist_ok=True)
    target = root / slug
    target.mkdir(exist_ok=True)
    _link_or_copy(job_dir / base["heightmap"]["file"], target / base["heightmap"]["file"])
    texture = (base.get("texture") or {}).get("file")
    if texture and (job_dir / texture).is_file():
        _link_or_copy(job_dir / texture, target / texture)
    (target / "unity_scene.json").write_text(json.dumps(scene), encoding="utf-8")
    _prune(root)
    return {"job_param": f"{job_id}/{BUNDLE_DIR}/{slug}", "zones": len(zone_out)}
