"""DELETE /api/pipeline/{job_id}: removes finished jobs, refuses running ones, 404s unknown ones."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_job_store
from app.api.routes_pipeline import router
from app.auth.service import Principal, get_principal
from app.jobs.models import JobStage, JobState
from app.jobs.store import JobStore


@pytest.fixture
def client_and_store(tmp_path):
    store = JobStore(tmp_path)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_job_store] = lambda: store
    app.dependency_overrides[get_principal] = lambda: Principal(email="t@example.com", role="analyst")
    return TestClient(app), store


def _make(store: JobStore, stage: JobStage) -> JobState:
    return store.create(JobState(source_filename="x.png", stored_path="x.png", stage=stage))


def test_delete_ready_job(client_and_store):
    client, store = client_and_store
    job = _make(store, JobStage.READY)
    assert client.delete(f"/api/pipeline/{job.job_id}").status_code == 204
    assert client.get(f"/api/pipeline/{job.job_id}").status_code == 404


def test_delete_running_job_is_refused(client_and_store):
    client, store = client_and_store
    job = _make(store, JobStage.DEPTH)
    assert client.delete(f"/api/pipeline/{job.job_id}").status_code == 409
    assert (store.job_dir(job.job_id) / "job.json").exists()


def test_delete_unknown_job(client_and_store):
    client, _ = client_and_store
    assert client.delete("/api/pipeline/nope").status_code == 404
