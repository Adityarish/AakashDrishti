"""Bake the featured demo scene: run the REAL pipeline on real GAMUS tiles, score each against its real
reference heights, and print the results so the best-looking, honestly-measured scene can be shipped.

Usage: python scripts/bake_featured.py <tile_id> [<tile_id> ...] [--install <tile_id>]

--install copies the finished job into backend/demo/featured/ (committed, loaded at server start).
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.analysis.scene import load_scene  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.jobs.models import JobState, RunOptions  # noqa: E402
from app.jobs.store import JobStore  # noqa: E402
from app.samples import registry  # noqa: E402
from app.validation import lab  # noqa: E402

BAKE_DIR = Path(__file__).resolve().parents[2] / "data" / "bake"
FEATURED_DIR = Path(__file__).resolve().parents[1] / "demo" / "featured"


def bake(tile_id: str) -> dict:
    from app.pipeline.run import execute_pipeline

    settings = get_settings()
    sample = registry.get_sample(settings, tile_id)
    store = JobStore(BAKE_DIR)
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    stored = registry.write_sample_input(sample, job_dir, "geotiff")
    registry.attach_reference(sample, job_dir)
    job = JobState(job_id=job_id, source_filename=f"{tile_id}.tif", stored_path=str(stored),
                   options=RunOptions(tta=True, ensemble=False), is_sample=True, sample_id=tile_id)
    store.create(job)
    execute_pipeline(job_id, store, settings)
    job = store.get(job_id)
    if job.stage != "READY":
        return {"tile": tile_id, "error": job.error}
    scene = load_scene(job_dir)
    reference, note = lab.read_reference(job_dir / "sample_reference.npy", scene)
    result = lab.evaluate(scene, reference, "ndsm", job_dir, note)
    g = result["global"]
    return {"tile": tile_id, "job_id": job_id, "rmse": g["rmse"], "mae": g["mae"], "r": g["pearson_r"],
            "landscape": {k: round(v["rmse"], 2) for k, v in result["per_landscape"].items()}}


def install(job_id: str, tile_id: str) -> None:
    src = BAKE_DIR / job_id
    dst = FEATURED_DIR / "job"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("depth_pro_input.png", "*.tmp"))
    meta = {"tile_id": tile_id, "baked_from": job_id, "title": "Featured scene: Washington DC (GAMUS tile)"}
    (FEATURED_DIR / "featured.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    size = sum(p.stat().st_size for p in dst.rglob("*") if p.is_file()) / 1e6
    print(f"installed {tile_id} ({size:.1f} MB) into {FEATURED_DIR}")


if __name__ == "__main__":
    args = sys.argv[1:]
    if "--install" in args:
        i = args.index("--install")
        install(args[i + 1], args[i + 2])
    else:
        for tile in args:
            print(json.dumps(bake(tile)), flush=True)
