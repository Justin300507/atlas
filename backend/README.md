# Atlas Backend (Phase 1: Repository Intelligence)

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Run

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
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

## Test

```bash
# fast suite (no network)
.venv/Scripts/python -m pytest tests/ -m "not slow"

# full suite including real-network integration test
.venv/Scripts/python -m pytest tests/
```
