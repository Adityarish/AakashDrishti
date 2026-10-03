"""Aerial object detection + per-object elevation (FR-50).

Runs an oriented-bounding-box detector trained on DOTA (aerial/satellite imagery) over the
optical image, then samples the pipeline's own height arrays inside each detected footprint so
every object carries a real elevation instead of being a flat 2D box.

Why a DOTA-OBB model and not a COCO one: COCO weights are trained on ground-level photographs
and hit the same nadir domain gap the depth backbones do. Measured on three held-out GAMUS tiles,
COCO `yolov8s` found 6/19/5 objects and labelled rooftop clutter "refrigerator" and "tv", while
DOTA `yolov8s-obb` found 300/186/215 vehicles with boxes aligned to the parking rows. DOTA's
classes are also the operationally useful ones here (vehicles, ships, planes, helicopters,
bridges, storage tanks, harbours).

Three height numbers are reported per object and they are NOT equally trustworthy:

- `surface_elevation` -- the median DSM value inside the footprint, i.e. the elevation of this
  object's own surface in the scene's height field. Always meaningful, in whatever units the
  scene uses, and the number to show as "the object's elevation on the map".
- `terrain_elevation` -- the bare ground under the object (median of dsm - ndsm). Only
  informative for a DEM-calibrated `absolute_dsm` scene; in `pseudo_metric` mode the DSM *is*
  height above ground, so this is 0 by construction, not a measurement.
- `height_above_ground` -- the nDSM's own p90 inside the footprint. For a large object (ship,
  aircraft, storage tank) this is meaningful; for a car it is at or below the height model's
  metre-scale vertical noise floor, so it is reported with `height_reliable: false` rather than
  presented as a measurement. Callers must not round-trip it as a measured object height.

`height_reliable` additionally requires the sample to be physically plausible for its class
(CLASS_MAX_PLAUSIBLE_M): a car parked under a tree samples the canopy and would otherwise be
published as "a 7.8 m small vehicle".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import cv2
import numpy as np

from app.core.logging import get_logger
from app.depth.device import cuda_scope

logger = get_logger(__name__)

# Objects at least this tall are above the single-view height model's metre-scale noise floor,
# so their sampled nDSM height is worth reporting as a height rather than as an artefact.
RELIABLE_HEIGHT_M = 2.5
MAX_OBJECTS = 2000

# Upper bound on a physically plausible height for each DOTA class, in metres. A sample above the
# bound means the footprint caught something else -- an overhanging tree, a neighbouring roof, a
# building edge -- not a genuinely tall object, so the height is flagged unreliable instead of
# being reported. Without this, a car parked under a tree is published as "a 7.8 m small vehicle".
# Generous bounds on purpose: this rejects contamination, it does not pretend to be a size prior.
CLASS_MAX_PLAUSIBLE_M: dict[str, float] = {
    # Cars and SUVs top out around 2 m, which is below RELIABLE_HEIGHT_M -- so no small vehicle
    # can ever qualify for a reliable height. That is the honest outcome: a "2.7 m car" is this
    # model's own vertical noise, not a tall car.
    "small vehicle": 2.0,
    "large vehicle": 5.0,
    "ship": 60.0,
    "plane": 25.0,
    "helicopter": 8.0,
    "storage tank": 30.0,
    "bridge": 60.0,
    "harbor": 30.0,
    "roundabout": 2.0,
    "tennis court": 1.0,
    "basketball court": 1.0,
    "ground track field": 1.0,
    "soccer ball field": 1.0,
    "baseball diamond": 1.0,
    "swimming pool": 1.0,
}
DEFAULT_MAX_PLAUSIBLE_M = 100.0


class ObjectDetectionUnavailable(RuntimeError):
    """Raised when ultralytics or the detector weights are not usable."""


@dataclass
class DetectedObject:
    id: int
    label: str
    confidence: float
    polygon: list[list[float]]  # oriented box, 4 x [col, row] in source-image pixels
    center_px: list[float]
    area_px: float
    surface_elevation: Optional[float] = None
    terrain_elevation: Optional[float] = None
    height_above_ground: Optional[float] = None
    height_reliable: bool = False
    lonlat: Optional[list[float]] = None


@dataclass
class DetectionResult:
    objects: list[DetectedObject] = field(default_factory=list)
    status: str = "ok"  # "ok" | "skipped" | "unavailable"
    note: str = ""
    model_name: str = ""
    counts: dict[str, int] = field(default_factory=dict)

    def as_payload(self, job_id: str, unit: str) -> dict[str, Any]:
        return {
            "job_id": job_id,
            "status": self.status,
            "note": self.note,
            "model": self.model_name,
            "count": len(self.objects),
            "counts_by_class": self.counts,
            "height_unit": unit,
            "objects": [
                {
                    "id": o.id,
                    "label": o.label,
                    "confidence": round(o.confidence, 3),
                    "polygon": [[round(x, 1), round(y, 1)] for x, y in o.polygon],
                    "center_px": [round(o.center_px[0], 1), round(o.center_px[1], 1)],
                    "area_px": round(o.area_px, 1),
                    "surface_elevation": None if o.surface_elevation is None else round(o.surface_elevation, 2),
                    "terrain_elevation": None if o.terrain_elevation is None else round(o.terrain_elevation, 2),
                    "height_above_ground": None if o.height_above_ground is None else round(o.height_above_ground, 2),
                    "height_reliable": o.height_reliable,
                    "lonlat": None if o.lonlat is None else [round(o.lonlat[0], 6), round(o.lonlat[1], 6)],
                }
                for o in self.objects
            ],
        }


def _tile_origins(length: int, window: int, overlap: float) -> list[int]:
    if length <= window:
        return [0]
    step = max(1, int(window * (1.0 - overlap)))
    origins = list(range(0, max(1, length - window + 1), step))
    if origins[-1] != length - window:
        origins.append(length - window)
    return origins


def _nms_by_aabb(boxes: np.ndarray, scores: np.ndarray, classes: np.ndarray, iou_threshold: float) -> list[int]:
    """Greedy NMS on axis-aligned boxes, per class. Used only to dedupe tile-overlap repeats."""
    keep: list[int] = []
    for cls in np.unique(classes):
        idx = np.where(classes == cls)[0]
        order = idx[np.argsort(-scores[idx])]
        while order.size:
            current = int(order[0])
            keep.append(current)
            if order.size == 1:
                break
            rest = order[1:]
            xx1 = np.maximum(boxes[current, 0], boxes[rest, 0])
            yy1 = np.maximum(boxes[current, 1], boxes[rest, 1])
            xx2 = np.minimum(boxes[current, 2], boxes[rest, 2])
            yy2 = np.minimum(boxes[current, 3], boxes[rest, 3])
            inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
            area_current = (boxes[current, 2] - boxes[current, 0]) * (boxes[current, 3] - boxes[current, 1])
            area_rest = (boxes[rest, 2] - boxes[rest, 0]) * (boxes[rest, 3] - boxes[rest, 1])
            iou = inter / np.maximum(area_current + area_rest - inter, 1e-6)
            order = rest[iou < iou_threshold]
    return keep


def _run_model(model: Any, rgb: np.ndarray, imgsz: int, overlap: float, conf: float, device: str):
    """Tiled inference. Large images must be tiled: resizing a 4000 px scene down to 1024 px
    shrinks a car to ~3 px and the detector stops seeing it entirely."""
    height, width = rgb.shape[:2]
    polygons: list[np.ndarray] = []
    scores: list[float] = []
    classes: list[int] = []

    for top in _tile_origins(height, min(imgsz, height), overlap):
        for left in _tile_origins(width, min(imgsz, width), overlap):
            tile = rgb[top:top + min(imgsz, height), left:left + min(imgsz, width)]
            result = model.predict(cv2.cvtColor(tile, cv2.COLOR_RGB2BGR), imgsz=imgsz, conf=conf,
                                   verbose=False, device=device)[0]
            obb = getattr(result, "obb", None)
            if obb is None or len(obb) == 0:
                continue
            quads = obb.xyxyxyxy.cpu().numpy().reshape(-1, 4, 2)
            quads[..., 0] += left
            quads[..., 1] += top
            polygons.extend(quads)
            scores.extend(obb.conf.cpu().numpy().tolist())
            classes.extend(obb.cls.cpu().numpy().astype(int).tolist())

    if not polygons:
        return [], [], []

    quads = np.stack(polygons)
    aabb = np.stack([quads[:, :, 0].min(1), quads[:, :, 1].min(1), quads[:, :, 0].max(1), quads[:, :, 1].max(1)], axis=1)
    keep = _nms_by_aabb(aabb, np.asarray(scores), np.asarray(classes), iou_threshold=0.45)
    keep.sort(key=lambda i: -scores[i])
    keep = keep[:MAX_OBJECTS]
    return [quads[i] for i in keep], [scores[i] for i in keep], [classes[i] for i in keep]


def _height_is_reliable(label: str, height: Optional[float], dsm_is_metric: bool) -> bool:
    """True only when a sampled height is worth publishing as a height: the scene is metric, the
    value clears the model's vertical noise floor, and it is still physically plausible for the
    class. Anything else is contamination (an overhanging tree, a neighbouring roof) or noise."""
    if not dsm_is_metric or height is None or height < RELIABLE_HEIGHT_M:
        return False
    return height <= CLASS_MAX_PLAUSIBLE_M.get(label, DEFAULT_MAX_PLAUSIBLE_M)


def _sample_heights(
    quad: np.ndarray, dsm: np.ndarray, ndsm: np.ndarray, terrain: np.ndarray
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """(p90 nDSM, median DSM surface, median terrain) inside one oriented box, on a local crop."""
    h, w = ndsm.shape
    x0, y0 = int(np.floor(quad[:, 0].min())), int(np.floor(quad[:, 1].min()))
    x1, y1 = int(np.ceil(quad[:, 0].max())), int(np.ceil(quad[:, 1].max()))
    x0, y0 = max(0, x0), max(0, y0)
    x1, y1 = min(w, max(x1, x0 + 1)), min(h, max(y1, y0 + 1))
    if x1 <= x0 or y1 <= y0:
        return None, None, None

    mask = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
    cv2.fillPoly(mask, [np.round(quad - [x0, y0]).astype(np.int32)], 1)
    selected = mask.astype(bool)
    if not selected.any():
        return None, None, None

    def _finite(array: np.ndarray) -> np.ndarray:
        values = array[y0:y1, x0:x1][selected]
        return values[np.isfinite(values)]

    object_vals, surface_vals, terrain_vals = _finite(ndsm), _finite(dsm), _finite(terrain)
    height = float(np.percentile(object_vals, 90)) if object_vals.size else None
    surface = float(np.median(surface_vals)) if surface_vals.size else None
    base = float(np.median(terrain_vals)) if terrain_vals.size else None
    return height, surface, base


def detect_objects(
    rgb: np.ndarray,
    dsm: np.ndarray,
    ndsm: np.ndarray,
    terrain: np.ndarray,
    weights: Path,
    device_preference: str = "cuda",
    conf: float = 0.3,
    imgsz: int = 1024,
    overlap: float = 0.2,
    dsm_is_metric: bool = True,
    to_lonlat: Optional[Any] = None,
) -> DetectionResult:
    """Detect aerial objects in `rgb` and attach elevations sampled from `ndsm`/`terrain`.

    Never raises for a missing dependency or missing weights: returns status "unavailable" so the
    pipeline can carry on, matching how building/land-cover analysis degrades.
    """
    try:
        from ultralytics import YOLO
    except ImportError as exc:
        return DetectionResult(status="unavailable", note=f"ultralytics is not installed ({exc}); object detection skipped.")

    if not weights.is_file():
        return DetectionResult(
            status="unavailable",
            note=(f"Detector weights not found at {weights}. Download yolov8s-obb.pt (DOTA) into that path, "
                  "or set OBJECT_DETECTION_WEIGHTS in .env."),
        )

    device = 0 if device_preference == "cuda" else "cpu"
    try:
        import torch

        if device_preference == "cuda" and not torch.cuda.is_available():
            device = "cpu"
    except ImportError:
        device = "cpu"

    with cuda_scope("ObjectDetector"):
        model = YOLO(str(weights))
        names = model.names
        quads, scores, classes = _run_model(model, rgb, imgsz, overlap, conf, device)
        del model

    objects: list[DetectedObject] = []
    for index, (quad, score, cls) in enumerate(zip(quads, scores, classes), start=1):
        height, surface, base = _sample_heights(quad, dsm, ndsm, terrain)
        center = [float(quad[:, 0].mean()), float(quad[:, 1].mean())]
        label = str(names[int(cls)])
        reliable = _height_is_reliable(label, height, dsm_is_metric)
        lonlat = None
        if to_lonlat is not None:
            try:
                point = to_lonlat(center[0], center[1])
                lonlat = [float(point[0]), float(point[1])] if point else None
            except Exception:  # noqa: BLE001 -- a projection failure must not drop the detection
                lonlat = None
        objects.append(DetectedObject(
            id=index, label=label, confidence=float(score),
            polygon=[[float(x), float(y)] for x, y in quad], center_px=center,
            area_px=float(cv2.contourArea(quad.astype(np.float32))),
            surface_elevation=surface, terrain_elevation=base, height_above_ground=height,
            height_reliable=reliable, lonlat=lonlat,
        ))

    counts: dict[str, int] = {}
    for obj in objects:
        counts[obj.label] = counts.get(obj.label, 0) + 1

    flat_terrain = bool(objects) and all(
        o.terrain_elevation is not None and abs(o.terrain_elevation) < 1e-6 for o in objects
    )
    note = (
        f"{len(objects)} object(s) detected by {weights.name} (DOTA aerial classes) at confidence >= {conf:g}. "
        "Elevations are sampled from this scene's own height field. Per-object heights are the nDSM's "
        f"p90 inside the footprint and are only flagged reliable above {RELIABLE_HEIGHT_M:g} m, since smaller "
        "objects sit at or below this single-view height model's vertical noise floor."
    )
    if flat_terrain:
        note += (" This scene has no DEM-derived bare earth, so its surface is already height above ground and "
                 "terrain_elevation is 0 by construction; use surface_elevation.")
    if not dsm_is_metric:
        note += " This scene has no metric scale, so elevations are in relative DSM units."
    return DetectionResult(objects=objects, status="ok", note=note, model_name=weights.name, counts=counts)
