# Atlas Phase 1: Repository Intelligence + Architecture Graph

## Purpose

Atlas is an AI engineering intelligence platform: paste a repo, get a full engineering
review instead of a chatbot. This is the first of ~10 planned subsystems and is the
foundation the rest (code quality, security, AI architect, docs generator, AI mentor,
etc.) will consume. It answers two questions about a repository:

1. **What is this project built with?** (stack detection)
2. **How is it wired together?** (architecture graph: modules, imports, services,
   API routes, DB models, external API calls)

## Scope for this phase

- **Languages parsed deeply:** Python and JavaScript/TypeScript only, via Tree-sitter.
  Everything else gets coarse detection only (file extensions, known config files) —
  no deep import/route graph for other languages yet.
- **Ingestion:** public GitHub repo URL only. Backend does a shallow `git clone` into a
  temp workspace, analyzes it, deletes the workspace when done. No auth flow for
  private repos in this phase.
- **Output:** a JSON API only. No frontend UI yet — that's phase 2, once there's a
  stable contract to build against.
- **Persistence:** none. Every request re-clones and re-analyzes. No database. This
  keeps phase 1 focused on getting detection + graph-building correct; storage becomes
  a real requirement once other subsystems need to query saved results, and is
  deferred to a later phase rather than guessed at now.

## Architecture

```
POST /analyze {"repo_url": "https://github.com/owner/repo"}
        │
        ▼
 1. Clone stage      shallow git clone → temp dir (auto-cleaned via context manager)
        │
        ▼
 2. Stack detection  heuristic scan of config/manifest files
        │            (package.json, requirements.txt/pyproject.toml, Dockerfile,
        │             docker-compose.yml, alembic/migrations, etc.)
        ▼
 3. Code parsing     Tree-sitter walk of .py / .js/.jsx/.ts/.tsx files →
        │            per-file symbol tables (imports, defined functions/classes,
        │            decorators for route detection)
        ▼
 4. Graph building   NetworkX directed graph: nodes = modules/files, edges = imports;
        │            route nodes for detected API endpoints; db-model nodes for
        │            detected ORM models. Serialized to node-link JSON.
        ▼
 5. Response         { "stack": {...}, "graph": {nodes:[...], edges:[...]} }
```

### Components

- **`cloner`** — shallow-clones a repo URL into a temp dir; context-manager cleanup.
  Depends on: `git` CLI (via subprocess). Used by: API layer only.
- **`stack_detector`** — reads known manifest/config files, returns a `StackReport`
  (backend framework, frontend framework, database, auth, deployment, architecture
  style guess). Pure function: `detect(repo_path) -> StackReport`. No dependencies on
  other components — testable against fixture repos in isolation.
- **`code_parser`** — Tree-sitter wrapper. `parse_file(path) -> FileSymbols` (imports,
  defined names, decorators, calls). Depends on: tree-sitter grammars for
  Python/JS/TS. Used by graph builder only.
- **`graph_builder`** — consumes `FileSymbols` across the repo, produces a NetworkX
  `DiGraph`, then a JSON-serializable node-link representation. Depends on:
  `code_parser` output only, not on the filesystem directly.
- **`api`** — FastAPI app exposing `POST /analyze`. Orchestrates cloner → detector →
  parser → graph builder → response. Handles clone/parse errors as HTTP 4xx/5xx with
  clear messages (invalid URL, clone failure, empty/unsupported repo).

Each component is independently unit-testable against small fixture repos/files
checked into `tests/fixtures/`, without needing network access or a real clone.

## Error handling

- Malformed or non-GitHub URL → 400 with message.
- Clone failure (private/nonexistent repo, network error) → 422 with the git error
  surfaced, not swallowed.
- Repo with no recognizable stack → still returns 200 with an empty/`"unknown"` stack
  report and whatever graph could be built — analysis degrades gracefully, it doesn't
  hard-fail just because detection is inconclusive.
- Clone timeout (very large repos) → configurable timeout, 504 on exceed.

## Testing

- Unit tests for `stack_detector` against a handful of small fixture repos (a FastAPI
  one, a React+Vite one, an empty repo) checked into `tests/fixtures/`.
- Unit tests for `code_parser` against fixture source files covering imports, route
  decorators (`@app.get(...)`, Express `router.get(...)`), and ORM model classes.
- Unit tests for `graph_builder` against known `FileSymbols` inputs, asserting graph
  shape (node/edge counts, expected edges).
- One integration test that clones a small real public repo (pinned to a commit SHA
  for stability) end-to-end through the API, marked slow/network so it can be skipped
  in fast test runs.
- No live-network dependency in the default test run.

## Tech stack (this phase)

Python 3.11+, FastAPI, uvicorn, GitPython or subprocess `git`, `tree-sitter` +
language grammars for Python/JS/TS, NetworkX, Pydantic for request/response models,
pytest. React/TS frontend, PostgreSQL, ChromaDB, and the task queue from the original
tech list are deferred to later phases — not needed until there's persistence or a UI.

## Out of scope for this phase (explicitly deferred)

Frontend/UI, persistence/database, private repo auth, non-Python/JS deep parsing,
code quality scoring, security scanning, git history analysis, AI-powered Q&A. These
are later subsystems that will consume this phase's graph output.
