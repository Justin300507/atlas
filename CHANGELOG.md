# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Atlas doesn't tag point releases yet — this file starts at the Public
Beta launch and groups by capability milestone, not by commit; see
`git log` for the full history.

## [Public Beta] - 2026-07-24

First public release. Everything below is implemented and validated
against real repositories (see `docs/benchmarks/`), not just unit
tested.

### Added

- **Repository Intelligence** — stack/language/framework/deployment
  detection.
- **Architecture Graph** — Python and JS/TS/JSX/TSX import + route
  dependency graph (tree-sitter + NetworkX).
- **Code Quality Engine** — circular imports (strongly-connected
  components), long/complex functions, naming-convention checks, rolled
  into maintainability/architecture/overall scores.
- **Security Scanner** — deterministic checks for hardcoded secrets,
  dangerous exec, and unsafe deserialization, with test/fixture-path
  findings demoted rather than hidden.
- **Git Intelligence** — file churn, bug-fix-commit hotspots, ownership,
  and co-change patterns from up to 500 commits of history.
- **Documentation Generator** — a single Markdown report combining all
  of the above, with a capped Mermaid dependency diagram and an
  Analysis Coverage disclosure section.
- **Frontend** — React/Vite paste-a-URL flow with live per-stage
  progress, dark mode, and refresh/reconnect recovery.
- **Async job pipeline** — `POST /jobs` + polling, SQLite-backed job
  state, per-client rate limiting, request-ID correlation through to
  job completion logs.
- **Docker deployment** — multi-stage builds for both services,
  `docker-compose.yml`, CI-validated stack boot on every push
  (`docker-validate.yml`).
- **CI** — pytest/ruff/vitest/oxlint/tsc/build all run on every push and
  PR (`ci.yml`), not just the Docker stack.
- **Documentation** — `ARCHITECTURE.md`, `DEPLOYMENT.md`,
  `TROUBLESHOOTING.md`, `CONTRIBUTING.md`, `FAQ.md` (consolidated,
  code-verified known-limitations list), `ROADMAP.md`.
- **Real-world validation** — six repos across Python/JS/TS ecosystems
  (Django, FastAPI, Flask, React, Express, requests), full generated
  reports published under `docs/benchmarks/real-world-validation-reports/`.
- **Landing page** — static GitHub Pages site (`docs/index.html`) with
  a real validation-results table, Open Graph/Twitter Card previews, and
  WCAG AA-checked contrast.
- **Community infrastructure** — issue templates (bug, false positive,
  feature request), PR template, `SECURITY.md`, `LICENSE` (MIT),
  Dependabot + secret scanning enabled.

### Fixed (during pre-launch hardening)

Selected highlights — see `docs/superpowers/specs/` for full design
docs behind each:

- Quality scores were floored at 0/100 for every real repo except the
  smallest, due to unnormalized per-issue penalties.
- The 5,000-file analysis cap counted non-source files (docs,
  translations, fixtures), starving real source coverage on repos like
  Django.
- Security scanner findings inside test/fixture files ranked as
  `critical`/`important`, indistinguishable from real risk.
- Job completion logs couldn't correlate back to the request that
  queued them (background-thread execution, no request ID threaded
  through).
- `git log` parsing crashed on commit messages with non-ASCII
  characters (Windows codepage decoding).
- Import resolution used substring matching (`"core.py".endswith("re.py")`
  → true), causing false circular-import clusters.

### Known limitations

See `FAQ.md` — not repeated here since it's the canonical source and
this file would drift out of sync with it.
