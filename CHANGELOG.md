# Changelog

Format loosely follows [Keep a Changelog](https://keepachangelog.com/).
Atlas doesn't tag point releases yet — this file starts at the Public
Beta launch and groups by capability milestone, not by commit; see
`git log` for the full history.

## [Unreleased]

### Added (v1.2)

- **Repository Comparison** — `POST /compare` diffs two completed
  jobs' snapshots (`AnalysisSnapshot`, persisted via a real schema
  migration on the existing jobs table) for architecture/quality/
  security/git/semantic changes. Documented significance thresholds
  (±5 points score noise floor, new circular clusters and critical/
  important security findings always flagged, criticality/hotspot set
  changes reported as facts, not classified good/bad). See
  `docs/superpowers/specs/2026-07-24-repository-comparison-design.md`.
  Validated against real Flask/requests snapshots end-to-end; a
  regression/improvement label-inversion bug was caught by its own
  test suite before merge, not by inspection.


### Added

- **Semantic Repository Intelligence Engine** — architecture metrics
  (fan-in/out, betweenness/closeness centrality, articulation points,
  bridges), dependency criticality ranking, deterministic layer
  detection (reports "insufficient evidence" rather than guessing),
  engineering hotspots (churn × centrality × complexity), and
  coupling/architectural-smell detection (god modules, facades,
  utility dumping, isolated components, layering violations). New
  report sections: Architecture Health, Dependency Criticality,
  Subsystem Overview, Engineering Hotspots, Coupling & Architectural
  Smells, plus two new Mermaid diagrams. See
  `docs/superpowers/specs/2026-07-24-semantic-repository-intelligence-design.md`
  for every algorithm/threshold decision. Validated against Django,
  Flask, and requests; findings cross-checked against real domain
  knowledge (e.g. `django/utils/functional.py` correctly flagged as
  Django's most-imported utility module).


Post-launch operations pass, same day as the Public Beta release —
found by dogfooding and live walkthroughs, not by user reports (the
repo had zero issues/PRs/discussions at the time this section was
written; see the operations report for that day for the honest caveat
on what "evidence-driven" could actually mean yet).

### Fixed

- Security scanner flagged its own source comments (explaining what
  `eval()`/`exec()`/`pickle.load()` detection does) as if they were
  live dangerous code — found by running Atlas on its own repository.
  Full-line comments are now skipped for the execution/deserialization
  checks (not for secret detection — a commented-out secret is still a
  real leaked value).
- The actual product UI's browser tab title was the unmodified Vite
  scaffold default ("frontend"), not "Atlas" — found by loading the app
  and looking at the tab, not just the marketing landing page.
- Startup logs confirmed nothing about resolved configuration
  (`ATLAS_ENV`, `ATLAS_ALLOWED_ORIGINS`, `ATLAS_LOG_LEVEL`) — an
  operator had no way to confirm a production env var was actually read
  short of triggering a real cross-origin request. Now logged as one
  INFO line at startup.
- `docker-validate.yml` had a real, reproducible CI race: the frontend
  container had no Docker healthcheck, so `docker compose up --wait`
  considered it "ready" the moment the container started, not once
  nginx had actually finished its entrypoint scripts and started
  serving. Root-caused from the actual `docker compose logs` output of
  a failed run, not assumed. Added a curl-based healthcheck (installed
  explicitly rather than assumed present) plus a bounded retry on the
  workflow's own check as defense-in-depth. Verified fixed via a live
  CI run, not just static review.
- SQLite "database is locked" under concurrent job writes — the
  semantic-analysis engine's extra per-job write tipped already-tight
  write contention over the default busy-timeout on a loaded CI
  runner. Fixed with WAL mode + a longer timeout; that fix then hit
  its own real issue (40 threads racing to switch a brand-new file to
  WAL mode can collide on Windows), fixed with a bounded retry around
  just that first-time switch.

### Dependencies

First Dependabot run (`.github/dependabot.yml`, added this session)
opened 10 PRs. Triaged individually rather than bulk-merged:

- Merged 9: GitHub Actions (`checkout`, `setup-node`, `setup-python` to
  v7), `pydantic`, `fastapi`, `pytest` (8→9), `ruff`, `typescript`
  (6→7), `@types/node` — all fully green across backend/frontend/
  docker-validate CI, then re-verified locally after merge (full test
  suites, lint, typecheck, build all still pass with the bumped
  versions installed).
- Closed 1: `tree-sitter` 0.21.3→0.26.0. Confirmed via CI logs to break
  the parser (`tree-sitter-languages` 1.10.2 depends on a `Language()`
  constructor signature removed in tree-sitter 0.22+) — 17 real test
  failures, not a fluke. `tree-sitter==0.21.3` is pinned exactly for
  this reason; left as a known constraint, not merged.

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
