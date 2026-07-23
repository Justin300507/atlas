# Atlas Phase 5: Frontend + Async Job Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a minimal React+Vite+TypeScript frontend (paste a GitHub URL, watch
real progress, view the rendered report) backed by a new SQLite-backed async job
API on the FastAPI backend.

**Architecture:** Extract the existing `/documentation` pipeline (clone → parse →
graph → quality → clone-history → git-intelligence → generate-docs) out of
`main.py` into a reusable `report_pipeline.run_full_analysis(repo_url, on_stage)`
function. A new `jobs.py` module persists job state (queued/running/done/error, plus
current stage and, once done, the resulting markdown) to a local SQLite file. New
`POST /jobs` / `GET /jobs/{id}` endpoints create a job, run it on a background
thread pool calling `run_full_analysis` with a stage-reporting callback, and let the
frontend poll for progress once a second until it's done. The frontend renders the
final Markdown (including its Mermaid dependency diagram) directly.

**Tech Stack:** Backend: no new Python dependencies (`sqlite3`, `concurrent.futures`,
`uuid`, `datetime` are stdlib; `CORSMiddleware` ships with `fastapi`). Frontend
(new): React, Vite, TypeScript, `react-markdown`, `remark-gfm`, `mermaid`; `vitest` +
`@testing-library/react` for tests. Node v24 / npm v11 confirmed available.

## Global Constraints

