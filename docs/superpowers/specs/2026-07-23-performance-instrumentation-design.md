# Atlas: Performance Instrumentation & Benchmarking (v1)

## Problem

There's no visibility into where a `/documentation`/`/jobs` request
actually spends its time (clone vs. parse vs. graph-build vs. quality/
security scanning vs. doc generation), and no measurement against real
repos of varying size to know if any stage is a genuine bottleneck versus
just "it feels slow." `run_full_analysis`/`analyze_structure` already call
an `on_stage(name)` hook at each transition (added for job progress in
Phase 5) — that hook is the natural place to attach timing without
touching the pipeline's actual logic.

## Architecture

New `backend/app/timing.py`: `StageTimer`, a small callable wrapper around
an existing `on_stage` callback. Each call records how long the *previous*
stage took (time between consecutive `notify()` calls), forwards the call
to the wrapped callback unchanged (so job-progress polling is untouched),
and `finish()` closes out the final stage's duration plus a `total` key.
No new dependency — `time.monotonic()`, stdlib only.

Wired into `main.py`'s `_run_job` (the background-job path used by
`/jobs`): wraps the existing `lambda stage: jobs.update_job(...)` callback,
and on completion (success or failure, via `try/finally`) logs the
resulting `{stage: seconds, total: seconds}` dict via the stdlib `logging`
module at `INFO` level. Deliberately *not* added to the JSON response
schema (`AnalyzeResponse`/`DocumentationResponse`) — this is operational
telemetry for logs, not part of the API contract, so no consumer-facing
change.

## Real-repo measurement (performed as part of this phase)

Ran `run_full_analysis` directly (bypassing HTTP) against real public
repos using `StageTimer`, and found two genuine, unrelated bottlenecks:

**1. Backend: `run_full_analysis` cloned the same repo twice** — once via
`shallow_clone` (depth 1, for structure) and again via `clone_with_history`
(depth 501, for git intelligence). A depth-N clone checks out the exact
same working tree a depth-1 clone would (extra depth only adds history
objects behind HEAD, not different files), so one clone can serve both
needs. Fixed in `report_pipeline.run_full_analysis` by dropping the
`shallow_clone` call entirely and running structure analysis against the
`clone_with_history` checkout instead. Stage names/order are unchanged
(`notify("cloning_history")` still fires at the same point, immediately
after structure analysis) so job-progress polling behavior is identical.
On a trivial repo (octocat/Hello-World) this measured as an unambiguous
~47% reduction in total pipeline time (2.80s -> 1.48s), since there's
almost no history to fetch either way and the second clone was pure
overhead. On a repo with substantial history (tiangolo/typer), single-run
timings varied too much (run-to-run GitHub clone time ranged 3-14s in
this environment) to quote a precise percentage, but a paired/interleaved
benchmark (4 trials, old two-clone strategy vs. new one-clone strategy,
alternating to cancel out time-varying network conditions) showed the
one-clone median (5.8s) beating the two-clone median (8.9s) — consistent
with the structural argument that one combined clone transfers the HEAD
tree's objects once instead of twice, regardless of network noise on any
single sample.

**2. Frontend: the entire Mermaid library was in the initial page-load
bundle.** `MarkdownReport.tsx` statically `import`ed `mermaid`, which
transitively pulls in a renderer for every Mermaid diagram type plus
`cytoscape` and `katex` — several hundred KB gzipped, none of it needed
until a report containing a ` ```mermaid ` block is actually rendered.
Confirmed via `vite build`'s output: before the fix, `index.html`
eagerly `<link rel="modulepreload">`-loaded 15+ chunks including
`cytoscape.esm` (435 kB) and a 662 kB chunk, none used before the user
even submits a URL. Fixed by replacing the static import with a cached
dynamic `import("mermaid")` inside `MermaidBlock`, deferring the fetch to
the first time a diagram actually needs rendering. After the fix,
`index.html` loads exactly one script tag with no Mermaid-related
preloads — verified directly in the build output, not estimated.

## Alternatives considered

- **APM/tracing library (OpenTelemetry, etc.)** — rejected for v1; a
  single-process app with one meaningful call graph doesn't need
  distributed tracing infrastructure yet. `StageTimer` is ~20 lines and
  gives the same "where did the time go" answer for the shape of workload
  Atlas has today.
- **Exposing timings in the API response** — rejected; conflates
  operational telemetry with the public contract, and would need
  versioning discipline every time a stage is added/renamed/merged.
  Logs are the right place for this.
- **Wrapping `/analyze` (the synchronous endpoint) too** — not done in
  this pass; `/analyze` calls `analyze_structure` directly without going
  through the job-runner path, and adding timing there would need a
  second wiring point for less benefit (it's the smaller of the two
  pipelines, already bounded by file-count/size caps). Left as a clearly
  separable follow-up rather than scope-creeping this change.

## Edge cases

- If a stage raises before ever calling `notify()` again (e.g. the very
  first clone fails), `finish()` still records whatever partial duration
  exists for the last stage entered plus `total` — a request that fails
  immediately still produces a (short) timing entry, not a crash in the
  timer itself.
