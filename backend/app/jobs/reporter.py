"""Live progress reporter used by the pipeline. Every call persists to the JobStore, so
polling and SSE clients always see real state (FR-47). Log lines are real pipeline events."""

from __future__ import annotations

import time
from typing import Optional

from app.core.logging import get_logger
from app.jobs.models import STEP_DEFINITIONS, JobStage, JobState, LogLine
from app.jobs.store import JobStore

logger = get_logger(__name__)

MAX_LOG_LINES = 600
_STAGE_BY_STEP = {key: stage for key, _label, _weight, stage in STEP_DEFINITIONS}


class JobCancelled(RuntimeError):
    """Raised inside the pipeline when the user cancels a running job."""


class JobReporter:
    def __init__(self, store: JobStore, job: JobState) -> None:
        self._store = store
        self.job = job
        self._last_flush = 0.0

    def _step(self, key: str):
        for step in self.job.steps:
            if step.key == key:
                return step
        raise KeyError(key)

    def _flush(self, force: bool = True) -> None:
        now = time.time()
        if not force and now - self._last_flush < 0.25:
            return
        self._last_flush = now
        self._store.update(self.job)

    def log(self, msg: str, level: str = "info", step: Optional[str] = None) -> None:
        log_fn = logger.warning if level == "warn" else logger.error if level == "error" else logger.info
        log_fn("[%s] %s", self.job.job_id[:8], msg)
        self.job.logs.append(LogLine(t=time.time(), level=level, step=step, msg=msg))  # type: ignore[arg-type]
        if len(self.job.logs) > MAX_LOG_LINES:
            del self.job.logs[: len(self.job.logs) - MAX_LOG_LINES]
        self._flush(force=False)

    def check_cancel(self) -> None:
        fresh = self._store.get(self.job.job_id)
        if fresh.cancel_requested:
            raise JobCancelled("Job cancelled by user")

    def start(self, key: str, detail: Optional[str] = None) -> None:
        self.check_cancel()
        step = self._step(key)
        step.status = "running"
        step.progress = 0.0
        step.started_at = time.time()
        step.detail = detail
        self.job.stage = _STAGE_BY_STEP.get(key, self.job.stage)
        self.log(detail or f"{step.label} started", step=key)
        self._flush()

    def progress(self, key: str, pct: float, detail: Optional[str] = None) -> None:
        step = self._step(key)
        step.progress = float(max(0.0, min(100.0, pct)))
        if detail is not None:
            step.detail = detail
        self._flush(force=False)

    def done(self, key: str, detail: Optional[str] = None) -> None:
        step = self._step(key)
        step.status = "done"
        step.progress = 100.0
        step.ended_at = time.time()
        if detail is not None:
            step.detail = detail
            self.log(detail, step=key)
        self._flush()

    def skip(self, key: str, reason: str) -> None:
        step = self._step(key)
        step.status = "skipped"
        step.progress = 100.0
        step.detail = reason
        step.ended_at = time.time()
        self.log(f"{step.label} skipped: {reason}", level="warn", step=key)
        self._flush()

    def fail(self, key: Optional[str], message: str) -> None:
        if key is not None:
            step = self._step(key)
            step.status = "failed"
            step.detail = message
            step.ended_at = time.time()
        self.log(message, level="error", step=key)
        self._flush()

    def set_stage(self, stage: JobStage) -> None:
        self.job.stage = stage
        self._flush()
