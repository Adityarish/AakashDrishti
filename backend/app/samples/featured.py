"""Featured scene: a real pipeline run (real model, real GAMUS reference) baked ahead of time and shipped
in backend/demo/featured so the app has a ready-to-open scene on first launch, offline.

`scripts/bake_featured.py` produces it. The scene is genuine output, so its accuracy numbers are measured;
it is labelled as a pre-processed scene in the UI."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.core.config import Settings, REPO_ROOT
from app.core.logging import get_logger

logger = get_logger(__name__)

FEATURED_ID = "featured-washington-dc"
BUNDLE = REPO_ROOT / "backend" / "demo" / "featured"
DISPLAY_NAME = "Featured - Washington DC (GAMUS tile).tif"


def install_featured_scene(settings: Settings) -> bool:
    src = BUNDLE / "job"
    meta_file = BUNDLE / "featured.json"
    dst = settings.output_dir_path / FEATURED_ID
    if not src.is_dir() or not meta_file.is_file() or dst.exists():
        return False
    old_id = json.loads(meta_file.read_text(encoding="utf-8"))["baked_from"]
    shutil.copytree(src, dst)
    for path in dst.glob("*.json"):
        path.write_text(path.read_text(encoding="utf-8").replace(old_id, FEATURED_ID), encoding="utf-8")
    job_file = dst / "job.json"
    job = json.loads(job_file.read_text(encoding="utf-8"))
    source = next((p for p in dst.glob("source.*")), None)
    job.update({"job_id": FEATURED_ID, "source_filename": DISPLAY_NAME, "stored_path": str(source) if source else ""})
    job["summary"] = {**job.get("summary", {}), "featured": True}
    job["outputs"] = {k: v for k, v in job.get("outputs", {}).items() if (dst / v.rsplit("/", 1)[-1]).exists()}
    job_file.write_text(json.dumps(job, indent=2), encoding="utf-8")
    logger.info("Installed featured scene into %s", dst)
    return True


SITE_ID = "site-denver-7"
SITE_BUNDLE = REPO_ROOT / "backend" / "demo" / "denver7" / "job"


def install_site_scene(settings: Settings) -> bool:
    """Install the hand-verified 7.tif scene (built by scripts/denver7/build_scene.py) as a ready job. Idempotent: an
    existing folder is left alone unless its unity_scene.json is older than the bundle's."""
    if not SITE_BUNDLE.is_dir():
        return False
    dst = settings.output_dir_path / SITE_ID
    marker, installed = SITE_BUNDLE / "job.json", dst / "job.json"
    # reinstall when the bundle was rebuilt (its job.json is always the last file written)
    if installed.exists() and installed.stat().st_mtime >= marker.stat().st_mtime and (dst / "arrays.npz").exists():
        return False
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(SITE_BUNDLE, dst)
    logger.info("Installed site scene into %s", dst)
    return True
