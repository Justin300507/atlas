# Atlas: Deployment Readiness (v1)

## Problem

Atlas has no way to actually be deployed today: no Dockerfile for either
service, no docker-compose wiring them together, and the root `README.md`
is still describing "Phase 1" (stale — Code Quality, Git Intelligence,
Documentation Generator, Security Scanner, and the frontend are all
shipped). Separately, a concrete bug was found while designing this
phase: `_run_job`'s stage-timing log line (added in the performance phase)
is silently dropped in practice — `logging.getLogger().handlers` is empty
and the root logger's effective level is `WARNING`, so `logger.info(...)`
never reaches anything outside of pytest's `caplog` (which installs its
own capturing handler regardless of app config). Nothing in production
would ever configure real log output.

## Architecture

**Logging** (`backend/app/config.py` gains `resolve_log_level`,
`backend/app/main.py` calls `logging.basicConfig(...)` at import time):
`ATLAS_LOG_LEVEL` env var (default `"INFO"`), validated against Python's
standard level names — an unrecognized value raises `ConfigError` at
import time, same fail-fast posture as the CORS config. `basicConfig` is
called once, at the same import-time point CORS is resolved, with a
timestamp/level/logger-name/message format suitable for container log
aggregation (plain text, one line per record — no structured-JSON logging
framework, since there's exactly one log call site in the whole app today
and that would be over-engineering for it).

**Docker**: `backend/Dockerfile` (`python:3.12-slim` — pinned because
`tree-sitter-languages` has no 3.14 wheels, a constraint already noted in
project memory; installs `git` via apt since `cloner.py` shells out to
it), `frontend/Dockerfile` (multi-stage: `node:20-alpine` build stage,
`nginx:alpine` to serve the static `dist/` output), and a root
`docker-compose.yml` wiring both with the CORS/log-level env vars. The
frontend's `VITE_API_BASE` is a Vite *build-time* env var (baked into the
static JS bundle, not readable at container runtime), so it's passed as a
Docker build ARG, not a plain runtime environment variable — getting this
wrong would silently produce a frontend image that always points at
whatever `VITE_API_BASE` was during `docker build`, regardless of
`docker run -e` overrides.

**Docs**: root `README.md` rewritten to describe the actual current state
(all five shipped phases, links to `backend/README.md`,
`frontend/` setup, and the new `DEPLOYMENT.md`) instead of the stale
Phase-1-only description. New root `DEPLOYMENT.md`: docker-compose quick
start, the full environment variable reference (`ATLAS_ENV`,
`ATLAS_ALLOWED_ORIGINS`, `ATLAS_LOG_LEVEL`, `VITE_API_BASE`), and a
pre-launch checklist that explicitly cross-references two things already
documented elsewhere so they don't get missed: the rate limiter's
reverse-proxy caveat (production-security-hardening design doc) and that
`atlas_jobs.db` needs a persistent volume if job history should survive a
container restart.

## Alternatives considered

- **Kubernetes manifests / Helm chart** — rejected for v1; no evidence
  Atlas is being deployed at that scale yet, and docker-compose covers
  "one backend + one frontend" which is the actual current architecture.
- **A structured logging library (structlog, python-json-logger)** —
  rejected; one log call site doesn't justify a new dependency.
  `logging.basicConfig` with a plain format string is proportionate;
  revisit if/when there are enough log call sites that grep-based log
  reading in production stops being tractable.
- **Runtime-configurable `VITE_API_BASE` (e.g. window-injected config,
  runtime env substitution in the nginx stage)** — rejected for v1;
  correctly documenting the build-time-ARG requirement is simpler than
  adding a runtime-config-injection mechanism for a single URL that's
  already known at build/deploy time in a docker-compose setup. Worth
  revisiting only if Atlas ever needs one built image promoted across
  multiple environments without rebuilding.

## Edge cases

- `ATLAS_LOG_LEVEL` is validated case-insensitively (`"debug"`, `"DEBUG"`
  both work), consistent with `ATLAS_ENV`'s existing handling.
- `docker-compose.yml`'s backend service mounts a named volume for
  `atlas_jobs.db`'s parent directory so job history (and the job-cleanup
  behavior added in the security-hardening phase) survives a container
  restart — without it, every restart silently resets job state, which
  would be confusing rather than dangerous, but worth avoiding by default.
