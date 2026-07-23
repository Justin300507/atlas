# Atlas Phase 5: Frontend + Async Job Progress

## Purpose

Atlas has four working backend endpoints and no way to see any of it without curl.
This phase adds a minimal, demoable frontend: paste a GitHub URL, watch real
analysis progress, view the resulting report. Because real progress requires the
backend to track a running analysis between requests — something no prior phase has
needed — this phase also adds a small, SQLite-backed job API. This is the first
phase to introduce server-side state; every prior phase was explicitly stateless.

## Scope decisions for this phase

- **One job type: run the full `/documentation` pipeline.** `/documentation` already
  computes everything a results view needs (stack, quality, git intelligence, and a
  Markdown report bundling all of it). A job wraps that same pipeline instead of
  inventing a second, thinner one — one code path, one thing to keep correct.
- **SQLite for job state, not in-memory-only or Redis.** In-memory-only was
  considered (simplest, zero new surface area) but rejected: job state should
  survive a backend restart, which matters once this is something other people run
  themselves during beta. Redis was considered and rejected: it requires a separate
  running service, which is real setup friction for anyone (including future beta
  testers) trying to run Atlas locally. SQLite is stdlib (`sqlite3`, no new
  dependency), a single file, and needs nothing installed.
- **Polling, not SSE.** The frontend polls `GET /jobs/{id}` roughly once a second
  until the job reaches `done` or `error`. Simpler and more robust than a streaming
  connection (no reconnect/lifecycle handling to get right), at the cost of up to
  ~1s of UI lag per stage transition — an acceptable trade for a v1.
