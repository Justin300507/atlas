# Atlas: CORS Hardening (v1)

## Problem

`main.py` hardcodes `allow_origins=["*"]`. That was a deliberate v1 choice
(see commit `598ab6b`'s message: "CORS is deliberately wide open... so any
cross-origin page can call `POST /jobs`") mitigated only by a concurrency
cap and, as of the previous phase, per-client rate limiting. Neither
actually restricts *who* can call the API from a browser — they only bound
*how much* damage an unrestricted caller can do. Before a public beta,
Atlas needs an environment-aware CORS policy: permissive enough for local
development, strict by default, and unable to accidentally ship
wide-open in production.

## Architecture

New `backend/app/config.py`, one pure function:
`resolve_cors_origins(env: Mapping[str, str] | None = None) -> list[str]`.

Reads two variables (defaulting to `os.environ` when `env` isn't passed,
so it's easy to unit test in isolation):

- `ATLAS_ENV` — `"development"` (default if unset) or `"production"`.
  Anything else raises `ConfigError` at startup.
- `ATLAS_ALLOWED_ORIGINS` — comma-separated list of origins
  (`scheme://host[:port]`, no path, no trailing slash).

Behavior:
- **`development`** (default): if `ATLAS_ALLOWED_ORIGINS` is unset, falls
  back to the frontend's known local dev/preview origins
  (`http://localhost:5173`, `http://127.0.0.1:5173` — Vite's default dev
  port — plus `:4173` for `vite preview`). If it *is* set, that list is
  used instead (lets a developer test against a different frontend origin
  without editing code).
- **`production`**: `ATLAS_ALLOWED_ORIGINS` is **required**. Missing, empty,
  or containing a literal `"*"` all raise `ConfigError` — the app refuses
  to start rather than silently falling back to a permissive default. This
  is the "fail safely" requirement: a misconfigured production deploy
  should crash loudly at boot, not serve traffic with an open CORS policy
  nobody intended.
- Every configured origin (dev override or production list) is validated
  against `scheme://host[:port]` with no path/trailing slash — CORS origins
  don't include a path per the Fetch/CORS spec, and a stray trailing slash
  is a real, easy-to-make typo that would silently never match any
  browser-sent `Origin` header, producing a confusing "CORS is broken"
  debugging session instead of a clear startup error.

`main.py` calls `resolve_cors_origins()` once at import time and passes the
result straight to `CORSMiddleware(allow_origins=...)`. A misconfiguration
throws before the app object finishes constructing — before `uvicorn` ever
binds a port.

## Alternatives considered

- **Silently falling back to `["*"]` or to the dev list when production
  config is missing** — rejected; this is exactly the accidental-insecure-
  default scenario the "fail safely" requirement exists to prevent. Loud
  and immediate beats quiet and permissive.
- **A general-purpose settings framework (pydantic-settings, python-decouple)**
  — rejected for v1: two env vars and one validation function don't
  justify a new dependency; revisit if config surface grows (e.g. once
  Priority 6 deployment work adds more settings).
- **Wildcard subdomain matching (e.g. `*.atlas.dev`)** — not implemented;
  `CORSMiddleware`'s `allow_origins` doesn't support wildcarding
  sub-patterns without switching to `allow_origin_regex`, and there's no
  concrete subdomain topology yet to design against. Exact-match origins
  are sufficient for a single frontend origin per environment today.

## Edge cases

- `ATLAS_ENV` is compared case-insensitively (`"Production"`,
  `"PRODUCTION"` all work) since env vars are frequently set by humans or
  platform UIs with inconsistent casing.
- Whitespace and empty entries in a comma-separated `ATLAS_ALLOWED_ORIGINS`
  (trailing commas, stray spaces) are trimmed and dropped rather than
  producing a confusing empty-string "origin."
- An `ATLAS_ALLOWED_ORIGINS` value that parses to zero valid entries in
  `production` mode is treated identically to an unset variable (still
  raises `ConfigError`) — an all-whitespace or all-comma value shouldn't
  sneak past the "must be configured" check.
