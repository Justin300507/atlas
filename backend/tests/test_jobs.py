import os
import subprocess
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.jobs import (
    cleanup_stale_jobs,
    count_active_jobs,
    create_job,
    get_job,
    try_create_job,
    update_job,
)

BACKEND_DIR = Path(__file__).parent.parent


def _backdate_job(job_id: str, db_path, hours_ago: float) -> None:
    created_at = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("UPDATE jobs SET created_at = ? WHERE id = ?", (created_at, job_id))
        conn.commit()
    finally:
        conn.close()


def test_create_job_returns_queued_record(tmp_path):
    db_path = tmp_path / "jobs.db"

    job_id = create_job("https://github.com/example/example", db_path=db_path)
    record = get_job(job_id, db_path=db_path)

    assert record is not None
    assert record.id == job_id
    assert record.repo_url == "https://github.com/example/example"
    assert record.status == "queued"
    assert record.stage is None
    assert record.markdown is None
    assert record.error is None


def test_get_job_returns_none_for_unknown_id(tmp_path):
    db_path = tmp_path / "jobs.db"
    create_job("https://github.com/example/example", db_path=db_path)

    assert get_job("does-not-exist", db_path=db_path) is None


def test_update_job_updates_only_given_fields(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = create_job("https://github.com/example/example", db_path=db_path)

    update_job(job_id, status="running", stage="cloning_structure", db_path=db_path)
    record = get_job(job_id, db_path=db_path)
    assert record.status == "running"
    assert record.stage == "cloning_structure"
    assert record.markdown is None

    update_job(job_id, stage="parsing", db_path=db_path)
    record = get_job(job_id, db_path=db_path)
    assert record.status == "running"  # unchanged by the second call
    assert record.stage == "parsing"

    update_job(job_id, status="done", markdown="## Report", db_path=db_path)
    record = get_job(job_id, db_path=db_path)
    assert record.status == "done"
    assert record.markdown == "## Report"
    assert record.error is None


def test_update_job_can_record_an_error(tmp_path):
    db_path = tmp_path / "jobs.db"
    job_id = create_job("https://github.com/example/example", db_path=db_path)

    update_job(job_id, status="error", error="Repository clone timed out", db_path=db_path)
    record = get_job(job_id, db_path=db_path)

    assert record.status == "error"
    assert record.error == "Repository clone timed out"


def test_create_job_creates_missing_parent_directories(tmp_path):
    db_path = tmp_path / "nested" / "does" / "not" / "exist" / "jobs.db"

    job_id = create_job("https://github.com/example/example", db_path=db_path)

    assert get_job(job_id, db_path=db_path) is not None


def test_jobs_isolated_across_different_db_files(tmp_path):
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    job_id = create_job("https://github.com/example/example", db_path=db_a)

    assert get_job(job_id, db_path=db_a) is not None
    assert get_job(job_id, db_path=db_b) is None


def test_count_active_jobs_counts_queued_and_running_but_not_done_or_error(tmp_path):
    db_path = tmp_path / "jobs.db"

    queued = create_job("https://github.com/example/a", db_path=db_path)
    running = create_job("https://github.com/example/b", db_path=db_path)
    update_job(running, status="running", db_path=db_path)
    done = create_job("https://github.com/example/c", db_path=db_path)
    update_job(done, status="done", markdown="x", db_path=db_path)
    errored = create_job("https://github.com/example/d", db_path=db_path)
    update_job(errored, status="error", error="x", db_path=db_path)

    assert count_active_jobs(db_path=db_path) == 2
    assert queued  # keep referenced for clarity of intent


def test_try_create_job_returns_none_once_at_capacity(tmp_path):
    db_path = tmp_path / "jobs.db"

    accepted = [try_create_job(f"https://github.com/example/{i}", max_active=3, db_path=db_path) for i in range(3)]
    assert all(job_id is not None for job_id in accepted)

    rejected = try_create_job("https://github.com/example/overflow", max_active=3, db_path=db_path)
    assert rejected is None
    assert count_active_jobs(db_path=db_path) == 3


def test_try_create_job_is_atomic_under_concurrent_callers(tmp_path):
    # Regression test: a plain "count, then insert" (two separate
    # statements) lets many concurrent callers all read a count under the
    # cap before any of them commits, so far more than max_active jobs get
    # created. This exercises try_create_job's single atomic
    # INSERT ... SELECT ... WHERE with real concurrent threads hitting the
    # same db file, not just sequential calls.
    db_path = tmp_path / "jobs.db"
    max_active = 5
    request_count = 40

    def attempt(i: int) -> str | None:
        return try_create_job(f"https://github.com/example/{i}", max_active=max_active, db_path=db_path)

    with ThreadPoolExecutor(max_workers=request_count) as pool:
        results = list(pool.map(attempt, range(request_count)))

    accepted = [r for r in results if r is not None]
    assert len(accepted) == max_active
    assert count_active_jobs(db_path=db_path) == max_active


def test_cleanup_stale_jobs_removes_only_finished_jobs_older_than_max_age(tmp_path):
    db_path = tmp_path / "jobs.db"

    old_job = create_job("https://github.com/example/old", db_path=db_path)
    update_job(old_job, status="done", markdown="# report", db_path=db_path)
    recent_job = create_job("https://github.com/example/recent", db_path=db_path)
    update_job(recent_job, status="done", markdown="# report", db_path=db_path)
    _backdate_job(old_job, db_path, hours_ago=48)
    _backdate_job(recent_job, db_path, hours_ago=1)

    removed = cleanup_stale_jobs(max_age_hours=24, db_path=db_path)

    assert removed == 1
    assert get_job(old_job, db_path=db_path) is None
    assert get_job(recent_job, db_path=db_path) is not None


def test_cleanup_stale_jobs_never_removes_a_running_or_queued_job(tmp_path):
    db_path = tmp_path / "jobs.db"

    stuck_running = create_job("https://github.com/example/stuck-running", db_path=db_path)
    update_job(stuck_running, status="running", db_path=db_path)
    _backdate_job(stuck_running, db_path, hours_ago=48)

    stuck_queued = create_job("https://github.com/example/stuck-queued", db_path=db_path)
    _backdate_job(stuck_queued, db_path, hours_ago=48)

    removed = cleanup_stale_jobs(max_age_hours=24, db_path=db_path)

    assert removed == 0
    assert get_job(stuck_running, db_path=db_path) is not None
    assert get_job(stuck_queued, db_path=db_path) is not None


def test_atlas_jobs_db_path_env_var_overrides_the_default(tmp_path):
    # DEFAULT_DB_PATH is computed once at module import, so proving the env
    # var actually takes effect needs a fresh process, not a monkeypatch of
    # an already-imported module attribute.
    custom_path = tmp_path / "custom" / "jobs.db"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.jobs import DEFAULT_DB_PATH\nprint(DEFAULT_DB_PATH)\n",
        ],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        env={**os.environ, "ATLAS_JOBS_DB_PATH": str(custom_path)},
        check=True,
    )

    assert str(custom_path) in result.stdout


def test_cleanup_stale_jobs_is_a_noop_when_nothing_is_old(tmp_path):
    db_path = tmp_path / "jobs.db"
    create_job("https://github.com/example/example", db_path=db_path)

    removed = cleanup_stale_jobs(max_age_hours=24, db_path=db_path)

    assert removed == 0
