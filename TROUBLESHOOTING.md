# Troubleshooting

## Backend won't start: `tree_sitter_languages` install/import errors

`tree-sitter-languages` doesn't publish wheels for every Python version.
Use **Python 3.12** for the backend venv, not whatever your system default
is (this project targets 3.12 specifically for that reason).

```bash
cd backend
python3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
```

## Backend crashes immediately on startup with `ConfigError`

This is intentional, not a bug — see `backend/app/config.py`. Two cases:

- `ATLAS_ENV=production` with no `ATLAS_ALLOWED_ORIGINS` set: the app
  refuses to start rather than silently allow all origins. Set
  `ATLAS_ALLOWED_ORIGINS` to your real frontend origin(s).
- `ATLAS_LOG_LEVEL` set to something other than `DEBUG`/`INFO`/`WARNING`/
  `ERROR`/`CRITICAL`: fix the typo.

See `DEPLOYMENT.md` for the full environment variable reference.

## `POST /analyze` / `/documentation` / `/jobs` returns 422

The request body's `repo_url` is either missing, not a `https://github.com/owner/repo`
URL, or over 300 characters. Check the response body's `detail` field —
FastAPI returns exactly which field failed validation.

## `POST /jobs` returns 429 immediately

Two independent things can cause this — check the response `detail` to
tell them apart:

- **"Too many analyses are already in progress"** — the global
  concurrency cap (8 by default) is full. Wait for existing jobs to
  finish, or raise `_MAX_ACTIVE_JOBS` in `main.py` if your hardware can
  take it.
- **"Too many requests from this client"** — you've hit the per-client
  rate limit (20 requests/60s). Check the `Retry-After` response header.
  Note: behind a reverse proxy, this limiter can end up shared across
  *all* clients — see the production-security-hardening design doc.

## A job is stuck in `queued`/`running` forever

There's no hard timeout on the analysis phase itself (see the "hard CPU
timeout" section of the production-security-hardening design doc for
why). If a job seems stuck:

- Check the backend logs for `job <id> stage timings` — it logs even on
  failure, so you can see which stage it was in.
- A pathologically large repo can still take a long time even with the
  file-count/size caps; this is a known v1 limitation, not necessarily a
  bug.

Stuck jobs are never silently deleted by the retention cleanup — see
`jobs.cleanup_stale_jobs`, which explicitly only removes finished (`done`/
`error`) jobs.

## Frontend loads but every request fails / CORS error in the browser console

- Confirm the backend is actually running and reachable at whatever
  `VITE_API_BASE` the frontend was built with (default
  `http://127.0.0.1:8000` — this is baked in at **build** time for Vite,
  not read at runtime; changing it means rebuilding the frontend).
- Confirm the backend's `ATLAS_ALLOWED_ORIGINS` includes the frontend's
  actual origin. In development with no env vars set, the backend already
  defaults to `http://localhost:5173`/`:4173` — if you're serving the
  frontend from a different port, that's the mismatch.

## `docker compose up --build` fails building the frontend image

If you see errors about a native binary for the wrong platform (e.g. a
`win32`/`darwin` binding inside an Alpine Linux build), check that
`frontend/.dockerignore` exists and excludes `node_modules` — without it,
your host's platform-specific `node_modules` gets copied into the Linux
build stage and clobbers the freshly `npm ci`'d Linux one. This was a
real bug caught during this project's own Docker work; the `.dockerignore`
fix is already in the repo, but if you've customized the Dockerfile,
double-check it's still being respected.

## A quality/architecture score is way lower than expected on a repo I know is fine

Check the `## Risk Areas` section of the report — an unusually low score
is almost always driven by circular-import clusters (module cycles a
project may not realize it has) or a batch of high-complexity functions,
both listed with file:line references. The scores are heuristic signals,
not guarantees — see the report's own "Analysis Coverage" footer for the
full list of known limitations (no CommonJS `require(variable)` support
for dynamic paths, pattern-based security scanning, etc.).

## Where to look next

- `DEPLOYMENT.md` — environment variables, Docker, production checklist.
- `ARCHITECTURE.md` — module responsibilities and request flow.
- `docs/superpowers/specs/` — the design doc behind every feature,
  including explicitly documented known limitations for each.
