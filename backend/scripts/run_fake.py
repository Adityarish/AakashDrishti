"""TEST HARNESS ONLY: run all downstream pipeline stages with GAMUS reference heights (plus noise)
standing in for the network output, so UI/analysis work can proceed without loading torch models.
Outputs go to data/test_outputs; never mix these jobs into the real gallery."""
from __future__ import annotations

import os, sys, uuid
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.depth.da_v2_adapter import TiledDepthResult
from app.depth.pipeline import DepthStackResult
from app.jobs.models import JobState, RunOptions
from app.jobs.store import JobStore
from app.pipeline import run as run_module
from app.samples import registry


def main() -> None:
    sample_id = sys.argv[1] if len(sys.argv) > 1 else "DC_38_25"
    variant = sys.argv[2] if len(sys.argv) > 2 else "geotiff"
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else get_settings().output_dir_path.parent / "test_outputs"
    settings = get_settings()
    sample = registry.get_sample(settings, sample_id)
    store = JobStore(out)
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    stored = registry.write_sample_input(sample, job_dir, variant)
    registry.attach_reference(sample, job_dir)
    agl = np.load(sample.agl_path).astype(np.float32)
    rng = np.random.default_rng(0)

    def fake_stack(rgb, work_dir, **kwargs):
        mean = np.clip(agl + rng.normal(0, 0.25, agl.shape).astype(np.float32), 0, None)
        std = (0.15 + 0.5 * np.abs(np.gradient(agl)[0]) / (agl.max() + 1e-6) * 4).astype(np.float32)
        da = TiledDepthResult(mean=mean, std=std, tile_count=1, tta_variants=8, seconds=0.0, checkpoint_is_height=True)
        return DepthStackResult(da, None, None, "Test harness: reference heights used in place of the network")

    run_module.run_depth_stack = fake_stack
    job = JobState(job_id=job_id, source_filename=f"TEST-{sample_id}.{'tif' if variant == 'geotiff' else 'png'}",
                   stored_path=str(stored), options=RunOptions(), is_sample=True, sample_id=sample_id)
    store.create(job)
    run_module.execute_pipeline(job_id, store, settings)
    job = store.get(job_id)
    for line in job.logs:
        print(f"[{line.level:5}] {line.step or '-':11} {line.msg}")
    print("stage:", job.stage, "error:", job.error, "job:", job_id)


if __name__ == "__main__":
    main()
