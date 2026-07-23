# Quality score normalization — design spec

## Problem, confirmed empirically

Real-world validation (`backend/scripts/validate_real_repos.py`) against
Django, FastAPI, Flask, React, and Express found `maintainability_score`
is **0/100 for every repo except the smallest** (Express, 141 files):

| Repo | Files | Maintainability | Architecture | Overall |
|---|---:|---:|---:|---:|
| django/django | 1511 | 0 | 0 | 0 |
| tiangolo/fastapi | 1131 | 0 | 54 | 27 |
| facebook/react | 2509 | 0 | 29 | 14 |
| pallets/flask | 83 | 0 | 43 | 22 |
| expressjs/express | 141 | 69 | 100 | 84 |

Root cause: both scores are absolute-penalty models with no cap and no
normalization by codebase size.

- `maintainability_score`: `-5` per long function, `-5` per high-complexity
  function, `-2` per naming violation, no cap. Any repo with roughly 20+
  such issues floors at 0 — trivially true of any codebase with more than
  a couple hundred functions, since some fraction will always cross the
  length/complexity/naming thresholds. Django alone has 1600+ issues
  beyond what the report even lists.
- `architecture_score`: `-10` per circular-import cluster, *uncapped*
  (unlike the largest-cluster-size penalty, which is already capped at
  `-40`). A repo with 17 small-to-medium clusters (Django) takes a flat
  `-170` from this term alone, before the two properly-normalized terms
  (largest-cluster-size, participation-ratio) get a say.

Net effect: `maintainability_score` is not a signal at all for any
non-trivial real repo — it is always 0. This fails the standing bar for
this project (would an engineer trust this report?) in the most direct
way possible: the score never differentiates.

## Fix

### Architecture score: cap the uncapped term

The cluster-*count* penalty becomes bounded, same pattern already used
for the largest-cluster-size penalty:

```python
_MAX_CLUSTER_COUNT_PENALTY = 40  # was uncapped

score -= min(_MAX_CLUSTER_COUNT_PENALTY, len(clusters) * _PER_CLUSTER_PENALTY)
```

This is deliberately *not* normalized by repo size (e.g. clusters ÷
total modules) — that was tried first and rejected: for a 2-module repo,
one 2-module cluster is already 50% cluster "density," which swings
tiny repos to worse scores than before. A flat cap avoids that
small-sample perversity while still preventing cluster *count* alone
from dominating the score for large repos. `largest_cluster_size` and
`participation_ratio` (already a true rate) continue to carry the
size-sensitive signal.

### Maintainability score: Laplace-smoothed rate, not absolute count

Switch from `-N points per issue` to a smoothed-rate penalty per
category, so the same *proportion* of issues costs roughly the same
number of points regardless of codebase size — while small samples
(a 1-function test fixture, a toy repo) don't swing to extreme rates:

```python
_RATE_SMOOTHING = 20  # Laplace-style: treat every sample as if padded
                       # with 20 hypothetical clean units, so a 1-function
                       # sample doesn't compute a naive 100% issue rate.
_LONG_FUNCTION_WEIGHT = 100
_HIGH_COMPLEXITY_WEIGHT = 100
_NAMING_WEIGHT = 60

rate = issue_count / (total_sample + _RATE_SMOOTHING)
penalty = round(rate * WEIGHT)
```

`total_sample` is total function count for the long-function and
high-complexity penalties, and total functions + classes for naming.

This was chosen over a flat per-category cap (tried second): Flask, at
only 83 files, *already* has enough issues to floor a capped model too
— a cap large enough to matter for Django (thousands of functions) is
far too loose for an 83-file repo, and no single constant cap serves
both scales. The smoothing constant makes small and large samples both
behave sensibly off the same formula: at `total_sample=1` the smoothing
term dominates and the formula reduces to roughly the old per-issue
point cost; at `total_sample` in the thousands, the smoothing term is
negligible and the formula reduces to a true rate.

## What does NOT change

- The circular-import detection itself (strongly-connected components,
  one issue per cluster) — that's already correct, established in the
  2026-07-23 marathon session.
- `participation_ratio`'s scoring term — already a true rate, already
  behaves correctly at any repo size.
- The largest-cluster-size penalty — already capped, already correct.
- Security scoring — out of scope for this spec; the validation run's
  security-finding counts (2–151 across repos) look proportionate to
  repo size already and weren't flagged as a credibility problem.

## Test impact

Four existing `quality_engine` tests are unaffected (verified by hand):
their fixtures have few enough issues relative to sample size that both
the old and new formulas produce the same score. One existing test,
`test_architecture_score_floors_at_zero_with_many_clusters`, currently
pins the *old, confirmed-wrong* behavior (20 tiny clusters spread across
a 40-module repo scores exactly 0) — its expected value changes, and
it's renamed to describe what it now actually asserts. New regression
tests are added for: a large-repo-shaped fixture that no longer floors
at 0 on either score, and a genuinely maximally-bad fixture that still
correctly floors at 0 on both (so "can still score 0 when it should"
stays covered).

## Validation plan

After implementation: re-run `validate_real_repos.py` against the same
five successful repos (Django, FastAPI, Flask, React, Express) and
manually judge whether the new scores are believable — not just
"nonzero," but plausible relative to each other and to what's publicly
known about each project's structure.