- **Render `/documentation`'s Markdown as-is, not a multi-panel dashboard.** The
  Markdown report (Executive Summary, Architecture Overview, Dependency Diagram as
  Mermaid, Risk Areas, Recent High-Churn Components, Analysis Coverage) already is
  the results view this phase asked for. A richer, multi-panel dashboard with an
  interactive graph (e.g. React Flow consuming `/analyze`'s raw node/edge JSON) was
  considered and explicitly deferred — real extra frontend work and an extra
  backend call/clone, better justified once real users ask for it.
- **Refactor while touching this code: extract the shared pipeline.**
  `/documentation`'s handler in `main.py` already duplicates `/analyze`'s
  clone→parse→graph→quality steps (flagged, accepted, in Phase 4's review as a
  deliberate v1 shortcut). Adding a second caller of that same pipeline (the job
  runner) is exactly the trigger that shortcut's review comment predicted — so this
  phase extracts it into one shared function instead of copying it a third time.
- **Explicitly out of scope:** job history/listing (a job is only ever looked up by
  the ID the frontend just received — no "list my past analyses" UI), job
  cancellation/retry (v1 shows an error and lets the user resubmit a fresh job),
  auth (Atlas remains a public, unauthenticated analysis tool), horizontal scaling
  of job workers (a single in-process thread pool is enough for one backend
  instance), and the multi-panel/interactive-graph dashboard mentioned above.

## Backend design

### New module: `backend/app/report_pipeline.py`

```python
def run_full_analysis(repo_url: str, on_stage: Callable[[str], None] | None = None) -> DocumentationResponse:
    ...
```

Extracted from `main.py`'s current `/documentation` handler verbatim, with an
`on_stage` callback invoked before each step: `"cloning_structure"`, `"parsing"`,
`"building_graph"`, `"analyzing_quality"`, `"cloning_history"`,
`"analyzing_git_history"`, `"generating_documentation"`. Raises the same
`InvalidRepoUrlError` / `CloneError` / `subprocess.TimeoutExpired` as today — callers
decide how to translate those (HTTP status code for the synchronous endpoint, a
stored error string for the job runner).

`main.py`'s `/documentation` endpoint becomes a thin wrapper: call
`run_full_analysis(request.repo_url)` (no `on_stage`), keep its existing
try/except → HTTP status mapping unchanged. Response shape and behavior are
identical to today — this is a pure refactor of `/documentation`, not a behavior
change, and its existing tests should pass unmodified.

### New module: `backend/app/jobs.py`

SQLite file at `backend/atlas_jobs.db` (created on first use if missing, gitignored
— matches the pattern of other generated/local artifacts like `.venv`). One table:

```sql
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    repo_url TEXT NOT NULL,
    status TEXT NOT NULL,        -- "queued" | "running" | "done" | "error"
    stage TEXT,                  -- current pipeline stage, NULL until running
    markdown TEXT,               -- populated when status = "done"
    error TEXT,                  -- populated when status = "error"
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

Functions: `create_job(repo_url: str) -> str` (returns a new UUID job id, inserts a
`queued` row), `update_job(job_id, *, status=None, stage=None, markdown=None,
error=None)` (updates only the given fields plus `updated_at`), `get_job(job_id) ->
JobRecord | None`. Each function opens its own short-lived `sqlite3.connect(...)`
call — no long-held connection, no connection pool; SQLite handles this concurrency
pattern natively and it keeps the module simple.

### New endpoints in `main.py`

- **`POST /jobs`** — body `{repo_url}` (reuses `AnalyzeRequest`). Validates the URL
  eagerly via `validate_github_url` so a malformed URL fails fast with 400 instead
  of silently queuing a job that will only fail later. On success: creates a job row
  via `jobs.create_job`, submits `_run_job(job_id, repo_url)` to a module-level
  `concurrent.futures.ThreadPoolExecutor` (fire-and-forget — not awaited), and
  returns `{"job_id": ...}` with HTTP 202 immediately.
- **`GET /jobs/{job_id}`** — returns the job row as JSON (`id`, `status`, `stage`,
  `markdown`, `error`). 404 if the id doesn't exist.
- **`_run_job(job_id, repo_url)`** (not a route, runs in the thread pool): marks the
  job `running`, calls `run_full_analysis(repo_url, on_stage=lambda stage:
  jobs.update_job(job_id, stage=stage))`, and on success stores the resulting
  markdown with `status="done"`. On `InvalidRepoUrlError` / `CloneError` /
  `subprocess.TimeoutExpired` / any other exception, stores a user-facing error
  string with `status="error"`.

### CORS

The Vite dev server runs on a different origin than the FastAPI backend, so
`fastapi.middleware.cors.CORSMiddleware` is added, allowing all origins. Atlas has
no auth and no secrets in its responses — it's a public repo-analysis tool — so a
permissive CORS policy doesn't create a new risk here; this is a deliberate,
documented choice, not an oversight, and can be tightened later if Atlas ever grows
per-user state worth protecting.

## Frontend design

New `frontend/` directory at the repo root (sibling to `backend/`), a Vite + React +
TypeScript scaffold (`npm create vite@latest`). Single page, four UI states:

1. **Idle** — a URL text input + "Analyze" button.
2. **Running** — an ordered checklist of the seven pipeline stages (checking off as
   `GET /jobs/{id}` reports each one reached) plus an elapsed-time counter. Polls
   every 1s.
3. **Done** — renders the returned Markdown via `react-markdown` + `remark-gfm`
   (for the report's tables). Mermaid fenced code blocks are rendered specially: a
   custom `react-markdown` code-block component detects a ```` ```mermaid ```` block
   and renders it via the `mermaid` npm package instead of as a plain code block.
   A "New Analysis" button returns to Idle.
4. **Error** — the job's `error` string plus a "Try Again" button back to Idle.

No routing library (one page, no navigation), no component/CSS framework — plain
CSS, matching the "just enough" scope this phase is deliberately keeping to.

### Data flow

```
Idle: user submits URL
   │
   ▼
POST /jobs { repo_url }  →  { job_id }
   │
   ▼
Running: setInterval polls GET /jobs/{job_id} every 1s
   │           │
   │           ├─ status "running" → update stage checklist, keep polling
   │           ├─ status "done"    → stop polling, render markdown (state → Done)
   │           └─ status "error"   → stop polling, show error (state → Error)
```

## Error handling

Backend: `run_full_analysis` bubbles its existing exception types unchanged; both
callers (the synchronous endpoint and `_run_job`) already have to handle exactly
those types today, so no new error taxonomy is introduced. Frontend: a failed
`POST /jobs` (e.g. 400 on an invalid URL) is shown inline on the Idle screen without
transitioning to Running; a polling `fetch` failure (network blip) is retried on the
next interval tick rather than immediately surfaced as an error, since a single
dropped poll isn't the same as the job itself failing.

## Testing

- **`jobs.py`**: unit tests for `create_job`/`update_job`/`get_job` against a real
  temporary SQLite file (via `tmp_path`), covering the full status lifecycle and a
  lookup miss.
- **`report_pipeline.py`**: a test confirming `run_full_analysis` produces the same
  `DocumentationResponse` shape `/documentation` already returns (reusing the
  existing `fastapi_repo` fixture and clone-monkeypatching pattern), and that
  `on_stage` is called with every expected stage name in order.
- **`main.py`**: `POST /jobs` + `GET /jobs/{id}` API tests polling a job through to
  completion (mocked clones, no live network — same pattern as every existing API
  test), plus a 404-on-unknown-job-id test and a 400-on-invalid-URL test.
- **`/documentation`'s (and `/analyze`'s) *behavior* is unchanged, but three
  existing tests need mechanical updates, not because behavior changed but because
  Python resolves a monkeypatched name in the module that actually calls it: moving
  `_iter_source_files`/`_MAX_FILE_SIZE_BYTES`/`_MAX_FILES_PER_REPO` and the
  clone-and-analyze pipeline into `report_pipeline.py` means tests that patched
  `app.main.shallow_clone`, `app.main.clone_with_history`, or
  `app.main._MAX_FILES_PER_REPO` to intercept `/documentation`'s (or the moved
  constants') behavior must patch `app.report_pipeline.*` instead — `/analyze`'s own
  handler stays in `main.py` untouched, so its monkeypatches are unaffected. Exactly
  three tests need this: `test_analyze_skips_oversized_file_and_keeps_others`
  (import path only), `test_analyze_stops_walking_after_max_file_count` (monkeypatch
  path), `test_documentation_returns_markdown_report` (both monkeypatch paths).
- **Frontend**: Vitest + React Testing Library covering the four UI states with a
  mocked `fetch` (Idle → submit → Running with a mocked in-flight job → Done
  rendering known markdown; and a separate Error-state test). No live backend or
  live network in frontend tests.
- **Manual real-repo validation** (per the process change adopted after Phase 4):
  after implementation, actually run the frontend against the real backend for at
  least one real GitHub URL and confirm the full flow — submit, watch stages
  progress, see the rendered report — works end-to-end, not just that its unit
  tests pass.

## Tech stack (this phase)

Backend: no new Python dependencies (`sqlite3`, `concurrent.futures`, `uuid` are all
stdlib); `fastapi.middleware.cors.CORSMiddleware` ships with the `fastapi` package
already installed. Frontend (new): `react`, `react-dom`, `vite`, `typescript`,
`react-markdown`, `remark-gfm`, `mermaid`; `vitest` + `@testing-library/react` for
tests.

## Out of scope for this phase (explicitly deferred)

Job history/listing UI, job cancellation/retry, auth, multi-instance job workers,
a multi-panel/interactive-graph dashboard, SSE streaming, and any visual design
system beyond plain functional CSS.
