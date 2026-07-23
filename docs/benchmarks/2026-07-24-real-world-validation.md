# Atlas Real-World Validation

Generated 2026-07-24. Full reports for each repo are in
`real-world-validation-reports/`. Produced by `backend/scripts/validate_real_repos.py`
— see the [quality-score-normalization design doc](../superpowers/specs/2026-07-24-quality-score-normalization-design.md)
for why the scores below differ from an earlier run the same day.

| Repo | Ecosystem | OK | Time (s) | Peak RSS (MB) | Files | Cap hit | Import edges | Overall | Arch | Circular clusters | Security | Commits |
|---|---|---|---:|---:|---:|:-:|---:|---:|---:|---:|---:|---:|
| django/django | Python | ✓ | 34.1 | 71 | 1511 | no | 4989 | 55 | 16 | 17 | 151 | 500 (truncated) |
| tiangolo/fastapi | Python | ✓ | 21.2 | 71 | 1131 | no | 1608 | 74 | 54 | 1 | 7 | 500 (truncated) |
| pallets/flask | Python | ✓ | 6.3 | 70 | 83 | no | 171 | 70 | 43 | 1 | 2 | 500 (truncated) |
| facebook/react | JavaScript | ✓ | 29.0 | 71 | 2509 | no | 1079 | 47 | 29 | 3 | 30 | 500 (truncated) |
| expressjs/express | JavaScript (CommonJS) | ✓ | 8.9 | 69 | 141 | no | 153 | 98 | 100 | 0 | 2 | 500 (truncated) |
| vercel/next.js | TypeScript (monorepo) | ✗ | — | — | — | — | — | — | — | — | — | see below |

## What this found

**Quality scores were not credible before this run.** `maintainability_score`
was 0/100 for Django, FastAPI, React, and Flask — every repo tested except
the smallest. Root cause and fix: the
[quality-score-normalization design doc](../superpowers/specs/2026-07-24-quality-score-normalization-design.md).
Both scores now differentiate meaningfully: Django's low architecture score
(16) correctly reflects a real, well-known trait (a 141-module circular
cluster centered on `django/__init__.py`/`django/conf/__init__.py`), while
its high maintainability score (94) correctly reflects that the *functions
themselves* are, in fact, well-kept relative to the codebase's size — a
distinction the old formula couldn't make since it floored both to 0
regardless.

**vercel/next.js failed to clone** — not an Atlas parsing bug, a Windows
filesystem limitation. Turbopack's test-snapshot fixtures use deeply nested
paths that exceed Windows' default `MAX_PATH` (260 chars) during checkout;
git reports `Filename too long` and the working tree never completes. This
is specific to running Atlas natively on Windows (as this validation did) —
Atlas's actual deployment target is a Linux container (see `Dockerfile`,
`docker-compose.yml`), where this path-length limit doesn't exist. Not
fixed here, since fixing a Windows-dev-only limitation isn't the highest
priority; documented so it isn't mistaken for a parser or clone-logic bug
later. Separately, this run *did* motivate a real fix: the raw git error
for this failure was originally several hundred lines of `Updating files:
NN%` progress noise; `cloner.py`'s `_clean_git_error` now extracts just the
`fatal:`/`error:` lines and caps the message at 500 chars, so a real clone
failure surfaces a short, honest diagnostic instead of a wall of text
(regression-tested in `test_cloner.py`).

**Would an engineer trust these reports?** With the scoring fix: broadly
yes, with caveats already disclosed in every report's "Analysis Coverage"
footer (heuristic scores, not guarantees; no CommonJS `require()` — now
actually supported — was the old caveat; current known gaps are Windows
long-path cloning and the file-count/graph-size caps not yet being
surfaced when hit, see the truncation-visibility work in progress).
Django's report in particular reads as genuinely useful: it correctly
identifies the real circular-dependency hot spot instead of drowning it in
an undifferentiated wall of "everything is bad" noise.
