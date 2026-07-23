# Atlas: Performance & Load Benchmarking (v1)

## Problem

Prior performance work (see the performance-instrumentation design doc)
measured two specific bottlenecks ad hoc, against two real repos, via a
throwaway scratch script. There's no repeatable way to answer "how does
Atlas scale as repo size grows" or "what happens when several analyses
run at once" — both explicitly requested, and both need a different
methodology than "clone a real GitHub repo," since real-repo clone time is
dominated by network variance (already observed to range 3-14s for the
same operation in this environment), which would swamp any LOC-scaling
signal.

## Architecture

**Synthetic repo generation** (`backend/scripts/generate_synthetic_repo.py`):
builds a local git repo with a target total line count, spread across
`N` Python modules in a package, each importing 1-2 earlier modules (a
mix of a chained "previous module" import plus one earlier-random import,
so the dependency graph has real fan-in/fan-out instead of a degenerate
straight line or a fully-disconnected file set) and containing a handful
of functions/classes of varying size. A small number of git commits (5,
not 500) are layered on top so git-intelligence has real, if light, work
to do — LOC/file-count is the scaling axis here, commit-history depth was
already covered by the git-intelligence design doc's own benchmarking.
Generated entirely under a temp directory, never inside the Atlas repo
itself (repo-safety rule: experiments stay isolated).

**Benchmark script** (`backend/scripts/benchmark.py`): two legs, matching
the two things that were asked for and that need different methodology:

1. **Real-repo leg** (validates against actual public repos): runs the
   real `run_full_analysis(url)` end-to-end, network clone included,
   against a short fixed list (octocat/Hello-World, tiangolo/typer) —
   kept short deliberately to avoid hammering GitHub with a large
   benchmark matrix.
2. **Synthetic LOC-scaling leg**: for each of 10k/25k/50k/100k/250k
   target LOC, generates a synthetic repo (leg above) and calls
   `analyze_structure` + `parse_git_log`/`analyze_git_history` +
   `generate_documentation` directly against the local path — no clone,
   no network, isolating pure parse/graph/quality/security/doc-gen
   compute time from clone-time noise entirely.

Both legs use the existing `StageTimer` for per-stage wall-clock timing,
plus a background-thread `psutil` RSS sampler (peak, not just before/after
— a snapshot taken only at start and end would miss a transient peak
mid-parse) for memory. Results are rendered as a Markdown table and
written to `docs/benchmarks/2026-07-23-performance-and-load-benchmark.md`
— a dated, checked-in artifact, not just a stdout printout that
evaporates after the session.

`psutil` is added to a new `backend/requirements-bench.txt`, not the main
`requirements.txt` — it's a benchmarking tool, not something the deployed
app needs, so it doesn't belong in the Docker image.

**Queue/concurrency behavior** (`backend/tests/test_concurrency_load.py`,
a real pytest test, not a one-off script): fires 12 concurrent
`POST /jobs` requests (via a `ThreadPoolExecutor` of real HTTP-shaped
`TestClient` calls) against a **local fixture directory** monkeypatched in
for `clone_with_history` — deliberately not real GitHub clones. The thing
under test here is the app's own concurrency machinery (the
`_MAX_ACTIVE_JOBS` cap, the job `ThreadPoolExecutor`, SQLite job-state
writes under concurrent access), not clone performance, and 12 concurrent
real clones would be needless load on GitHub for a fact this test doesn't
need real network to establish. Asserts: exactly `_MAX_ACTIVE_JOBS` (8)
requests succeed with 202, the remainder get 429, and every accepted job
eventually reaches `status: "done"` with no deadlock/starvation across
the 4-worker thread pool. Making this a permanent, deterministic pytest
test (rather than a one-off number in a report) gives durable regression
protection against future concurrency bugs, which is worth more than a
single benchmark-run measurement.

## Alternatives considered

