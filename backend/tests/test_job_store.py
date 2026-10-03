"""JobStore persistence: create / reload from disk / list / delete."""

from __future__ import annotations

from app.jobs.models import JobState
from app.jobs.store import JobNotFoundError, JobStore

import pytest


def _job(name: str = "a.png") -> JobState:
    return JobState(source_filename=name, stored_path=name)


def test_create_persists_and_reloads_from_disk(tmp_path):
    store = JobStore(tmp_path)
    job = store.create(_job())
    assert (tmp_path / job.job_id / "job.json").exists()

    fresh = JobStore(tmp_path)  # simulates a process restart
    assert fresh.get(job.job_id).source_filename == "a.png"


def test_list_all_is_most_recent_first_and_skips_corrupt_files(tmp_path):
    store = JobStore(tmp_path)
    first = store.create(_job("first.png"))
    second = store.create(_job("second.png"))
    store.update(second)  # bumps updated_at

    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "job.json").write_text("{not json", encoding="utf-8")

    ids = [j.job_id for j in JobStore(tmp_path).list_all()]
    assert ids == [second.job_id, first.job_id]


def test_delete_removes_memory_and_disk(tmp_path):
    store = JobStore(tmp_path)
    job = store.create(_job())
    store.delete(job.job_id)

    assert not (tmp_path / job.job_id).exists()
    with pytest.raises(JobNotFoundError):
        store.get(job.job_id)
