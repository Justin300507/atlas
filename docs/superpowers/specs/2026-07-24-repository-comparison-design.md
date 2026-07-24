# Repository Comparison — design spec

## Scope decision made up front

Comparison works on **two completed jobs** (`job_id_a`, `job_id_b`) —
the unit Atlas already has. "Two commits" / "two branches" are
explicitly **not supported**: `cloner.py` only clones HEAD of a bare
repo URL (`git clone --depth N <url>`, no `--branch`/ref checkout).
Building that out is separate scope from comparison itself and risks
rushing a less-tested cloner change under this session's time budget.
Disclosed as a known limitation, not silently unsupported.

## Phase 1 — Snapshot model

`AnalysisSnapshot` (new Pydantic model) — a slim, deterministic
projection of an already-computed analysis, **not** a second analysis
pass. Built once, at the end of `run_full_analysis`, from data already
in memory (`quality`, `security`, `git_report`, `semantic`) — no new
parsing, no re-cloning.

Persisted as one JSON column (`snapshot`) on the existing `jobs` table
(`schema_version` field inside the JSON, not a DB migration framework —
one column, `ALTER TABLE ... ADD COLUMN`, guarded against re-running on
an existing DB). Explicitly excluded from the snapshot: full file
lists, full markdown, full dependency graph, full issue/finding text —
only counts, scores, and the top-N ranked lists already capped
elsewhere in Atlas (critical modules, hotspots). This keeps a snapshot
a few KB, not a copy of the whole analysis.

## Phase 2 — Comparison engine (`comparison_engine.py`)

Pure function `compare_snapshots(a, b) -> ComparisonReport`. For each
of architecture / quality / security / git / semantic, produces:
- **changed** scalar metrics (score deltas, counts) with the raw before/after values — always shown, not classified.
- **added/removed** for set-valued things (module names appearing in
  criticality/hotspot top-N in one snapshot but not the other).
- **unchanged** is implicit (not enumerated — would be the largest,
  least useful list).

## Phase 3/4 — Regression / improvement thresholds

Documented, fixed thresholds — not tuned against a dataset (none
exists yet for this feature), stated as a starting point:
- Quality/architecture/overall score: ±5 points is the noise floor
  (below that, not reported as regression or improvement — normal
  churn from unrelated file changes moves these scores by 1-3 points
  even with no meaningful architectural change, based on the score
  volatility already observed across this project's own real-repo
  validation runs).
- New circular-dependency cluster: always a regression (binary, no
  threshold needed).
- Circular cluster removed: always an improvement.
- Security findings: any increase in `critical`/`important` count is a
  regression; `minor`-only changes are not reported as regressions
  (matches the severity model already used everywhere else in Atlas).
- A module entering the hotspot top-15 that wasn't there before: a new
  hotspot (regression-flagged only if it's also `critical`/`important`
  complexity-wise — reusing existing severity, not inventing a new
  one). Leaving the top-15: hotspot eliminated (improvement).
- A module entering dependency-criticality top-15: reported as a
  criticality change, **not** classified regression/improvement on its
  own — becoming more central isn't inherently good or bad without
  knowing why, and the mandate says never speculate.

## Phase 5 — Visual diff

One Mermaid diagram: modules that entered or left the critical-module
top-15, colored by added/removed. Capped at 15+15=30 nodes max (same
cap discipline as every other diagram in this codebase). No dependency-
graph-diff diagram — a full before/after graph diff on top of an
already-capped 40-node diagram would be unreadable, and the module-
level added/removed table already carries that information in
readable form.

## Phase 6 — Report

New `generate_comparison_report()` in `doc_generator.py`, same
Markdown-section style as the existing report. Every section states
its own confidence/limitation inline rather than one generic disclaimer
at the end, since different sections have different real caveats
(score noise floor vs. set-difference vs. "not classified").

## Phase 7 — API

`POST /compare` — `{"job_id_a": str, "job_id_b": str}` → `{"markdown": str, "comparison": ComparisonReport}`.
404 if either job doesn't exist; 409 if either isn't `status=done` yet
(a snapshot only exists on a completed job) or is a job that predates
this feature (no `snapshot` column value — an old completed job from
before this migration).

## Known limitations

- Comparing two different repos (not two runs of the same repo) is
  technically possible (the engine doesn't check) and will produce a
  mostly-"different everything" report — not nonsensical, but not the
  intended use case, and not specially detected/warned about.
- Thresholds are a documented starting point, not empirically tuned —
  no historical comparison dataset exists yet to tune against.
- No ref/branch/commit-level comparison (see scope decision above).
