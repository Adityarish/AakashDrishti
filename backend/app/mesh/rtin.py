"""Adaptive RTIN (Martini) terrain meshing with chunked LOD tiles.

The DSM is cut into 1024 px chunks. Every chunk is triangulated three times with growing error
tolerance (LOD0 fine, LOD2 coarse): dense triangles at building edges, sparse on flat ground.
Border skirts hide cracks between chunks that use different LODs. Chunk meshes carry positions,
normals and chunk-local UVs; the optical/overlay textures are supplied by the viewer, so the
same tiles serve every overlay. A separate textured GLB/OBJ is written for GIS/DCC tools.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import trimesh
from PIL import Image
from pymartini import Martini
from scipy import ndimage

CHUNK_PX = 1024
LOD_ERROR_MULTIPLIERS = (1.0, 4.0, 16.0)
LOD0_TRIANGLE_CAP = 160_000
EXPORT_TRIANGLE_CAP = 350_000
MAX_EXPORT_TEXTURE_PX = 4096


@dataclass
class ChunkInfo:
    chunk_id: str
    px_window: tuple[int, int, int, int]  # c0, r0, c1, r1 (inclusive last pixel index)
    bounds: tuple[float, float, float, float]  # minx, minz, maxx, maxz in scene units
    lod_files: list[str]
    lod_triangles: list[int]
    lod_errors: list[float]


@dataclass
class SceneMesh:
    manifest: dict
    export_triangles: int
    export_vertices: int
    chunk_count: int


def _grid_size_for(extent_px: int) -> int:
    k = min(10, max(3, math.ceil(math.log2(max(extent_px, 2)))))
    return 2**k + 1


def _fill_nan(height: np.ndarray) -> np.ndarray:
    if np.isfinite(height).all():
        return height.astype(np.float32)
    mask = ~np.isfinite(height)
    if mask.all():
        return np.zeros_like(height, dtype=np.float32)
    idx = ndimage.distance_transform_edt(mask, return_distances=False, return_indices=True)
    return height[tuple(idx)].astype(np.float32)


def _sample_grid(height: np.ndarray, c0: int, r0: int, c1: int, r1: int, size: int) -> np.ndarray:
    rows = np.linspace(r0, r1, size, dtype=np.float64)
    cols = np.linspace(c0, c1, size, dtype=np.float64)
    rr, cc = np.meshgrid(rows, cols, indexing="ij")
    return ndimage.map_coordinates(height, [rr, cc], order=1, mode="nearest").astype(np.float32)


def rtin_triangulate(grid: np.ndarray, max_error: float) -> tuple[np.ndarray, np.ndarray]:
    size = grid.shape[0]
    martini = Martini(size)
    tile = martini.create_tile(np.ascontiguousarray(grid, dtype=np.float32).ravel())
    vertices, triangles = tile.get_mesh(max_error)
    return np.asarray(vertices).reshape(-1, 2), np.asarray(triangles).reshape(-1, 3)


def _add_skirts(verts_xy: np.ndarray, tris: np.ndarray, positions: np.ndarray, size: int, depth: float):
    """Duplicate border vertices lowered by `depth` and stitch them with quads."""
    last = size - 1
    faces: list[list[int]] = []
    extra: list[np.ndarray] = []
    base = positions.shape[0]

    def edge(mask: np.ndarray, key: int, flip: bool):
        nonlocal base
        idx = np.nonzero(mask)[0]
        if idx.size < 2:
            return
        order = idx[np.argsort(verts_xy[idx, key])]
        lowered = positions[order].copy()
        lowered[:, 1] -= depth
        extra.append(lowered)
        new = np.arange(base, base + order.size)
        base += order.size
        for a in range(order.size - 1):
            v0, v1, n0, n1 = order[a], order[a + 1], new[a], new[a + 1]
            faces.extend([[v0, v1, n0], [v1, n1, n0]] if not flip else [[v1, v0, n0], [n1, v1, n0]])

    x, y = verts_xy[:, 0], verts_xy[:, 1]
    edge(y == 0, 0, False)
    edge(y == last, 0, True)
    edge(x == 0, 1, True)
    edge(x == last, 1, False)
    if not extra:
        return positions, tris
    return np.vstack([positions] + extra), np.vstack([tris, np.array(faces, dtype=np.int64)])


def _chunk_mesh(
    height: np.ndarray,
    window: tuple[int, int, int, int],
    px_m: float,
    center: tuple[float, float],
    vertical_scale: float,
    base_height: float,
    max_error: float,
    skirt_depth: float,
) -> tuple[trimesh.Trimesh, float]:
    c0, r0, c1, r1 = window
    size = _grid_size_for(max(c1 - c0, r1 - r0) + 1)
    grid = _sample_grid(height, c0, r0, c1, r1, size)
    error = max_error
    for _ in range(14):
        verts_xy, tris = rtin_triangulate(grid * vertical_scale, error)
        if len(tris) <= LOD0_TRIANGLE_CAP:
            break
        error *= 1.6
    gx, gy = verts_xy[:, 0].astype(np.int64), verts_xy[:, 1].astype(np.int64)
    cols = c0 + gx * (c1 - c0) / (size - 1)
    rows = r0 + gy * (r1 - r0) / (size - 1)
    positions = np.stack(
        [(cols - center[0]) * px_m, (grid[gy, gx] - base_height) * vertical_scale, (rows - center[1]) * px_m], axis=1
    ).astype(np.float32)
    uv = np.stack([gx / (size - 1), 1.0 - gy / (size - 1)], axis=1).astype(np.float32)

    positions, tris = _add_skirts(verts_xy, tris, positions, size, skirt_depth)
    uv_full = np.vstack([uv, np.zeros((positions.shape[0] - uv.shape[0], 2), np.float32)])
    if positions.shape[0] > uv.shape[0]:
        skirt_source = np.arange(uv.shape[0], positions.shape[0])
        # skirt vertices inherit UVs from their border source by nearest xz
        uv_full[skirt_source] = uv[_nearest_border_index(positions[: uv.shape[0]], positions[skirt_source])]
    mesh = trimesh.Trimesh(vertices=positions, faces=tris, process=False)
    mesh.visual = trimesh.visual.TextureVisuals(uv=uv_full)
    return mesh, error


def _nearest_border_index(source: np.ndarray, query: np.ndarray) -> np.ndarray:
    from scipy.spatial import cKDTree

    tree = cKDTree(source[:, [0, 2]])
    _, index = tree.query(query[:, [0, 2]])
    return index


def build_scene_meshes(
    height: np.ndarray,
    out_dir: Path,
    px_m: float,
    is_metric: bool,
    rgb: Optional[np.ndarray],
    export_texture: Optional[np.ndarray],
) -> tuple[dict, dict]:
    """Write chunk LOD GLBs under out_dir/chunks and a textured terrain_hires.glb/obj.

    Returns (scene_geometry_manifest, export_stats)."""
    h, w = height.shape
    height = _fill_nan(height)
    finite_min, finite_max = float(height.min()), float(height.max())
    span = max(finite_max - finite_min, 1e-9)

    if is_metric:
        vertical_scale = 1.0
        base_height = finite_min
        lod0_error = 0.5
        height_units = "m"
    else:
        vertical_scale = 0.10 * max(w, h) * px_m / span
        base_height = finite_min
        lod0_error = 0.002 * 0.10 * max(w, h) * px_m
        height_units = "relative"

    center = ((w - 1) / 2.0, (h - 1) / 2.0)
    skirt = max(2.0, 0.04 * span * vertical_scale)
    chunks_dir = out_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    chunk_infos: list[ChunkInfo] = []
    rows_n = math.ceil(h / CHUNK_PX)
    cols_n = math.ceil(w / CHUNK_PX)
    for r in range(rows_n):
        for c in range(cols_n):
            c0, r0 = c * CHUNK_PX, r * CHUNK_PX
            c1 = min(c0 + CHUNK_PX, w - 1)
            r1 = min(r0 + CHUNK_PX, h - 1)
            if c1 - c0 < 2 or r1 - r0 < 2:
                continue
            chunk_id = f"r{r}c{c}"
            files, tri_counts, errors = [], [], []
            for lod, multiplier in enumerate(LOD_ERROR_MULTIPLIERS):
                mesh, used_error = _chunk_mesh(
                    height, (c0, r0, c1, r1), px_m, center, vertical_scale, base_height,
                    lod0_error * multiplier, skirt,
                )
                mesh.vertex_normals  # noqa: B018 - force normal computation for the GLB
                name = f"chunks/{chunk_id}_lod{lod}.glb"
                (out_dir / name).write_bytes(mesh.export(file_type="glb"))
                files.append(name)
                tri_counts.append(int(len(mesh.faces)))
                errors.append(float(used_error))
            chunk_infos.append(ChunkInfo(
                chunk_id=chunk_id,
                px_window=(c0, r0, c1, r1),
                bounds=((c0 - center[0]) * px_m, (r0 - center[1]) * px_m, (c1 - center[0]) * px_m, (r1 - center[1]) * px_m),
                lod_files=files, lod_triangles=tri_counts, lod_errors=errors,
            ))

    export_stats = _export_textured(height, out_dir, px_m, center, vertical_scale, base_height, lod0_error, export_texture)

    manifest = {
        "width": w,
        "height": h,
        "pixelSizeM": px_m,
        "metersPerUnit": 1.0,
        "heightUnits": height_units,
        "verticalScale": vertical_scale,
        "baseHeight": base_height,
        "heightRange": [finite_min, finite_max],
        "worldSize": [w * px_m, h * px_m],
        "chunks": [
            {"id": ci.chunk_id, "window": list(ci.px_window), "bounds": list(ci.bounds), "lods": ci.lod_files,
             "triangles": ci.lod_triangles, "errors": ci.lod_errors}
            for ci in chunk_infos
        ],
    }
    return manifest, export_stats


def _export_textured(height, out_dir, px_m, center, vertical_scale, base_height, lod0_error, texture) -> dict:
    h, w = height.shape
    size = 2 ** min(12, math.ceil(math.log2(max(w, h, 2)))) + 1
    grid = _sample_grid(height, 0, 0, w - 1, h - 1, size)
    error = max(lod0_error, 1e-6)
    for _ in range(40):
        verts_xy, tris = rtin_triangulate(grid * vertical_scale, error)
        if len(tris) <= EXPORT_TRIANGLE_CAP:
            break
        error *= 1.4
    gx, gy = verts_xy[:, 0].astype(np.int64), verts_xy[:, 1].astype(np.int64)
    cols = gx * (w - 1) / (size - 1)
    rows = gy * (h - 1) / (size - 1)
    positions = np.stack(
        [(cols - center[0]) * px_m, (grid[gy, gx] - base_height) * vertical_scale, (rows - center[1]) * px_m], axis=1
    ).astype(np.float32)
    uv = np.stack([gx / (size - 1), 1.0 - gy / (size - 1)], axis=1).astype(np.float32)

    image = None
    if texture is not None:
        tex = texture
        longest = max(tex.shape[:2])
        if longest > MAX_EXPORT_TEXTURE_PX:
            scale = MAX_EXPORT_TEXTURE_PX / longest
            tex = cv2.resize(tex, (int(tex.shape[1] * scale), int(tex.shape[0] * scale)), interpolation=cv2.INTER_AREA)
        image = Image.fromarray(tex)

    if image is not None:
        material = trimesh.visual.material.PBRMaterial(baseColorTexture=image, metallicFactor=0.0, roughnessFactor=1.0)
        visual = trimesh.visual.TextureVisuals(uv=uv, material=material)
    else:
        visual = trimesh.visual.TextureVisuals(uv=uv)
    mesh = trimesh.Trimesh(vertices=positions, faces=tris, visual=visual, process=False)
    (out_dir / "terrain_hires.glb").write_bytes(mesh.export(file_type="glb"))

    obj_dir = out_dir / "terrain_obj"
    obj_dir.mkdir(exist_ok=True)
    try:
        mesh.export(str(obj_dir / "terrain.obj"), file_type="obj")
    except Exception:  # noqa: BLE001
        obj_lines = [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in positions]
        obj_lines += [f"vt {u:.5f} {v:.5f}" for u, v in uv]
        obj_lines += [f"f {a + 1}/{a + 1} {b + 1}/{b + 1} {c + 1}/{c + 1}" for a, b, c in tris]
        (obj_dir / "terrain.obj").write_text("\n".join(obj_lines), encoding="utf-8")
    return {"vertices": int(len(positions)), "triangles": int(len(tris)), "max_error": float(error)}
