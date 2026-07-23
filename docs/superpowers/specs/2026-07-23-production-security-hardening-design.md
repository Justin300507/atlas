# Atlas: Production Security Hardening (v1)

## Problem

CORS is deliberately wide open (`allow_origins=["*"]`, tracked separately —
see the CORS hardening spec) and there's no auth, so any page on the
internet can call Atlas's endpoints. The only existing abuse mitigation is
a *global* concurrency cap (`_MAX_ACTIVE_JOBS = 8` on `POST /jobs`, added in
commit `598ab6b`) — it bounds total simultaneous clone/CPU work but does
nothing to stop one client from repeatedly consuming the whole budget, and
doesn't apply to `/analyze`, `/documentation`, or `/git-intelligence` at
all (each still clones + fully analyzes a repo synchronously on request).
Separately, the jobs SQLite table has no retention policy — every job ever
created stays forever, including its full markdown report, which is
unbounded growth for a public beta.

## Architecture

**Per-client rate limiting** (new `backend/app/rate_limiter.py`):
`RateLimiter(max_requests, window_seconds)` is an in-memory, thread-safe
sliding-window limiter — a dict of `deque[float]` timestamps per key behind
a `threading.Lock` (FastAPI runs sync path functions in a worker thread
pool, so this needs to be thread-safe, unlike the SQLite-backed job state
which already serializes through file-level connections). `allow(key) ->
bool` pops timestamps older than the window, then admits the call if under
`max_requests`.

Wired into `main.py` as a FastAPI dependency, keyed on `request.client.host`,
applied to all four expensive endpoints (`/analyze`, `/documentation`,
`/git-intelligence`, `/jobs`): 20 requests/60s per client. On rejection,
raises `HTTPException(429, headers={"Retry-After": "60"})` with a message
distinct from the existing global-capacity 429, so client and server logs
can tell "you personally are going too fast" apart from "the whole service
is at capacity."

**Payload validation**: `AnalyzeRequest.repo_url` gains
`Field(max_length=300)`. Real GitHub URLs are well under 100 characters;
without a bound, pydantic will happily validate (and FastAPI will fully
buffer) an arbitrarily large request body before `validate_github_url`'s
regex ever gets a chance to reject it. This turns an unbounded-payload
resource question into an automatic 422 with no custom code.

**Job cleanup** (`jobs.py`): `cleanup_stale_jobs(max_age_hours=24)` deletes
job rows older than the cutoff. Called opportunistically at the top of
`POST /jobs` (before creating the new job) rather than via a background
scheduler/cron — no new process, thread, or dependency, and cleanup volume
naturally tracks real traffic instead of running on a fixed clock no one is
watching yet.

## Alternatives considered

- **`slowapi` / Redis-backed rate limiting** — rejected for v1: single-process
  deployment, no shared state across workers yet, and the project's stated
  preference is deterministic in-house code over a new dependency where a
  ~20-line limiter suffices. Revisit if Atlas ever runs multiple worker
  processes/instances behind a load balancer, since in-memory state doesn't
  share across processes.
- **Trusting `X-Forwarded-For` for the rate-limit key** — rejected: trusting
  a client-supplied header as an identity key is itself spoofable and
  becomes a real decision once a reverse proxy is in the deployment picture
  (tracked as a Priority 6 deployment-readiness concern, not this one).
  `request.client.host` is what's actually verifiable today.
- **A background/cron sweep for job cleanup** — rejected for the same
  reason as Redis: adds a process/scheduler dependency for a job that's
  cheap enough to piggyback on the one write path that already exists.
- **Wrapping analysis in a hard CPU timeout** — considered and deferred.
  Python has no reliable cross-thread preemption (`signal.alarm` only works
  on Unix's main thread; jobs already run off-main-thread on a
  `ThreadPoolExecutor`), so a "kill this analysis after N seconds" timeout
  isn't implementable correctly here without a process-per-job model, which
  is a much bigger architectural change. The existing bounds — file-count
  cap, per-file size cap, bounded git-history depth — already limit how
  much work a single request can trigger; that's the practical mitigation
  today.

## Known limitation — read before deploying behind a reverse proxy

The rate limiter's key is `request.client.host`, the TCP peer FastAPI sees.
**Behind any reverse proxy, load balancer, or typical PaaS deployment
(nginx, Docker port-mapping, Render/Fly/Heroku-style platforms), every
request's TCP peer is the proxy itself** — so this "per-client" limiter
collapses to one shared 20-req/60s budget for the *entire service*, not per
visitor. In that topology it throttles organic traffic under load and does
nothing to isolate one abusive client. This is a real gap, not a
theoretical one: whoever picks Atlas's deployment topology (Priority 6)
must either put the rate limiter in front of the proxy, or configure a
trusted-proxy header (only once the proxy is known and trusted — see
"alternatives considered" on why `X-Forwarded-For` isn't trusted blindly
today).

## Edge cases

- A client with no discoverable IP (`request.client is None`, e.g. some
  test clients) falls back to a shared `"unknown"` bucket rather than
  crashing — slightly conservative (all such clients share one budget) but
  never a 500.
- Rate limiter state grows one deque per distinct IP seen; not bounded or
  evicted in v1 — acceptable for a beta's traffic volume, worth revisiting
  if it ever shows up in memory profiling (ties into Priority 5).
- `cleanup_stale_jobs` runs synchronously on the request path but is a
  single indexed-free `DELETE ... WHERE created_at < ?` against a table
  that's bounded by the same cleanup it performs — cheap in practice at
  beta scale; would want an index on `created_at` before this matters at
  larger scale.
