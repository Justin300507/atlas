from __future__ import annotations

import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ATLAS_JOBS_DB_PATH lets a deployment point this at a mounted volume (see
# docker-compose.yml) without colliding with the app package directory that
# the default path is otherwise computed relative to.
DEFAULT_DB_PATH = Path(
    os.environ.get("ATLAS_JOBS_DB_PATH")
    or Path(__file__).resolve().parent.parent / "atlas_jobs.db"
)

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    status TEXT NOT NULL,
    stage TEXT,
    markdown TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
"""


@dataclass
class JobRecord:
    id: str
    repo_url: str
    status: str
    stage: str | None
    markdown: str | None
    error: str | None
    created_at: str
    updated_at: str


def _resolve_db_path(db_path: Path | None) -> Path:
    return db_path if db_path is not None else DEFAULT_DB_PATH


_WAL_SWITCH_RETRIES = 5
_WAL_SWITCH_RETRY_DELAY_SECONDS = 0.05


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Found via a real CI failure under concurrent load (_MAX_ACTIVE_JOBS=8
    # jobs, 4 of them truly parallel via _JOB_EXECUTOR, each opening a fresh
    # connection per update_job() call across ~10 writes over its
    # pipeline): sqlite3.connect()'s default 5s busy-timeout wasn't always
    # enough headroom on a loaded runner, raising "database is locked".
    # WAL mode lets readers (get_job/count_active_jobs polling) proceed
    # without blocking on an in-progress writer, which is the actual
    # source of contention here, not a logic race -- try_create_job's
    # atomicity (see its own docstring) is unaffected by either change.
    conn = sqlite3.connect(db_path, timeout=30.0)
    # Switching a brand-new file to WAL mode is itself a write (it creates
    # the -wal/-shm sidecar files) -- found immediately by this fix's own
    # test suite: 40 threads all calling _connect() on a fresh db file
    # for the first time can collide on that switch and raise "database is
    # locked" right away, faster than the connection's busy-timeout kicks
    # in (a Windows file-locking rough edge, not something the timeout
    # parameter alone covers). Once any connection succeeds, the mode is
    # stored in the file itself, so this retry only ever matters during
    # that brief first-initialization window.
    for attempt in range(_WAL_SWITCH_RETRIES):
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            break
        except sqlite3.OperationalError:
            if attempt == _WAL_SWITCH_RETRIES - 1:
                raise
            time.sleep(_WAL_SWITCH_RETRY_DELAY_SECONDS)
    conn.execute(_CREATE_TABLE_SQL)
    return conn


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_job(repo_url: str, db_path: Path | None = None) -> str:
    resolved_path = _resolve_db_path(db_path)
    job_id = str(uuid.uuid4())
    now = _now()
    conn = _connect(resolved_path)
    try:
        conn.execute(
            "INSERT INTO jobs (id, repo_url, status, stage, markdown, error, created_at, updated_at) "
            "VALUES (?, ?, 'queued', NULL, NULL, NULL, ?, ?)",
            (job_id, repo_url, now, now),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id


def try_create_job(repo_url: str, max_active: int, db_path: Path | None = None) -> str | None:
    """Atomically create a job only if under `max_active` -- a plain
    "check count, then insert" (two statements) has a real TOCTOU race
    under concurrent requests: several callers can all read a count under
    the cap before any of them commits their insert, letting far more than
    `max_active` jobs through at once. A single INSERT ... SELECT ... WHERE
    is one statement, so SQLite's own write-locking makes the count check
    and the insert atomic with respect to other connections."""
    resolved_path = _resolve_db_path(db_path)
    job_id = str(uuid.uuid4())
    now = _now()
    conn = _connect(resolved_path)
    try:
        cursor = conn.execute(
            "INSERT INTO jobs (id, repo_url, status, stage, markdown, error, created_at, updated_at) "
            "SELECT ?, ?, 'queued', NULL, NULL, NULL, ?, ? "
            "WHERE (SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')) < ?",
            (job_id, repo_url, now, now, max_active),
        )
        conn.commit()
    finally:
        conn.close()
    return job_id if cursor.rowcount == 1 else None


def update_job(
    job_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    markdown: str | None = None,
    error: str | None = None,
    db_path: Path | None = None,
) -> None:
    resolved_path = _resolve_db_path(db_path)
    fields: list[str] = []
    values: list[str] = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if stage is not None:
        fields.append("stage = ?")
        values.append(stage)
    if markdown is not None:
        fields.append("markdown = ?")
        values.append(markdown)
    if error is not None:
        fields.append("error = ?")
        values.append(error)
    fields.append("updated_at = ?")
    values.append(_now())
    values.append(job_id)

    conn = _connect(resolved_path)
    try:
        conn.execute(f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values)
        conn.commit()
    finally:
        conn.close()


def count_active_jobs(db_path: Path | None = None) -> int:
    resolved_path = _resolve_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')"
        ).fetchone()
    finally:
        conn.close()
    return row[0]


def cleanup_stale_jobs(max_age_hours: float = 24, db_path: Path | None = None) -> int:
    resolved_path = _resolve_db_path(db_path)
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    conn = _connect(resolved_path)
    try:
        # Only ever delete finished jobs. A job can still be legitimately
        # queued/running past the cutoff (there's no hard timeout on the
        # analysis phase itself -- see the security-hardening design doc's
        # "hard CPU timeout" section), and deleting its row out from under it
        # would make the in-flight worker's update_job() a silent no-op and
        # turn its eventual result into a permanent 404.
        cursor = conn.execute(
            "DELETE FROM jobs WHERE created_at < ? AND status IN ('done', 'error')",
            (cutoff,),
        )
        conn.commit()
        return cursor.rowcount
    finally:
        conn.close()


def get_job(job_id: str, db_path: Path | None = None) -> JobRecord | None:
    resolved_path = _resolve_db_path(db_path)
    conn = _connect(resolved_path)
    try:
        row = conn.execute(
            "SELECT id, repo_url, status, stage, markdown, error, created_at, updated_at "
            "FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return JobRecord(*row)