- Backend: Python 3.11+, all code under `backend/`. No new pip dependencies.
- Frontend: new `frontend/` directory at the repo root, sibling to `backend/`.
- `/analyze` and `/git-intelligence`'s *behavior* must not change. Their *test
  module paths* may need updates where they patch things this plan relocates —
  exactly three existing tests need such updates (see Task 1's Step 5), and no
  others.
- Job state persists in a local SQLite file (`backend/atlas_jobs.db`, gitignored),
  not in memory and not in an external service (Redis, etc.) — no separate service
  to install for anyone running Atlas locally.
- Progress delivery is polling (`GET /jobs/{id}` roughly once a second), not SSE.
- CORS: allow all origins. Atlas has no auth and no secrets in its responses; this
  is a deliberate, documented choice, not an oversight.
- No job history/listing endpoint, no cancel/retry, no auth, no multi-panel
  interactive-graph dashboard — the frontend renders `/documentation`'s existing
  Markdown output as-is.

---

### Task 1: Extract `report_pipeline.py` from `main.py`

**Files:**
- Create: `backend/app/report_pipeline.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py` (three tests need monkeypatch-path updates)

**Interfaces:**
- Consumes: `app.cloner.{CloneError, InvalidRepoUrlError, clone_with_history,
  shallow_clone}`, `app.code_parser.parse_file`, `app.doc_generator.
  generate_documentation`, `app.git_intelligence.analyze_git_history`,
  `app.git_log_parser.parse_git_log`, `app.graph_builder.build_graph`,
  `app.models.DocumentationResponse`, `app.quality_engine.analyze_quality`,
  `app.stack_detector.detect` — all existing, unchanged.
- Produces: `run_full_analysis(repo_url: str, on_stage: Callable[[str], None] | None
  = None) -> DocumentationResponse`, plus re-exported `_EXCLUDED_DIRS`,
  `_MAX_FILE_SIZE_BYTES`, `_MAX_FILES_PER_REPO`, `_GIT_HISTORY_COMMITS`,
  `_iter_source_files` (moved here verbatim from `main.py`). Used by Task 3
  (`main.py`'s new `/jobs` endpoint) and by `main.py`'s existing `/analyze`,
  `/documentation`, `/git-intelligence` endpoints.

- [ ] **Step 1: Create `report_pipeline.py`**

```python
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone
from .code_parser import parse_file
from .doc_generator import generate_documentation
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import build_graph
from .models import DocumentationResponse
from .quality_engine import analyze_quality
from .stack_detector import detect

# Bounds on parsing arbitrary cloned repos: this pipeline clones and parses
# arbitrary public repo URLs with no auth, so a pathological repo (one huge
# file, or hundreds of thousands of files) must not be able to exhaust
# memory/CPU.
_EXCLUDED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # skip individual files larger than this
_MAX_FILES_PER_REPO = 5000  # stop walking a repo after yielding this many files

# The commit window analyzed for git intelligence. The clone depth is set one
# commit deeper than what's analyzed so a truncated repo always has a spare
# commit locally for parse_git_log's truncation check to find — cloning and
# analyzing the exact same depth would make history_truncated always False,
# since a --depth-N clone physically cannot contain an (N+1)th commit.
_GIT_HISTORY_COMMITS = 500


def _iter_source_files(repo_path: Path):
    count = 0
    for path in repo_path.rglob("*"):
        if count >= _MAX_FILES_PER_REPO:
            return
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                continue
        except OSError:
            continue
        count += 1
        yield path


def _noop_stage(_stage: str) -> None:
    pass


def run_full_analysis(
    repo_url: str, on_stage: Callable[[str], None] | None = None
) -> DocumentationResponse:
    notify = on_stage or _noop_stage

    notify("cloning_structure")
    with shallow_clone(repo_url) as repo_path:
        repo_root = repo_path
        stack = detect(repo_path)

        notify("parsing")
        files = []
        for path in _iter_source_files(repo_path):
            try:
                symbols = parse_file(path)
            except Exception:
                continue
            if symbols is not None:
                files.append(symbols)

        notify("building_graph")
        graph = build_graph(files, repo_root=repo_path)

        notify("analyzing_quality")
        quality = analyze_quality(files, graph)

    notify("cloning_history")
    with clone_with_history(repo_url, depth=_GIT_HISTORY_COMMITS + 1) as history_path:
        notify("analyzing_git_history")
        commits, history_truncated = parse_git_log(history_path, max_commits=_GIT_HISTORY_COMMITS)
        git_report = analyze_git_history(commits, history_truncated)

    notify("generating_documentation")
    markdown = generate_documentation(repo_root, stack, files, graph, quality, git_report)
    return DocumentationResponse(markdown=markdown)
```

- [ ] **Step 2: Update `main.py` to use it**

Replace the full contents of `backend/app/main.py` with:

```python
from __future__ import annotations

import subprocess

from fastapi import FastAPI, HTTPException

from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone
from .code_parser import parse_file
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import build_graph, to_node_link
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    DocumentationResponse,
    GitIntelligenceReport,
    GraphResponse,
)
from .quality_engine import analyze_quality
from .report_pipeline import (
    _GIT_HISTORY_COMMITS,
    _iter_source_files,
    run_full_analysis,
)
from .stack_detector import detect

app = FastAPI(title="Atlas Repository Intelligence")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        with shallow_clone(request.repo_url) as repo_path:
            stack = detect(repo_path)
            files = []
            for path in _iter_source_files(repo_path):
                try:
                    symbols = parse_file(path)
                except Exception:
                    continue
                if symbols is not None:
                    files.append(symbols)
            graph = build_graph(files, repo_root=repo_path)
            quality = analyze_quality(files, graph)
            return AnalyzeResponse(
                stack=stack,
                graph=GraphResponse(**to_node_link(graph)),
                quality=quality,
            )
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/documentation", response_model=DocumentationResponse)
def documentation(request: AnalyzeRequest) -> DocumentationResponse:
    try:
        return run_full_analysis(request.repo_url)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/git-intelligence", response_model=GitIntelligenceReport)
def git_intelligence(request: AnalyzeRequest) -> GitIntelligenceReport:
    try:
        with clone_with_history(request.repo_url, depth=_GIT_HISTORY_COMMITS + 1) as repo_path:
            commits, history_truncated = parse_git_log(repo_path, max_commits=_GIT_HISTORY_COMMITS)
            return analyze_git_history(commits, history_truncated)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Note what changed from the current file: `_EXCLUDED_DIRS`, `_MAX_FILE_SIZE_BYTES`,
`_MAX_FILES_PER_REPO`, `_iter_source_files` are no longer defined in `main.py` —
they're imported from `.report_pipeline`. `/documentation`'s body shrinks to a
single `run_full_analysis` call. `/analyze` and `/git-intelligence` are otherwise
byte-for-byte identical to today.

- [ ] **Step 3: Run the full test suite to see what breaks**

Run: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`

Expected: most tests pass; exactly these fail, because they patch a name that now
lives in a different module (Python resolves a monkeypatched name in the module
that actually calls it — not wherever it happens to be re-imported):
- `test_analyze_skips_oversized_file_and_keeps_others` — `ImportError` or wrong
  value, since `from app.main import _MAX_FILE_SIZE_BYTES` no longer finds a
  locally-defined constant with the same live value semantics as before.
- `test_analyze_stops_walking_after_max_file_count` — the monkeypatch no longer
  affects the constant `_iter_source_files` actually reads.
- `test_documentation_returns_markdown_report` — the monkeypatched
  `app.main.shallow_clone`/`app.main.clone_with_history` are no longer what
  `run_full_analysis` calls internally.

- [ ] **Step 4: Fix the three tests**

In `backend/tests/test_api.py`, change:

```python
def test_analyze_skips_oversized_file_and_keeps_others(monkeypatch, tmp_path):
    from app.main import _MAX_FILE_SIZE_BYTES
```

to:

```python
def test_analyze_skips_oversized_file_and_keeps_others(monkeypatch, tmp_path):
    from app.report_pipeline import _MAX_FILE_SIZE_BYTES
```

Change:

```python
def test_analyze_stops_walking_after_max_file_count(monkeypatch, tmp_path):
    for i in range(5):
        (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")

    monkeypatch.setattr("app.main._MAX_FILES_PER_REPO", 2)
```

to:

```python
def test_analyze_stops_walking_after_max_file_count(monkeypatch, tmp_path):
    for i in range(5):
        (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")

    monkeypatch.setattr("app.report_pipeline._MAX_FILES_PER_REPO", 2)
```

Change:

```python
    monkeypatch.setattr("app.main.shallow_clone", fake_shallow_clone)
    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post("/documentation", json={"repo_url": "https://github.com/example/example"})
```

(this is inside `test_documentation_returns_markdown_report`) to:

```python
    monkeypatch.setattr("app.report_pipeline.shallow_clone", fake_shallow_clone)
    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)

    resp = client.post("/documentation", json={"repo_url": "https://github.com/example/example"})
```

- [ ] **Step 5: Run the full test suite again**

Run: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`

Expected: all 85 tests pass (same count as before this task — this is a pure
refactor, no test added or removed yet).

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/report_pipeline.py backend/app/main.py backend/tests/test_api.py
git commit -m "refactor: extract shared analysis pipeline into report_pipeline.py"
```

---

### Task 2: `jobs.py` — SQLite-backed job store

**Files:**
- Create: `backend/app/jobs.py`
- Create: `backend/tests/test_jobs.py`

**Interfaces:**
- Consumes: nothing new (stdlib `sqlite3`, `uuid`, `datetime`, `dataclasses`,
  `pathlib`).
- Produces:
  - `@dataclass JobRecord(id: str, repo_url: str, status: str, stage: str | None,
    markdown: str | None, error: str | None, created_at: str, updated_at: str)`
  - `create_job(repo_url: str, db_path: Path | None = None) -> str` (returns a new
    job id)
  - `update_job(job_id: str, *, status: str | None = None, stage: str | None =
    None, markdown: str | None = None, error: str | None = None, db_path: Path |
    None = None) -> None`
  - `get_job(job_id: str, db_path: Path | None = None) -> JobRecord | None`
  - `DEFAULT_DB_PATH: Path` (module-level constant, resolved fresh inside each
    function body rather than bound as a default-parameter value, so tests can
    monkeypatch it and have every subsequent call pick up the new path)
  - Used by Task 3 (`main.py`'s `/jobs` endpoints).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_jobs.py`:

```python
from app.jobs import create_job, get_job, update_job


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


def test_jobs_isolated_across_different_db_files(tmp_path):
    db_a = tmp_path / "a.db"
    db_b = tmp_path / "b.db"

    job_id = create_job("https://github.com/example/example", db_path=db_a)

    assert get_job(job_id, db_path=db_a) is not None
    assert get_job(job_id, db_path=db_b) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs'`.

- [ ] **Step 3: Implement `jobs.py`**

```python
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_jobs.py -v`
Expected: all 5 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/jobs.py backend/tests/test_jobs.py
git commit -m "feat: add SQLite-backed job store"
```

---

### Task 3: Wire `/jobs` endpoints and CORS into `main.py`

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `.gitignore` (repo root)
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: `run_full_analysis` (Task 1), `jobs.create_job`/`update_job`/`get_job`
  (Task 2), `cloner.validate_github_url` (existing).
- Produces: `POST /jobs` → `{"job_id": str}` (HTTP 202); `GET /jobs/{job_id}` →
  `{"id", "status", "stage", "markdown", "error"}` (HTTP 200) or 404.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py`:

```python
from app import jobs as app_jobs
from app import main as app_main


def test_create_job_returns_202_with_job_id(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url: None)

    resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})

    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert app_jobs.get_job(body["job_id"]) is not None


def test_create_job_rejects_invalid_url(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    resp = client.post("/jobs", json={"repo_url": "not-a-url"})

    assert resp.status_code == 400


def test_get_job_returns_404_for_unknown_id(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    resp = client.get("/jobs/does-not-exist")

    assert resp.status_code == 404


def test_job_runs_synchronously_via_submit_override_and_reaches_done(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    structure_fixture = FIXTURES / "fastapi_repo"
    history_repo = tmp_path / "history_repo"
    history_repo.mkdir()
    subprocess.run(["git", "init"], cwd=history_repo, check=True, capture_output=True)
    (history_repo / "a.py").write_text("1\n")
    subprocess.run(["git", "add", "a.py"], cwd=history_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=history_repo,
        check=True,
        capture_output=True,
    )

    @contextmanager
    def fake_shallow_clone(url, timeout=60):
        yield structure_fixture

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield history_repo

    monkeypatch.setattr("app.report_pipeline.shallow_clone", fake_shallow_clone)
    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)
    # Run the job inline instead of on a background thread, so the test is
    # deterministic — _submit_job and _run_job share the same (job_id,
    # repo_url) signature, so this substitution is exact.
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    job_id = create_resp.json()["job_id"]

    status_resp = client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "done"
    assert body["error"] is None
    assert "## Executive Summary" in body["markdown"]


def test_job_records_error_on_clone_failure(monkeypatch, tmp_path):
    from app.cloner import CloneError

    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    @contextmanager
    def failing_clone(url, timeout=60):
        raise CloneError("repository not found")
        yield  # pragma: no cover

    monkeypatch.setattr("app.report_pipeline.shallow_clone", failing_clone)
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/does-not-exist"})
    job_id = create_resp.json()["job_id"]

    status_resp = client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "error"
    assert body["error"] == "repository not found"
    assert body["markdown"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v -k job`
Expected: FAIL — 404 (no `/jobs` route yet) or `ImportError` for `app_jobs`/`app_main`.

- [ ] **Step 3: Wire the endpoints**

In `backend/app/main.py`, add these imports (extend the existing import block):

```python
from concurrent.futures import ThreadPoolExecutor

from fastapi.middleware.cors import CORSMiddleware

from . import jobs
from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone, validate_github_url
```

(this replaces the existing `from .cloner import CloneError, InvalidRepoUrlError,
clone_with_history, shallow_clone` line — it now also imports `validate_github_url`)

After `app = FastAPI(title="Atlas Repository Intelligence")`, add:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=4)
```

At the end of the file, add:

```python
def _submit_job(job_id: str, repo_url: str) -> None:
    _JOB_EXECUTOR.submit(_run_job, job_id, repo_url)


def _run_job(job_id: str, repo_url: str) -> None:
    jobs.update_job(job_id, status="running")
    try:
        response = run_full_analysis(
            repo_url, on_stage=lambda stage: jobs.update_job(job_id, stage=stage)
        )
        jobs.update_job(job_id, status="done", markdown=response.markdown)
    except InvalidRepoUrlError as exc:
        jobs.update_job(job_id, status="error", error=str(exc))
    except subprocess.TimeoutExpired:
        jobs.update_job(job_id, status="error", error="Repository clone timed out")
    except CloneError as exc:
        jobs.update_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # pragma: no cover - safety net for unexpected failures
        jobs.update_job(job_id, status="error", error=f"Unexpected error: {exc}")


@app.post("/jobs", status_code=202)
def create_job_endpoint(request: AnalyzeRequest) -> dict:
    try:
        validate_github_url(request.repo_url)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    job_id = jobs.create_job(request.repo_url)
    _submit_job(job_id, request.repo_url)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job_endpoint(job_id: str) -> dict:
    record = jobs.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id}")
    return {
        "id": record.id,
        "status": record.status,
        "stage": record.stage,
        "markdown": record.markdown,
        "error": record.error,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v -k job`
Expected: all 5 new tests pass.

Run the full suite: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all tests pass (85 existing + 5 new + 5 from Task 2 = 95), no regressions.

- [ ] **Step 5: Ignore the generated SQLite file**

In the root `.gitignore`, add a line:

```
*.db
```

- [ ] **Step 6: Update backend README**

Add a `## Jobs (async analysis with progress)` section in `backend/README.md`,
after the `## Documentation Generator` section:

```markdown
## Jobs (async analysis with progress)

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\": \"https://github.com/octocat/Hello-World\"}"
# => {"job_id": "..."}

curl http://127.0.0.1:8000/jobs/<job_id>
# => {"id": "...", "status": "running", "stage": "analyzing_quality", "markdown": null, "error": null}
```

Runs the same pipeline as `/documentation`, but asynchronously: `POST /jobs`
returns a job id immediately (202), and the analysis runs on a background thread.
Poll `GET /jobs/{job_id}` (roughly once a second) until `status` is `"done"`
(`markdown` populated) or `"error"` (`error` populated). Job state is persisted to
a local SQLite file (`backend/atlas_jobs.db`, created automatically, gitignored) —
not in-memory-only, so job state survives a backend restart; not Redis, so nothing
extra needs to be installed to run this locally.
```

- [ ] **Step 7: Commit**

```bash
cd ~/atlas
git add backend/app/main.py backend/tests/test_api.py backend/README.md .gitignore
git commit -m "feat: add async /jobs API with SQLite-backed progress tracking"
```

---

### Task 4: Frontend scaffold with Idle/Running states and polling

**Files:**
- Create: `frontend/` (via `npm create vite@latest`)
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/App.css`
- Create: `frontend/src/api.ts`

**Interfaces:**
- Consumes: `POST /jobs`, `GET /jobs/{id}` (Task 3), assumed to run at
  `http://127.0.0.1:8000` in dev.
- Produces: `createJob(repoUrl: string): Promise<{job_id: string}>`,
  `getJob(jobId: string): Promise<JobRecord>`, both importable from `./api`. Used
  by Task 5 (`App.tsx`'s Done/Error states) and `App.test.tsx`.

- [ ] **Step 1: Scaffold the Vite project**

Run from the repo root:

```bash
cd ~/atlas
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
```

Expected: a `frontend/` directory with `package.json`, `vite.config.ts`,
`tsconfig.json`, `index.html`, `src/main.tsx`, `src/App.tsx`, etc.

- [ ] **Step 2: Install additional dependencies**

```bash
cd ~/atlas/frontend
npm install react-markdown remark-gfm mermaid
npm install --save-dev vitest @testing-library/react @testing-library/jest-dom jsdom
```

- [ ] **Step 3: Create the API client**

Create `frontend/src/api.ts`:

```typescript
const API_BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export type JobStatus = "queued" | "running" | "done" | "error";

export interface JobRecord {
  id: string;
  status: JobStatus;
  stage: string | null;
  markdown: string | null;
  error: string | null;
}

export async function createJob(repoUrl: string): Promise<{ job_id: string }> {
  const resp = await fetch(`${API_BASE}/jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ repo_url: repoUrl }),
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({ detail: null }));
    throw new Error(body.detail || `Request failed with status ${resp.status}`);
  }
  return resp.json();
}

