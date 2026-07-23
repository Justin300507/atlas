# Deploying Atlas

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

`GET /health` on the backend returns `{"status": "ok"}` — use it for
container orchestration liveness/readiness probes.
