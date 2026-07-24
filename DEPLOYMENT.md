# Deploying Atlas

## Live deployment (Vercel + Railway)

The public instance runs frontend on **Vercel** (static Vite build, deployed
straight from source, no Docker) and backend on **Railway** (deployed from
`backend/Dockerfile` via the GitHub integration, root directory set to
`backend`). This split was chosen because the backend genuinely needs a
persistent container — it shells out to `git clone` as a real subprocess
against a writable temp directory, and jobs can run 10s-60s+ — which rules
out pure serverless/edge platforms (Vercel Functions, Cloudflare Workers,
Supabase Edge Functions all have execution-time limits and no persistent
filesystem). The frontend has no such constraint, so it runs on whichever
static host is most convenient.

**Two real issues found doing this deploy, not hypothetical:**

1. **Hardcoded port.** The backend Dockerfile's `CMD` used exec-form JSON
   (`["uvicorn", ..., "--port", "8000"]`), which never expands environment
   variables. Railway (like most container PaaS hosts) injects a dynamic
   `PORT` and routes to it — the container was unreachable until the CMD
   was switched to shell form so `${PORT:-8000}` actually expands. Local
   `docker-compose.yml` behavior is unchanged (it doesn't set `PORT`, so
   the default still applies).
2. **Root directory setting didn't apply to the build that used it.**
   Railway's dashboard "Root Directory" setting, for a monorepo-style
   GitHub-connected service, didn't take effect on the deployment that was
   in flight when it was changed, *or* on a `railway redeploy` of that same
   (pre-change) deployment object — both replayed the old build
   configuration and failed with Railway's auto-detect builder scanning the
   repo root instead of `backend/`. It only took effect on a genuinely new
   deployment triggered by a fresh commit push. If a Railway monorepo
   service keeps failing with "could not determine how to build the app"
   after setting Root Directory, don't just retry — push a new commit (even
   an empty one) to force a deployment that actually reads current service
   settings, or deploy once via `railway up` from the subdirectory directly.

**Backend on Railway, step by step (CLI-driven):**

```bash
railway login                                    # opens a browser
railway init --name atlas
railway add --repo <owner>/<repo> --branch main --service atlas-backend
# In the dashboard: atlas-backend -> Settings -> Root Directory -> backend
railway volume -s <serviceId> -e <envId> -p <projectId> add --mount-path /app/data
railway variable set ATLAS_ENV=production --service atlas-backend
railway variable set ATLAS_JOBS_DB_PATH=/app/data/atlas_jobs.db --service atlas-backend
railway variable set ATLAS_ALLOWED_ORIGINS=https://<your-frontend-domain> --service atlas-backend
railway domain --service atlas-backend           # generates a public *.up.railway.app URL
```

**Frontend on Vercel, step by step:**

```bash
cd frontend
vercel login
vercel link
vercel env add VITE_API_BASE production   # paste the Railway backend URL from above
vercel env add VITE_API_BASE preview
vercel --prod
```

`VITE_API_BASE` must be set on Vercel *before* the first build — Vite bakes
it in at build time (see the table below), so setting it after deploying
means rebuilding, not just changing a runtime setting.

After both are live, go back and update the Railway `ATLAS_ALLOWED_ORIGINS`
to the real Vercel URL (there's an unavoidable chicken-and-egg step here:
you don't know the frontend's URL until after its first deploy).

## Quick start (docker-compose)

```bash
docker compose up --build
```

- Backend: http://localhost:8000
- Frontend: http://localhost:5173

This is a development-shaped default (`ATLAS_ENV=development`, origins
pointed at `localhost`). For a real deployment, override the environment
variables below — don't just run the defaults against a public host.

## Environment variables (backend)

| Variable | Default | Purpose |
|---|---|---|
| `ATLAS_ENV` | `development` | `development` or `production`. In `production`, `ATLAS_ALLOWED_ORIGINS` is required — the app refuses to start without it rather than falling back to an insecure default. See `docs/superpowers/specs/2026-07-23-cors-hardening-design.md`. |
| `ATLAS_ALLOWED_ORIGINS` | local dev/preview origins | Comma-separated list of allowed CORS origins (`scheme://host[:port]`, no path, no trailing slash). Required in production. |
| `ATLAS_LOG_LEVEL` | `INFO` | Standard Python log level name (`DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL`). |
| `ATLAS_JOBS_DB_PATH` | `<repo>/backend/atlas_jobs.db` | Where the SQLite job-status database lives. Set this to a mounted volume path in any deployment where job history should survive a container restart (docker-compose.yml already does this). |

## Environment variables (frontend)

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE` | `http://127.0.0.1:8000` | The backend's URL. **Baked in at build time**, not read at container runtime — passed as a Docker build ARG in `frontend/Dockerfile`/`docker-compose.yml`, not a runtime `-e` flag. Changing it means rebuilding the frontend image. |

## Production checklist

- [ ] Set `ATLAS_ENV=production` and `ATLAS_ALLOWED_ORIGINS` to your real frontend origin(s). The app will refuse to start otherwise.
- [ ] **Read the rate limiter's known limitation** before trusting it: it keys on the TCP peer's address, which collapses to one shared budget for the whole service behind any reverse proxy or typical PaaS deployment. See `docs/superpowers/specs/2026-07-23-production-security-hardening-design.md`. If you're deploying behind a proxy, either put the limiter in front of it or configure a trusted-proxy header — don't assume it's already protecting you per-client.
- [ ] Mount a persistent volume for `ATLAS_JOBS_DB_PATH` (docker-compose.yml does this by default) if job history should survive restarts.
- [ ] Rebuild the frontend image with `VITE_API_BASE` pointed at your real backend URL.
- [ ] Point your reverse proxy / TLS termination in front of both services — neither Dockerfile does TLS itself.

## Building images individually

```bash
docker build -t atlas-backend ./backend
docker build -t atlas-frontend --build-arg VITE_API_BASE=https://api.example.com ./frontend
```

## Health check

`GET /health` on the backend returns HTTP 200 with `{"status": "ok"}`,
or HTTP 200 with `{"status": "degraded"}` if its database check fails —
**the status code is always 200 either way**, so a probe that only
checks the HTTP status won't see a degraded DB dependency as unhealthy.
Check the response body's `status` field, not just the status code, if
that distinction matters for your orchestration setup.
