# Atlas Backend

## Setup

**Requires Python 3.12** — `tree-sitter-languages` doesn't publish wheels
for every Python version, and a plain `python`/`python3` on your PATH
may resolve to something newer that this install will silently fail
against. Use `python3.12` (or `py -3.12` on Windows) explicitly:

```bash
cd backend
python3.12 -m venv .venv       # py -3.12 -m venv .venv on Windows
.venv/Scripts/python -m pip install -r requirements.txt
```

If you already created a venv with the wrong Python version, delete
`.venv` and recreate it with the command above — see
[`../TROUBLESHOOTING.md`](../TROUBLESHOOTING.md) if `pip install` still
fails.

## Run

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
```

## Linting

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m ruff check .
```

Configured in `ruff.toml` for pyflakes (unused imports/vars, undefined
names) and import ordering only -- not full pycodestyle line-length
enforcement, since this codebase predates a line-length convention and
retroactively enforcing one would mean reformatting existing code with no
behavioral benefit. `tests/fixtures/` is excluded: those files are
deliberately-crafted parser test inputs (e.g. an intentionally-unused
import that `code_parser`'s tests exercise on purpose), not real
application code.

## Configuration

Two environment variables control CORS (see
`docs/superpowers/specs/2026-07-23-cors-hardening-design.md` for the full
design):

- `ATLAS_ENV` — `development` (default) or `production`.
- `ATLAS_ALLOWED_ORIGINS` — comma-separated list of allowed origins
  (`scheme://host[:port]`, no path or trailing slash).

In `development`, if `ATLAS_ALLOWED_ORIGINS` is unset, Atlas defaults to
the frontend's local dev/preview origins (`http://localhost:5173`,
`http://127.0.0.1:5173`, `:4173`). In `production`,
`ATLAS_ALLOWED_ORIGINS` is **required** — the app refuses to start rather
than fall back to an insecure default (missing, empty, or `*` all raise a
startup error). Example for a real deployment:

```bash
export ATLAS_ENV=production
export ATLAS_ALLOWED_ORIGINS="https://atlas.example.com"
.venv/Scripts/python -m uvicorn app.main:app
```

## Try it

```bash
curl -X POST http://127.0.0.1:8000/analyze \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\": \"https://github.com/octocat/Hello-World\"}"
```

The response now also includes a `quality` field: `overall_score`,
`maintainability_score`, `architecture_score`, and a list of `issues` (circular
imports, long functions, high-complexity functions, naming violations).

## Git Intelligence

```bash
curl -X POST http://127.0.0.1:8000/git-intelligence \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\": \"https://github.com/octocat/Hello-World\"}"
```

Clones a bounded window of commit history (the last 500 commits by default, rather
than full history) and returns `commits_analyzed`, `history_truncated` (true if the
repo has more history than was analyzed), and three deterministic rollups: `churn`
(commit count and bug-fix-commit count per file, top 20), `ownership` (top author and
ownership ratio per file, top 20), and `co_changes` (file pairs that change together
in the same commit, top 20).

## Documentation Generator

```bash
curl -X POST http://127.0.0.1:8000/documentation \
  -H "Content-Type: application/json" \
  -d "{\"repo_url\": \"https://github.com/octocat/Hello-World\"}"
```

Runs the `/analyze` pipeline and the `/git-intelligence` pipeline internally (two
clones, same as calling both endpoints separately) and assembles the results into a
single Markdown report in the response's `markdown` field: Executive Summary,
Architecture Overview, Directory Guide, API Reference, a Mermaid Dependency Diagram
(capped at 40 modules for readability), Risk Areas (from the quality report),
Recent High-Churn Components (from git intelligence), and a closing Analysis
Coverage section disclosing what's currently supported (Python, ES Module and
CommonJS `require()` imports, git history, repo structure, security scanning)
versus known limitations (non-literal import targets can't be resolved
statically; scores are heuristic signals, not guarantees; large repos are
capped — see `FAQ.md` for the full list). Purely deterministic — no LLM call,
no data beyond what the other three endpoints already compute.

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

## Test

```bash
# fast suite (no network)
.venv/Scripts/python -m pytest tests/ -m "not slow"

# full suite including real-network integration test
.venv/Scripts/python -m pytest tests/
```
