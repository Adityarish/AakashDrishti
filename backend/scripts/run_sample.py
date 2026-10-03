"""Run the real pipeline (actual model inference, not the fake test harness) on a bundled
GAMUS sample, with its ground-truth reference height attached for the validation lab.

Usage: python scripts/run_sample.py <sample_id> [--variant geotiff|png]
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.input.detect import detect_input  # noqa: E402
from app.jobs.models import JobState, RunOptions  # noqa: E402
from app.jobs.store import JobStore  # noqa: E402
from app.pipeline.run import execute_pipeline  # noqa: E402
from app.samples import registry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("sample_id")
    parser.add_argument("--variant", default="geotiff", choices=["geotiff", "png"])
    args = parser.parse_args()

    settings = get_settings()
    sample = registry.get_sample(settings, args.sample_id)
    if sample is None:
        raise SystemExit(f"Unknown sample: {args.sample_id}")

    store = JobStore(settings.output_dir_path)
    job_id = uuid.uuid4().hex
    job_dir = store.job_dir(job_id)
    stored = registry.write_sample_input(sample, job_dir, args.variant)
    registry.attach_reference(sample, job_dir)
    descriptor = detect_input(stored)
    job = JobState(
        job_id=job_id, source_filename=f"{sample.sample_id}.{'tif' if args.variant == 'geotiff' else 'png'}",
        stored_path=str(stored), is_georeferenced=descriptor.is_georeferenced,
        mode="absolute" if descriptor.is_georeferenced else "relative", options=RunOptions(),
        is_sample=True, sample_id=args.sample_id,
    )
    store.create(job)
    execute_pipeline(job_id, store, settings)
    job = store.get(job_id)
    for line in job.logs:
        print(f"[{line.level:5}] {line.step or '-':11} {line.msg}")
    print("stage:", job.stage, "error:", job.error, "job_id:", job_id)

    if job.stage == "READY":
        val_path = job_dir / "validation_lab.json"
        if val_path.is_file():
            print("\n=== Validation lab (vs. real GAMUS ground truth) ===")
            print(json.dumps(json.loads(val_path.read_text()), indent=2))
        else:
            print("\nNo validation_lab.json written.")


if __name__ == "__main__":
    main()
