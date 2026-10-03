"""Run the full pipeline in-process on one image and print the live step log.

Usage: python scripts/run_local.py <image> [--no-tta] [--no-ensemble] [--gsd 0.5] [--sun-el 40] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.jobs.models import JobState, RunOptions  # noqa: E402
from app.jobs.store import JobStore  # noqa: E402
from app.pipeline.run import execute_pipeline  # noqa: E402


def _be_gentle() -> None:
    """Keep the desktop responsive: below-normal priority and a small torch thread pool."""
    import ctypes
    import os

    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x00004000)
    import torch

    torch.set_num_threads(int(os.environ.get("RUN_THREADS", "4")))


def main() -> None:
    _be_gentle()
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--no-tta", action="store_true")
    parser.add_argument("--no-ensemble", action="store_true")
    parser.add_argument("--gsd", type=float)
    parser.add_argument("--sun-el", type=float)
    parser.add_argument("--sun-az", type=float)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    settings = get_settings()
    out_dir = Path(args.out) if args.out else settings.output_dir_path
    store = JobStore(out_dir)
    job_id = uuid.uuid4().hex
    src = Path(args.image)
    stored = store.job_dir(job_id) / f"source{src.suffix.lower()}"
    shutil.copyfile(src, stored)
    options = RunOptions(tta=not args.no_tta, ensemble=not args.no_ensemble, gsd_m=args.gsd,
                         sun_elevation_deg=args.sun_el, sun_azimuth_deg=args.sun_az)
    job = JobState(job_id=job_id, source_filename=src.name, stored_path=str(stored), options=options)
    store.create(job)
    started = time.time()
    execute_pipeline(job_id, store, settings)
    job = store.get(job_id)
    for line in job.logs:
        print(f"[{line.level:5}] {line.step or '-':11} {line.msg}")
    print("stage:", job.stage, "error:", job.error, "seconds:", round(time.time() - started, 1))
    print("job_id:", job_id)
    if job.stage == "READY":
        meta = json.loads((store.job_dir(job_id) / "metadata.json").read_text())
        keys = ["dsm_kind", "calibration_scale", "calibration_sources", "buildings_count", "height_range", "timings", "pixels_per_second"]
        print(json.dumps({k: meta.get(k) for k in keys}, indent=2))


if __name__ == "__main__":
    main()
