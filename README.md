# Atlas

[![CI](https://github.com/Justin300507/atlas/actions/workflows/ci.yml/badge.svg)](https://github.com/Justin300507/atlas/actions/workflows/ci.yml)
[![Docker validate](https://github.com/Justin300507/atlas/actions/workflows/docker-validate.yml/badge.svg)](https://github.com/Justin300507/atlas/actions/workflows/docker-validate.yml)

Software Intelligence Platform — paste a GitHub repo, get a full engineering
review instead of a chatbot.

Atlas analyzes GitHub repositories to reveal architecture, dependency
relationships, code quality, Git history insights, security findings, and
engineering documentation — using deterministic software analysis, not an
LLM guessing at your code.

Given a public GitHub URL, Atlas clones it and produces:

- **Repository Intelligence** — stack/language/framework/deployment detection.
- **Architecture Graph** — a module/import/route dependency graph.
- **Code Quality Engine** — circular imports, long/complex functions, naming
  issues, rolled into maintainability/architecture scores.
- **Security Scanner** — deterministic checks for hardcoded secrets, dangerous
  execution, and unsafe deserialization.
- **Git Intelligence** — file churn, bug-fix hotspots, ownership, and
  co-change patterns from commit history.
- **Documentation Generator** — a single Markdown report combining all of the
  above, with a Mermaid dependency diagram.

All deterministic, static analysis — no LLM calls in the pipeline itself.
See two real generated reports in [`docs/examples/`](docs/examples/) (a
Python CLI framework and a CommonJS Node.js server).

## Screenshots

| | |
|---|---|
| ![Idle screen](docs/screenshots/idle.png) | ![Analysis in progress](docs/screenshots/running.png) |
| ![Generated report](docs/screenshots/report-light.png) | ![Generated report, dark mode](docs/screenshots/report-dark.png) |

## Running it

- **Quick start**: `docker compose up --build` — see [`DEPLOYMENT.md`](DEPLOYMENT.md).
  The compose stack (build, backend healthcheck, frontend serving) is
  validated on every push via [`docker-validate.yml`](.github/workflows/docker-validate.yml) —
  no local machine in dev has Docker installed, so CI is the real check.
- **Backend only**: see [`backend/README.md`](backend/README.md). Once running,
  interactive API docs are at `http://127.0.0.1:8000/docs` (Swagger UI, auto-generated).
- **Frontend only**: `cd frontend && npm install && npm run dev` (needs the
  backend running; see `VITE_API_BASE` in `DEPLOYMENT.md`).

The frontend is a paste-a-URL flow: submit a repo, watch per-stage progress,
get back the rendered report. It survives a page refresh mid-analysis.

## Documentation

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — module responsibilities, request-flow diagram.
- [`DEPLOYMENT.md`](DEPLOYMENT.md) — environment variables, Docker, production checklist.
- [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md) — common setup/runtime issues.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — local setup, test/lint commands, PR conventions.
- [`FAQ.md`](FAQ.md) — what Atlas is/isn't, how it was validated, and a full
  known-limitations list (security scanner blind spots, scoring caveats,
  size caps, the rate limiter's known reverse-proxy gap).
- [`ROADMAP.md`](ROADMAP.md) — what's shipped and validated vs. planned.
- [`CHANGELOG.md`](CHANGELOG.md) — what's shipped, grouped by milestone.
- [`SECURITY.md`](SECURITY.md) — how to report a vulnerability.
- [`docs/examples/`](docs/examples/) — real generated reports.
- [`docs/benchmarks/`](docs/benchmarks/) — measured performance and
  real-repository validation results.
- `docs/superpowers/specs/` — a design doc per feature, including explicitly
  documented known limitations for each (source material for `FAQ.md`).

## Project layout

- `backend/` — FastAPI app (`app/`), pytest suite (`tests/`), benchmarking
  scripts (`scripts/`, see `docs/benchmarks/`).
- `frontend/` — React + Vite + TypeScript.
- `docs/superpowers/specs/` — design docs, one per phase/feature.
- `docs/superpowers/plans/` — implementation plans for earlier phases.

## Not yet built

AI Architect (natural-language Q&A grounded in the dependency graph),
Technical Debt Analyzer, Performance Analyzer, AI Mentor. See
[`ROADMAP.md`](ROADMAP.md) for what each would involve and why the
backend is frozen on these for now, and [`FAQ.md`](FAQ.md) for known
limitations in what *is* built (e.g. the CORS/rate-limiting posture
documented in the production-security-hardening and CORS-hardening
specs).
