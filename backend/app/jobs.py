from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "atlas_jobs.db"

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


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
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
