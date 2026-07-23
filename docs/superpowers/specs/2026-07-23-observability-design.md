# Atlas: Observability (v1)

## Problem

Job-level logging (per-stage timing) already exists, but there's no way
to correlate a specific HTTP request with anything in the logs — no
request ID, no access log at all. Separately, `GET /health` returns a
hardcoded `{"status": "ok"}` regardless of whether the app can actually
reach its own database — a health check that can't detect its own broken
dependency isn't a useful liveness/readiness signal for an orchestrator.

## Architecture

**Request IDs** (`main.py`): a `BaseHTTPMiddleware` generates a UUID per
request (or reuses an inbound `X-Request-ID` header, so a caller/proxy
that already assigns one is respected rather than overwritten), stores it
on `request.state`, and returns it in the response's `X-Request-ID`
header so a client-side error report can reference the exact request. An
access-log line (method, path, status code, duration in ms, request ID)
is logged for every request that completes normally or via `HTTPException`
— the first general-purpose log line in the app beyond the existing
per-job stage timing. A request that raises an unhandled exception is a
separate case: `BaseHTTPMiddleware`'s `call_next` raises rather than
returning a response for that path, so there's no response object left to
attach `X-Request-ID` to. The middleware still logs (a distinct
"(unhandled exception)" line, since that's exactly the case where
correlation matters most) before re-raising, but the client-facing 500
itself won't carry the header — closing that gap fully would mean
constructing our own error response for every unhandled exception, which
changes error-handling behavior more than this phase's scope justifies.

**Health check** (`main.py`): `GET /health` now actually opens a
connection to the jobs database (the app's only real runtime dependency)
and reports `{"status": "ok" | "degraded", "checks": {"database": "ok" | "error: ..."}}`
instead of a hardcoded constant. Returns `200` either way — a health
*check* should report degraded status without necessarily failing the
HTTP call, since an orchestrator's liveness probe and a human reading the
body are different consumers of the same endpoint.

## Alternatives considered

- **A dedicated APM/tracing setup (OpenTelemetry)** — rejected for the
  same reason as the earlier performance-instrumentation phase: one
  request path doesn't justify the infrastructure yet. A request ID +
  access log line is the proportionate amount of observability for the
  app's current scale.
- **Failing `/health` with a non-200 status when the DB check fails** —
  rejected; conflates "the check ran and found a problem" with "the
  endpoint itself is broken." Returning 200 with `status: "degraded"` in
  the body lets both a simple uptime check (which usually only looks at
  the HTTP status) and a more detailed monitor (which reads the body)
  each get useful signal without one breaking the other.

## Edge cases

- An inbound `X-Request-ID` header is trusted as-is (not validated as a
  UUID) — it's an opaque correlation token for logs, not a security
  boundary, so accepting any caller-supplied string is fine.
- The health check's DB probe reuses the same `jobs._connect()` path as
  everything else (including the parent-directory-creation fix from the
  deployment-readiness phase), so it can't fail merely because the DB
  file/directory doesn't exist yet.
- `/health`'s response body never includes the raw exception message —
  only `type(exc).__name__`. `/health` is unauthenticated, and the full
  message can include the database's filesystem path (confirmed via
  independent review, which reproduced a real path-disclosure with the
  first draft's `f"error: {exc}"`). The full message still goes to the
  logs via `logger.error`, just not the response.
- `request.state.request_id` is only consumed by this middleware's own
  logging today. It does **not** reach the per-job stage-timing log line
  (`_run_job`), since job execution happens later on a `ThreadPoolExecutor`
  thread, decoupled from the original `Request` object — correlating a
  `POST /jobs` request with its eventual job-completion log would need
  passing the request ID through to the job record itself, not attempted
  in this pass.