export async function getJob(jobId: string): Promise<JobRecord> {
  const resp = await fetch(`${API_BASE}/jobs/${jobId}`);
  if (!resp.ok) {
    throw new Error(`Request failed with status ${resp.status}`);
  }
  return resp.json();
}
```

- [ ] **Step 4: Write the App component's Idle/Running states**

Replace the contents of `frontend/src/App.tsx`:

```tsx
import { useEffect, useRef, useState, type FormEvent } from "react";
import "./App.css";
import { createJob, getJob, type JobRecord } from "./api";

const STAGES = [
  "cloning_structure",
  "parsing",
  "building_graph",
  "analyzing_quality",
  "cloning_history",
  "analyzing_git_history",
  "generating_documentation",
];

const STAGE_LABELS: Record<string, string> = {
  cloning_structure: "Cloning repository",
  parsing: "Parsing source files",
  building_graph: "Building dependency graph",
  analyzing_quality: "Analyzing code quality",
  cloning_history: "Cloning commit history",
  analyzing_git_history: "Analyzing git history",
  generating_documentation: "Generating documentation",
};

type ViewState = "idle" | "running" | "done" | "error";

interface AppProps {
  pollIntervalMs?: number;
}

function App({ pollIntervalMs = 1000 }: AppProps) {
  const [repoUrl, setRepoUrl] = useState("");
  const [view, setView] = useState<ViewState>("idle");
  const [job, setJob] = useState<JobRecord | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const pollRef = useRef<number | null>(null);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
      if (timerRef.current) window.clearInterval(timerRef.current);
    };
  }, []);

  function stopTimers() {
    if (pollRef.current) window.clearInterval(pollRef.current);
    if (timerRef.current) window.clearInterval(timerRef.current);
  }

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    setSubmitError(null);
    try {
      const { job_id } = await createJob(repoUrl);
      setJob(null);
      setElapsedSeconds(0);
      setView("running");

      timerRef.current = window.setInterval(() => {
        setElapsedSeconds((s) => s + 1);
      }, pollIntervalMs);

      pollRef.current = window.setInterval(async () => {
        try {
          const record = await getJob(job_id);
          setJob(record);
          if (record.status === "done" || record.status === "error") {
            stopTimers();
            setView(record.status);
          }
        } catch {
          // A single dropped poll isn't a job failure — retry on the next tick.
        }
      }, pollIntervalMs);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to start analysis");
    }
  }

  function reset() {
    setView("idle");
    setJob(null);
    setSubmitError(null);
    setRepoUrl("");
  }

  const currentStageIndex = job?.stage ? STAGES.indexOf(job.stage) : -1;

  return (
    <div className="app">
      <h1>Atlas</h1>

      {view === "idle" && (
        <form onSubmit={handleSubmit}>
          <input
            type="text"
            placeholder="https://github.com/owner/repo"
            value={repoUrl}
            onChange={(e) => setRepoUrl(e.target.value)}
            required
          />
          <button type="submit">Analyze</button>
          {submitError && <p className="error">{submitError}</p>}
        </form>
      )}

      {view === "running" && (
        <div className="progress">
          <p>{elapsedSeconds}s elapsed</p>
          <ul>
            {STAGES.map((stage, i) => (
              <li key={stage} className={i <= currentStageIndex ? "done" : ""}>
                {STAGE_LABELS[stage]}
              </li>
            ))}
          </ul>
        </div>
      )}

      {view === "done" && job?.markdown && (
        <div className="report">
          <button onClick={reset}>New Analysis</button>
          <pre>{job.markdown}</pre>
        </div>
      )}

      {view === "error" && (
        <div className="report">
          <p className="error">{job?.error ?? "Analysis failed"}</p>
          <button onClick={reset}>Try Again</button>
        </div>
      )}
    </div>
  );
}

