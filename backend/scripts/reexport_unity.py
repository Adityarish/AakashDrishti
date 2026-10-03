"""Rebuild a finished job's Unity bundle (unity_scene.json) from its saved outputs, without re-running depth.

Use it after changing app/export/scene_assets.py or the detector settings, or to upgrade an older job:

    python scripts/reexport_unity.py path/to/outputs/<job_id>            # also (re)runs object detection
    python scripts/reexport_unity.py path/to/outputs/<job_id> --no-detect  # keep the job's existing objects.json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.detect.objects import detect_objects  # noqa: E402
from app.export.unity import export_unity_bundle  # noqa: E402
from app.input.detect import GeoMetadata  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("job_dir", type=Path)
    parser.add_argument("--no-detect", action="store_true", help="reuse objects.json instead of running YOLO again")
    args = parser.parse_args()
    job = args.job_dir.resolve()

    meta = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
    arrays = np.load(job / "arrays.npz")
    dsm, ndsm, labels = arrays["dsm"].astype(np.float32), arrays["ndsm"].astype(np.float32), arrays["labels"].astype(np.uint8)
    rgb = cv2.cvtColor(cv2.imread(str(job / "ortho.jpg")), cv2.COLOR_BGR2RGB)
    if rgb.shape[:2] != dsm.shape:
        rgb = cv2.resize(rgb, (dsm.shape[1], dsm.shape[0]), interpolation=cv2.INTER_AREA)

    geo = None
    if meta.get("geo"):
        g = meta["geo"]
        geo = GeoMetadata(crs=g["crs"], transform=tuple(g["transform"]), width=g["width"], height=g["height"],
                          bounds=tuple(g["bounds"]), resolution=tuple(g["resolution"]), nodata=None, band_count=3)
    is_metric = bool(meta.get("dsm_is_metric", False))
    terrain = (dsm - ndsm).astype(np.float32)

    settings = get_settings()
    objects_path = job / "objects.json"
    if args.no_detect and objects_path.is_file():
        payload = json.loads(objects_path.read_text(encoding="utf-8"))
    else:
        result = detect_objects(
            rgb=rgb, dsm=dsm, ndsm=ndsm, terrain=terrain, weights=settings.object_detection_weights_path,
            device_preference=settings.device, conf=settings.object_detection_conf, imgsz=settings.object_detection_imgsz,
            dsm_is_metric=is_metric,
        )
        payload = result.as_payload(meta.get("job_id", job.name), "m" if is_metric else "relative units")
        objects_path.write_text(json.dumps(payload), encoding="utf-8")
        print(f"detection: {result.status}, {len(result.objects)} objects {result.counts}")

    buildings = json.loads((job / "buildings.json").read_text(encoding="utf-8"))["buildings"]
    zones_file = job / "disaster_zones.json"
    zones = json.loads(zones_file.read_text(encoding="utf-8")).get("zones", []) if zones_file.is_file() else []

    # The exporter also writes heightmap.r16 and texture.jpg; export into a scratch folder and copy back ONLY
    # unity_scene.json, so the job's existing (possibly higher-quality) texture and heightmap stay byte-identical.
    with tempfile.TemporaryDirectory() as scratch:
        scene = export_unity_bundle(
            out_dir=Path(scratch), job_id=meta.get("job_id", job.name), dsm_height=dsm, rgb_image=rgb, geo=geo, dsm_is_metric=is_metric,
            buildings=buildings, zones=zones, assumed_gsd_m=settings.assumed_gsd_m, objects=payload.get("objects", []),
            ndsm=ndsm, terrain=terrain, labels=labels,
        )
        shutil.copyfile(Path(scratch) / "unity_scene.json", job / "unity_scene.json")
    print("refinement:", scene["refinement"])
    print(f"wrote {job / 'unity_scene.json'}: {len(scene['buildings'])} buildings, {len(scene['objects'])} objects, {len(scene['trees'])} trees")


if __name__ == "__main__":
    main()