- **Cloning real large repos (Django, a 250k-LOC monorepo) for the
  LOC-scaling leg** — rejected; real-repo LOC isn't controllable or
  reproducible run-to-run (a repo's size changes over time), and clone
  time noise would dominate exactly the signal this leg needs to isolate.
  Synthetic repos trade "is this exactly what a real repo looks like" for
  "is this exact size, every time, with no network variance" — the right
  trade for a scaling benchmark specifically (the real-repo leg above
  still exists precisely to keep validation grounded in genuine repos).
- **Load-testing via real concurrent GitHub clones** — rejected for the
  same reason, plus it's inconsiderate load on a third party for a
  question ("does our own concurrency cap work") that doesn't need it.
- **`tracemalloc` instead of `psutil` for memory** — rejected;
  `tracemalloc` only tracks Python-heap allocations and would
  significantly undercount tree-sitter's/networkx's native-extension
  memory, which is exactly the class of allocation most likely to scale
  with repo size.

## Findings from the first benchmark run

Running this infrastructure immediately paid for itself. The first pass at
the synthetic LOC-scaling leg showed clearly superlinear scaling — 100k to
250k LOC (2.5x) caused peak RSS to jump 5.6x (524MB -> 2,922MB) and total
time 3.5x. Bisecting per-stage (see the git history/commit log for the
diagnostic process) isolated it to `analyze_git_history`: 16.16s and a
~2.9GB *transient* peak (RSS settled back to ~64MB once garbage collected)
for the 250k-LOC synthetic repo alone.

Root cause: `git_intelligence.analyze_git_history`'s co-change-pair
computation ran `itertools.combinations(paths, 2)` — O(k²) — over every
commit's changed-file list with no size limit. The synthetic generator's
`git add .` (staging every file) before its 5-commit loop starts means the
loop's first commit captures the *entire* file set as newly added — not a
generator artifact specific to this benchmark, but exactly what almost
every real repo's actual first commit looks like. At 3,126 files, that's
`3126 * 3125 / 2 ≈ 4.88 million` pairs computed and stored in a Python
dict from one commit.

Fixed by skipping co-change pairing (not per-file churn/ownership
accounting, which is unaffected) for any commit touching more than 100
unique files (`git_intelligence.py`'s `_MAX_FILES_PER_COMMIT_FOR_COCHANGE`).
Re-measured after the fix: `analyze_git_history` dropped to 0.02s / +2.6MB
for the same 250k-LOC repo, and the LOC-scaling leg is now clean and
roughly linear end to end. This also measurably helped a *real* repo in
the benchmark's other leg: tiangolo/typer's peak RSS dropped from 191.6MB
to 53.5MB on re-run, confirming the bug wasn't a synthetic-fixture-only
artifact.

Separately, building the concurrent-load test for this phase
(`test_concurrency_load.py`) surfaced a second real bug: firing 12
concurrent `POST /jobs` requests showed the `_MAX_ACTIVE_JOBS` capacity
cap doing nothing (12/12 accepted) — a classic TOCTOU race, since the old
code checked `count_active_jobs()` and called `create_job()` as two
separate SQL statements with no atomicity between them. Fixed with
`jobs.try_create_job()`, a single atomic `INSERT ... SELECT ... WHERE`
statement relying on SQLite's own write-serialization. See the commit
message for the full fix history, including a test-methodology
correction along the way (the synthetic fixture's jobs completed so fast
that earlier ones were freeing capacity before all 12 requests even
finished submitting, undercounting the real peak-concurrency scenario).

## Edge cases

- The synthetic generator caps how skewed file sizes get (no single
  pathological giant file) so the LOC-scaling legs measure realistic
  scaling, not the file-size cap (`_MAX_FILE_SIZE_BYTES`) kicking in.
- The concurrency test's monkeypatched fixture clone must still look like
  a real repo to `analyze_structure`/`parse_git_log` (real files, a real
  `.git` history) so a bug in the actual analysis code, not just the
  queueing mechanism, would still be caught if introduced.