export default App;
```

(The Done state renders raw markdown in a `<pre>` for now — Task 5 replaces this
with a real Markdown+Mermaid renderer. Keeping this task's App functional and
testable on its own is the point of splitting it out.)

- [ ] **Step 5: Simplify the stylesheet**

Replace the contents of `frontend/src/App.css`:

```css
.app {
  max-width: 800px;
  margin: 0 auto;
  padding: 2rem 1rem;
  font-family: system-ui, sans-serif;
}

form {
  display: flex;
  gap: 0.5rem;
}

input[type="text"] {
  flex: 1;
  padding: 0.5rem;
  font-size: 1rem;
}

button {
  padding: 0.5rem 1rem;
  font-size: 1rem;
  cursor: pointer;
}

.error {
  color: #b00020;
}

.progress ul {
  list-style: none;
  padding: 0;
}

.progress li {
  padding: 0.25rem 0;
  color: #888;
}

.progress li.done {
  color: #111;
  font-weight: 600;
}

.report pre {
  white-space: pre-wrap;
  word-wrap: break-word;
}
```

- [ ] **Step 6: Run the dev build to confirm it compiles**

Run: `cd frontend && npm run build`
Expected: builds successfully with no TypeScript errors.

- [ ] **Step 7: Commit**

```bash
cd ~/atlas
git add frontend/
git commit -m "feat: scaffold React+Vite frontend with job polling"
```

---

### Task 5: Markdown+Mermaid rendering, Error state polish, and frontend tests

**Files:**
- Create: `frontend/src/MarkdownReport.tsx`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/setupTests.ts`
- Modify: `frontend/vite.config.ts`
- Modify: `frontend/package.json`
- Create: `frontend/src/App.test.tsx`

