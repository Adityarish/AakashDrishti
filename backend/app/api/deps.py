"""Shared FastAPI dependencies: settings and the process-local job store."""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.jobs.store import JobStore


@lru_cache
def get_job_store() -> JobStore:
    settings = get_settings()
    return JobStore(output_dir=settings.output_dir_path)
