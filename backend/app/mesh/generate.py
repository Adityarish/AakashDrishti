"""Convert the real DSM/rDSM raster + the user's uploaded RGB image into a
textured terrain mesh, exported as a browser-ready GLB.

FR-8: terrain mesh + RGB texture.

Method:

1. **Downsample the DSM grid** (not the texture) to a browser-friendly vertex
   count via block-averaging (`nanmean` over non-overlapping blocks), which
   respects NoData (a block that is entirely NoData stays NoData) and keeps
   structure better than nearest-neighbor decimation.
2. **Horizontal spacing.** If the input was georeferenced, real-world pixel
   spacing is derived from `geo.resolution` (converted from degrees to
   metres for geographic CRSs via a standard latitude-scaled approximation;
   assumed already in metres for projected CRSs). Non-georeferenced input
   has no real horizontal scale, so spacing falls back to arbitrary
   normalized scene units.
3. **Vertical scale.** A metric (SRTM-calibrated) DSM is plotted in real
   metres at the same horizontal scale (true 1:1 relief) with a documented,
   fixed vertical exaggeration for legibility. A relative (uncalibrated)
   DSM has no real units at all, so it is normalized to a fraction of the
   horizontal extent -- this is a visualization convenience, not a claim of
   accuracy (see PRD.md Section 11 / CLAUDE.md Section 6).
4. **Triangulation.** A quad is only triangulated when all four corner
   vertices are valid (finite); this avoids stretching triangles across
   NoData gaps.
5. **Texture.** The user's actual uploaded RGB image (resized to a capped
   texture resolution, independent of the (coarser) mesh grid resolution)
   is embedded directly into the GLB via `trimesh`'s PBR material.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
import trimesh
from PIL import Image

from app.input.detect import GeoMetadata

DEFAULT_MAX_GRID_DIM = 256
DEFAULT_MAX_TEXTURE_DIM = 1024
RELATIVE_VERTICAL_FRACTION = 0.25  # relative DSM: elevation range -> this fraction of scene width
METRIC_VERTICAL_EXAGGERATION = 2.0  # calibrated DSM: real metres, mildly exaggerated for legibility


class MeshGenerationError(RuntimeError):
    """Raised when a real mesh cannot be produced from the given DSM/image."""


@dataclass
class MeshResult:
    glb_bytes: bytes
    vertex_count: int
    triangle_count: int
    grid_rows: int
    grid_cols: int
    downsample_factor: int
    elevation_min: float
    elevation_max: float
    texture_width: int
    texture_height: int
    horizontal_spacing_x: float
    horizontal_spacing_z: float
    spacing_units: str  # "meters" | "scene-units"
    vertical_exaggeration: float


def _block_downsample_nanmean(arr: np.ndarray, factor: int) -> np.ndarray:
    if factor <= 1:
        return arr
    h, w = arr.shape
    h2, w2 = h // factor, w // factor
    if h2 < 2 or w2 < 2:
        return arr
    trimmed = arr[: h2 * factor, : w2 * factor]
    reshaped = trimmed.reshape(h2, factor, w2, factor)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Mean of empty slice")
        return np.nanmean(reshaped, axis=(1, 3)).astype(np.float32)


def _geo_pixel_spacing_meters(geo: GeoMetadata) -> tuple[float, float]:
    """Approximate real-world (dx, dz) pixel spacing in meters.

    For geographic CRSs (degrees, e.g. EPSG:4326) this uses the standard
    WGS84-sphere approximation (111,320 m/degree latitude, scaled by
    cos(latitude) for longitude). For projected CRSs (units already meters,
    e.g. most UTM zones) the resolution is used directly. This is a stated
    approximation, not a precise geodesic computation.
    """
    res_x, res_y = geo.resolution
    crs_upper = geo.crs.upper()
    is_geographic = "4326" in crs_upper or "CRS84" in crs_upper or geo.crs.startswith("+proj=longlat")

    if not is_geographic:
        return res_x, res_y

    mean_lat = (geo.bounds[1] + geo.bounds[3]) / 2.0
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(mean_lat))
    return res_x * meters_per_deg_lon, res_y * meters_per_deg_lat


def generate_terrain_mesh(
    dsm_height: np.ndarray,
    rgb_image: np.ndarray,
    geo: Optional[GeoMetadata],
    dsm_is_metric: bool,
    max_grid_dim: int = DEFAULT_MAX_GRID_DIM,
    max_texture_dim: int = DEFAULT_MAX_TEXTURE_DIM,
    assumed_pixel_size_m: Optional[float] = None,
) -> MeshResult:
    """`assumed_pixel_size_m` gives a non-georeferenced but metric DSM (heights in metres) the same
    metres-per-pixel horizontal scale the rest of the pipeline assumed, so relief is not distorted."""
    if dsm_height.ndim != 2:
        raise MeshGenerationError(f"Expected a 2D DSM array, got shape {dsm_height.shape}")

    finite_mask = np.isfinite(dsm_height)
    if finite_mask.sum() < 4:
        raise MeshGenerationError("DSM has fewer than 4 valid (non-NoData) pixels; cannot build a mesh.")

    h, w = dsm_height.shape
    downsample_factor = max(1, math.ceil(max(h, w) / max_grid_dim))
    grid = _block_downsample_nanmean(dsm_height, downsample_factor)
    rows, cols = grid.shape

    valid = np.isfinite(grid)
    if valid.sum() < 4:
        raise MeshGenerationError("DSM has too few valid pixels after downsampling to build a mesh.")

    finite_vals = grid[valid]
    elev_min, elev_max = float(finite_vals.min()), float(finite_vals.max())

    if geo is not None:
        dx, dz = _geo_pixel_spacing_meters(geo)
        dx *= downsample_factor
        dz *= downsample_factor
        spacing_units = "meters"
    elif dsm_is_metric and assumed_pixel_size_m:
        dx = dz = float(assumed_pixel_size_m) * downsample_factor
        spacing_units = "meters"
    else:
        dx, dz = 1.0, 1.0
        spacing_units = "scene-units"

    width_extent = dx * (cols - 1)
    depth_extent = dz * (rows - 1)

    if dsm_is_metric:
        vertical_exaggeration = METRIC_VERTICAL_EXAGGERATION
        elevation_scale = vertical_exaggeration
        elevation_offset = -elev_min * elevation_scale
    else:
        # No real units: normalize elevation range to a fraction of the
        # horizontal extent so relief is visible without claiming accuracy.
        span = max(elev_max - elev_min, 1e-6)
        target_range = RELATIVE_VERTICAL_FRACTION * max(width_extent, depth_extent, 1.0)
        elevation_scale = target_range / span
        vertical_exaggeration = elevation_scale
        elevation_offset = -elev_min * elevation_scale

    # --- Vertex grid (compacted: only valid pixels become vertices) ---
    index_map = -np.ones((rows, cols), dtype=np.int64)
    index_map[valid] = np.arange(int(valid.sum()))

    rr, cc = np.nonzero(valid)
    xs = (cc.astype(np.float32) * dx) - (width_extent / 2.0)
    zs = (rr.astype(np.float32) * dz) - (depth_extent / 2.0)
    ys = grid[rr, cc].astype(np.float32) * elevation_scale + elevation_offset

    vertices = np.stack([xs, ys, zs], axis=1).astype(np.float32)

    # UVs: image row 0 is the top of the image; glTF/OpenGL UV origin is
    # bottom-left, so v = 1 - (row / (rows-1)).
    us = cc.astype(np.float32) / max(cols - 1, 1)
    vs = 1.0 - (rr.astype(np.float32) / max(rows - 1, 1))
    uvs = np.stack([us, vs], axis=1).astype(np.float32)

    # --- Faces: only for quads whose 4 corners are all valid ---
    faces: list[list[int]] = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            i00, i01 = index_map[r, c], index_map[r, c + 1]
            i10, i11 = index_map[r + 1, c], index_map[r + 1, c + 1]
            if i00 < 0 or i01 < 0 or i10 < 0 or i11 < 0:
                continue
            faces.append([i00, i10, i01])
            faces.append([i01, i10, i11])

    if not faces:
        raise MeshGenerationError("No valid quads found (DSM too sparse/fragmented) -- cannot triangulate a mesh.")

    faces_arr = np.array(faces, dtype=np.int64)

    # --- Texture: the user's actual uploaded image, resized independently of mesh grid ---
    tex_h, tex_w = rgb_image.shape[:2]
    tex_scale = min(1.0, max_texture_dim / max(tex_h, tex_w))
    if tex_scale < 1.0:
        texture = cv2.resize(
            rgb_image, (int(tex_w * tex_scale), int(tex_h * tex_scale)), interpolation=cv2.INTER_AREA
        )
    else:
        texture = rgb_image
    texture_image = Image.fromarray(texture)

    material = trimesh.visual.material.PBRMaterial(baseColorTexture=texture_image, metallicFactor=0.0, roughnessFactor=1.0)
    visual = trimesh.visual.TextureVisuals(uv=uvs, material=material)
    mesh = trimesh.Trimesh(vertices=vertices, faces=faces_arr, visual=visual, process=False)

    glb_bytes = mesh.export(file_type="glb")
    if not isinstance(glb_bytes, (bytes, bytearray)):
        raise MeshGenerationError(f"trimesh GLB export returned unexpected type {type(glb_bytes)}")

    return MeshResult(
        glb_bytes=bytes(glb_bytes),
        vertex_count=int(vertices.shape[0]),
        triangle_count=int(faces_arr.shape[0]),
        grid_rows=rows,
        grid_cols=cols,
        downsample_factor=downsample_factor,
        elevation_min=elev_min,
        elevation_max=elev_max,
        texture_width=texture_image.width,
        texture_height=texture_image.height,
        horizontal_spacing_x=dx,
        horizontal_spacing_z=dz,
        spacing_units=spacing_units,
        vertical_exaggeration=vertical_exaggeration,
    )