**Interfaces:**
- Consumes: `JobRecord` (Task 4's `api.ts`).
- Produces: `MarkdownReport({ markdown: string })` component, used by `App.tsx`'s
  Done state.

- [ ] **Step 1: Create the Markdown+Mermaid renderer**

Create `frontend/src/MarkdownReport.tsx`:

```tsx
import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false });

let mermaidIdCounter = 0;

function MermaidBlock({ code }: { code: string }) {
  const [svg, setSvg] = useState<string>("");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    mermaidIdCounter += 1;
    const id = `atlas-mermaid-${mermaidIdCounter}`;
    mermaid
      .render(id, code)
      .then((result) => {
        if (!cancelled) setSvg(result.svg);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [code]);

  if (failed) {
    return <pre>{code}</pre>;
  }
  // eslint-disable-next-line react/no-danger
  return <div dangerouslySetInnerHTML={{ __html: svg }} />;
}

interface CodeProps {
  className?: string;
  children?: React.ReactNode;
}

function CodeBlock({ className, children }: CodeProps) {
  const language = /language-(\w+)/.exec(className || "")?.[1];
  const codeText = String(children).replace(/\n$/, "");

  if (language === "mermaid") {
    return <MermaidBlock code={codeText} />;
  }
  return <code className={className}>{children}</code>;
}

export function MarkdownReport({ markdown }: { markdown: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={{ code: CodeBlock }}>
      {markdown}
    </ReactMarkdown>
  );
}
```

- [ ] **Step 2: Wire it into `App.tsx`'s Done state**

In `frontend/src/App.tsx`, add the import:

```tsx
import { MarkdownReport } from "./MarkdownReport";
```

Replace:

```tsx
      {view === "done" && job?.markdown && (
        <div className="report">
          <button onClick={reset}>New Analysis</button>
          <pre>{job.markdown}</pre>
        </div>
      )}
```

with:

```tsx
      {view === "done" && job?.markdown && (
        <div className="report">
          <button onClick={reset}>New Analysis</button>
          <MarkdownReport markdown={job.markdown} />
        </div>
      )}
```

- [ ] **Step 3: Configure Vitest**

Replace the contents of `frontend/vite.config.ts`:

```typescript
/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    globals: true,
  },
});
```

Create `frontend/src/setupTests.ts`:

```typescript
import "@testing-library/jest-dom/vitest";
```

In `frontend/package.json`, add a `test` script to the existing `"scripts"` block
(keep `dev`, `build`, `lint`, `preview` as they are):

```json
    "test": "vitest run"
```

- [ ] **Step 4: Write the failing frontend tests**

Create `frontend/src/App.test.tsx`:

```tsx
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import App from "./App";

function jsonResponse(body: unknown, ok = true, status = 200) {
  return Promise.resolve({
    ok,
    status,
    json: () => Promise.resolve(body),
  });
}

describe("App", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows an inline error when submission fails", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ detail: "Not a valid GitHub repository URL" }, false, 400));
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "not-a-url" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(() => {
      expect(screen.getByText("Not a valid GitHub repository URL")).toBeInTheDocument();
    });
  });

  it("submits a URL and shows the running state", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "running",
          stage: "parsing",
          markdown: null,
          error: null,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(() => {
      expect(screen.getByText("Parsing source files")).toHaveClass("done");
    });
  });

  it("renders the report once the job is done", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "done",
          stage: "generating_documentation",
          markdown: "## Executive Summary\n\nhello",
          error: null,
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(
      () => {
        expect(screen.getByText("Executive Summary")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );
  });

  it("shows an error state when the job fails", async () => {
    const fetchMock = vi
      .fn()
      .mockReturnValueOnce(jsonResponse({ job_id: "abc123" }))
      .mockReturnValue(
        jsonResponse({
          id: "abc123",
          status: "error",
          stage: "cloning_structure",
          markdown: null,
          error: "Repository clone timed out",
        })
      );
    vi.stubGlobal("fetch", fetchMock);

    render(<App pollIntervalMs={5} />);
    fireEvent.change(screen.getByPlaceholderText(/github.com/i), {
      target: { value: "https://github.com/example/example" },
    });
    fireEvent.click(screen.getByText("Analyze"));

    await waitFor(
      () => {
        expect(screen.getByText("Repository clone timed out")).toBeInTheDocument();
      },
      { timeout: 2000 }
    );

    fireEvent.click(screen.getByText("Try Again"));
    expect(screen.getByPlaceholderText(/github.com/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 5: Run the tests to verify they fail (before the App prop existed they'd
  fail to compile; run now to confirm everything after Steps 1-3 actually passes)**

Run: `cd frontend && npm test`
Expected: all 4 tests pass (Steps 1-3 already wired the real implementation; this
confirms it). If `Parsing source files` isn't found with a `done` class, check that
`STAGES`/`STAGE_LABELS` in `App.tsx` match the stage names `report_pipeline.py`
actually emits (`cloning_structure`, `parsing`, `building_graph`,
`analyzing_quality`, `cloning_history`, `analyzing_git_history`,
`generating_documentation`) exactly.

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add frontend/
git commit -m "feat: render Markdown+Mermaid reports and add frontend tests"
```

---

### Task 6: Manual real-repo end-to-end validation

**Files:** none created or modified — this task is a manual verification step, not
a code change, per the process adopted after Phase 4 (real-repo validation is a
required gate before any phase is considered complete, since it has caught bugs
unit tests missed on every prior phase).

- [ ] **Step 1: Start the backend**

```bash
cd ~/atlas/backend
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Leave this running in one terminal.

- [ ] **Step 2: Start the frontend dev server**

```bash
cd ~/atlas/frontend
npm run dev
```

Note the local URL it prints (typically `http://localhost:5173`).

- [ ] **Step 3: Exercise the full flow against a real repo**

Open the frontend URL in a browser. Paste `https://github.com/octocat/Hello-World`
and click Analyze. Confirm:
- The Running view appears immediately and stage checkmarks progress over the next
  few seconds (not stuck, not all-at-once).
- The view transitions to Done and renders a readable report, including its
  Dependency Diagram section (even if empty/trivial for this tiny repo) without a
  raw ```mermaid code block showing through unrendered.
- "New Analysis" returns to the Idle screen and a second analysis can be started.

- [ ] **Step 4: Exercise the error path**

Paste an invalid value (e.g. `not-a-url`) and click Analyze. Confirm an inline
error appears on the Idle screen without ever transitioning to Running.

- [ ] **Step 5: Exercise a real repo with an actual dependency graph**

Repeat Step 3 with `https://github.com/tiangolo/typer` (confirmed reachable during
Phase 3/4 validation). Confirm the Mermaid dependency diagram actually renders as a
graph (not raw text), and that the report includes believable (non-zero,
non-astronomical) quality scores and git-intelligence data, consistent with the
`20/100` overall score and 2-cluster result from the last real-repo validation
round.

- [ ] **Step 6: Note results**

No commit for this task (nothing changes) — report findings back: did the full
flow work end-to-end, and if not, what broke? Fix any issues found here as a
follow-up task before considering Phase 5 complete, following the same
spec-deviation-or-bug judgment call used throughout every prior phase's real-repo
validation round.

---

## After this plan

Phase 5 delivers a working, demoable frontend with real backend-tracked progress,
completing the "presentation" milestone discussed after Phase 4. This is also the
first phase to introduce server-side state (SQLite-backed job records) — every
prior phase was explicitly stateless. Explicitly deferred: job history/listing,
job cancellation/retry, auth, a multi-panel/interactive-graph dashboard, SSE
streaming, published example reports, performance benchmarking, and public beta —
all per the user's stated 4-week plan, to be picked up as separate, explicitly
scoped follow-ups.
