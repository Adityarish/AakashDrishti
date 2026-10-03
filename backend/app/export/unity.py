"""Unity WebGL scene bundle: heightmap.r16 + texture.jpg + unity_scene.json.

Contract consumed by the Unity viewer (all coordinates in scene metres; x = east, z = north,
origin at the terrain's bottom-left corner):

- heightmap.r16   raw little-endian uint16, row-major, first row = NORTH edge.
                  height_m = min_m + (v / 65535) * (max_m - min_m)
                  (raw bytes on purpose: Texture2D.LoadImage would truncate a 16-bit PNG to 8-bit).
- texture.jpg     the uploaded RGB image, capped at `max_texture_dim`.
- unity_scene.json  sizes, height range, buildings, disaster zones, objects and trees (schema below).

  buildings[]  {id, height_m, footprint[[x,z]..], color_rgb}      roof colour = mean photo colour in the footprint
  objects[]    {id, label, kind, center[x,z], yaw_deg, size_m{length,width,height}, color_rgb, base_m, ...}
               kind: vehicle | truck | tank | pool | slab | aircraft | ship   (yaw = CCW from east toward north)
  trees[]      {id, position[x,z], height_m, crown_radius_m, color_rgb, base_m}
  refinement   counts of what was filtered/derived (see app/export/scene_assets.py)

Horizontal scale: GeoTIFF resolution when the input is georeferenced, otherwise an *assumed*
ground sample distance (reported in `horizontal_scale_source`) -- never presented as measured.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np
import rasterio

from app.export.scene_assets import build_objects, build_trees, classify_buildings
from app.input.detect import GeoMetadata
from app.mesh.generate import _geo_pixel_spacing_meters

HEIGHTMAP_FILE = "heightmap.r16"
TEXTURE_FILE = "texture.jpg"
SCENE_FILE = "unity_scene.json"
MIN_BUILDING_HEIGHT_M = 0.5


def _heightmap_grid(dsm_height: np.ndarray, max_dim: int) -> np.ndarray:
    """Area-downsample to <= max_dim on the long side; NoData is filled with the minimum."""
    finite = np.isfinite(dsm_height)
    if not finite.any():
        raise ValueError("DSM has no finite pixels; cannot export a heightmap")
    filled = np.where(finite, dsm_height, float(dsm_height[finite].min())).astype(np.float32)
    h, w = filled.shape
    scale = min(1.0, max_dim / max(h, w))
    if scale < 1.0:
        filled = cv2.resize(filled, (max(2, round(w * scale)), max(2, round(h * scale))), interpolation=cv2.INTER_AREA)
    return filled


def _building_roof_color(rgb_image: np.ndarray, footprint: list) -> list[int]:
    """Mean RGB of the source photo inside a building's footprint (its real rooftop colour).

    The Unity viewer previously drew every building as the same flat off-white box regardless of
    its real roof colour -- on a scene full of dark asphalt/tar roofs that reads as "way more
    white building infrastructure than the photo", not an accuracy problem with the footprints
    themselves. One mean colour per building (not a full texture) keeps the combined-mesh,
    one-draw-call design (see the Unity project's BuildingMeshBuilder) while making each box match
    what is actually on the roof.

    Works on the footprint's own bounding box: a full-image mask per building allocated hundreds of MiB each
    on very large scenes (and MemoryError'd on a 183-megapixel one).
    """
    h, w = rgb_image.shape[:2]
    pts = np.round(np.asarray(footprint, dtype=np.float64)).astype(np.int32)
    x0, y0 = max(0, int(pts[:, 0].min())), max(0, int(pts[:, 1].min()))
    x1, y1 = min(w, int(pts[:, 0].max()) + 1), min(h, int(pts[:, 1].max()) + 1)
    if x1 <= x0 or y1 <= y0:
        return [214, 214, 204]
    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(mask, [pts - [x0, y0]], 1)
    selected = mask.astype(bool)
    if not selected.any():
        return [214, 214, 204]  # same neutral off-white the viewer used before, as a fallback
    mean = rgb_image[y0:y1, x0:x1][selected].reshape(-1, 3).mean(axis=0)
    return [int(round(c)) for c in mean]


MAX_ANALYSIS_DIM = 4096   # longest side used for building/tree/vehicle refinement; larger scenes are analysed downscaled


def _downscaled_inputs(rgb, ndsm, terrain, labels, factor):
    """Area-downsample the rasters used by scene_assets so full-resolution temporaries never exist."""
    h, w = rgb.shape[:2]
    size = (max(2, w // factor), max(2, h // factor))
    rgb_s = cv2.resize(rgb, size, interpolation=cv2.INTER_AREA)
    ndsm_s = cv2.resize(np.nan_to_num(ndsm).astype(np.float32), size, interpolation=cv2.INTER_AREA)
    terrain_s = None if terrain is None else cv2.resize(np.nan_to_num(terrain).astype(np.float32), size, interpolation=cv2.INTER_AREA)
    labels_s = None if labels is None else cv2.resize(labels, size, interpolation=cv2.INTER_NEAREST)
    return rgb_s, ndsm_s, terrain_s, labels_s


def _scaled(points, factor):
    return [[x / factor, y / factor] for x, y in points]


def export_unity_bundle(
    out_dir: Path,
    job_id: str,
    dsm_height: np.ndarray,
    rgb_image: np.ndarray,
    geo: Optional[GeoMetadata],
    dsm_is_metric: bool,
    buildings: list[dict[str, Any]],
    zones: list[dict[str, Any]],
    assumed_gsd_m: float,
    objects: Optional[list[dict[str, Any]]] = None,
    ndsm: Optional[np.ndarray] = None,
    terrain: Optional[np.ndarray] = None,
    labels: Optional[np.ndarray] = None,
    max_heightmap_dim: int = 512,
    max_texture_dim: int = 2048,
) -> dict[str, Any]:
    """Write the bundle into `out_dir` and return the scene dict (also written as JSON)."""
    grid = _heightmap_grid(dsm_height, max_heightmap_dim)
    rows, cols = grid.shape
    min_m, max_m = float(grid.min()), float(grid.max())
    if max_m - min_m < 1e-3:
        max_m = min_m + 1e-3

    quantised = np.round((grid - min_m) / (max_m - min_m) * 65535.0).astype("<u2")
    (out_dir / HEIGHTMAP_FILE).write_bytes(quantised.tobytes())

    src_h, src_w = dsm_height.shape
    if geo is not None:
        dx, dz = _geo_pixel_spacing_meters(geo)
        scale_source = "geotiff"
    else:
        dx = dz = assumed_gsd_m
        scale_source = "assumed_gsd"
    size_x, size_z = src_w * abs(dx), src_h * abs(dz)

    tex_h, tex_w = rgb_image.shape[:2]
    tex_scale = min(1.0, max_texture_dim / max(tex_h, tex_w))
    texture = rgb_image
    if tex_scale < 1.0:
        texture = cv2.resize(rgb_image, (round(tex_w * tex_scale), round(tex_h * tex_scale)), interpolation=cv2.INTER_AREA)
    ok, jpg = cv2.imencode(".jpg", cv2.cvtColor(texture, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise RuntimeError("Failed to encode terrain texture as JPEG")
    (out_dir / TEXTURE_FILE).write_bytes(jpg.tobytes())

    def px_to_scene(col: float, row: float) -> list[float]:
        return [round(col / src_w * size_x, 3), round((src_h - row) / src_h * size_z, 3)]

    # Drop footprints that are really vegetation or parked-car clusters (they would be drawn as white
    # blocks) and turn the vegetation ones into trees; see app/export/scene_assets.py.
    detections = objects or []
    refinement: dict[str, Any] = {}
    tree_masks: list[np.ndarray] = []
    factor = max(1, -(-max(src_h, src_w) // MAX_ANALYSIS_DIM))   # ceil
    a_rgb, a_ndsm, a_terrain, a_labels = rgb_image, ndsm, terrain, labels
    if ndsm is not None and factor > 1:
        a_rgb, a_ndsm, a_terrain, a_labels = _downscaled_inputs(rgb_image, ndsm, terrain, labels, factor)
    a_h, a_w = a_rgb.shape[:2]

    def a_to_scene(col: float, row: float) -> list[float]:      # coordinates of the analysis rasters -> scene metres
        return px_to_scene(col * factor, row * factor)

    def scaled_building(b: dict) -> dict:
        return {**b, "footprint": _scaled(b.get("footprint") or [], factor)} if factor > 1 else b

    def scaled_object(o: dict) -> dict:
        if factor == 1:
            return o
        return {**o, "polygon": _scaled(o.get("polygon") or [], factor), "center_px": [o["center_px"][0] / factor, o["center_px"][1] / factor]}

    if ndsm is not None:
        scaled_buildings = [scaled_building(b) for b in buildings]
        kept_scaled, tree_masks, refinement = classify_buildings(scaled_buildings, a_rgb, a_labels, [scaled_object(o) for o in detections])
        kept_ids = {b["id"] for b in kept_scaled}
        buildings = [b for b in buildings if b["id"] in kept_ids]

    building_out = []
    for b in buildings:
        height = b.get("height_m")
        footprint = b.get("footprint") or []
        if height is None or height < MIN_BUILDING_HEIGHT_M or len(footprint) < 3:
            continue
        building_out.append(
            {
                "id": b["id"],
                "height_m": round(float(height), 2),
                "footprint": [px_to_scene(x, y) for x, y in footprint],
                "color_rgb": _building_roof_color(rgb_image, footprint),
            }
        )

    to_pixel = ~rasterio.Affine(*geo.transform) if geo is not None else None
    zone_out = []
    for i, z in enumerate(zones, start=1):
        geometry = z.get("geometry") or {}
        if geometry.get("type") != "Polygon" or not geometry.get("coordinates"):
            continue
        ring = geometry["coordinates"][0]
        if to_pixel is not None:  # zones carry map coordinates for georeferenced input
            ring = [to_pixel * (x, y) for x, y in ring]
        zone_out.append(
            {
                "id": i,
                "type": z.get("type"),
                "level": z.get("risk_level"),  # "low" | "medium" | "high" | null
                "polygon": [px_to_scene(x, y) for x, y in ring],
            }
        )

    # Detected aerial objects, as sized/oriented/coloured shapes. `surface_elevation` is the object's own
    # elevation in the height field; `height_above_ground` is only meaningful where `height_reliable` is
    # true -- a car is below this height model's noise floor (see app/detect/objects.py).
    if ndsm is not None:
        object_out = build_objects([scaled_object(o) for o in detections], a_rgb, a_terrain, (a_h, a_w), (size_x, size_z), a_to_scene)
        px_m = size_x / a_w
        trees = build_trees(a_rgb, a_ndsm, a_terrain, a_labels, tree_masks, px_m, dsm_is_metric, a_to_scene,
                            building_footprints=[_scaled(b["footprint"], factor) for b in buildings if b.get("footprint")])
        refinement.update({"vehicles_and_objects": len(object_out), "trees": len(trees)})
    else:  # callers that cannot supply the analysis rasters keep the plain detection list
        object_out = []
        for obj in detections:
            polygon = obj.get("polygon") or []
            if len(polygon) < 3:
                continue
            object_out.append(
                {
                    "id": obj["id"],
                    "label": obj.get("label", "object"),
                    "confidence": obj.get("confidence"),
                    "polygon": [px_to_scene(x, y) for x, y in polygon],
                    "center": px_to_scene(obj["center_px"][0], obj["center_px"][1]),
                    "surface_elevation": obj.get("surface_elevation"),
                    "terrain_elevation": obj.get("terrain_elevation"),
                    "height_above_ground": obj.get("height_above_ground"),
                    "height_reliable": bool(obj.get("height_reliable")),
                }
            )
        trees = []

    scene = {
        "job_id": job_id,
        "heightmap": {"file": HEIGHTMAP_FILE, "width": cols, "height": rows, "min_m": min_m, "max_m": max_m},
        "texture": {"file": TEXTURE_FILE},
        "world_size_m": {"x": round(size_x, 3), "z": round(size_z, 3)},
        "is_metric": dsm_is_metric,
        "horizontal_scale_source": scale_source,
        "buildings": building_out,
        "disaster_zones": zone_out,
        "objects": object_out,
        "trees": trees,
        "refinement": refinement,
    }
    (out_dir / SCENE_FILE).write_text(json.dumps(scene, indent=2), encoding="utf-8")
    return scene
