# Atlas Real-World Validation

Generated 2026-07-24. Full reports for each repo are in
`real-world-validation-reports/`. Produced by `backend/scripts/validate_real_repos.py`.
This is the *third* regeneration of this doc in one session — each prior
version's numbers changed because reading (not just counting) the actual
report output kept surfacing real bugs. See the design docs linked below
for the full story behind each fix.

| Repo | Ecosystem | OK | Time (s) | Peak RSS (MB) | Files | Cap hit | Import edges | Overall | Arch | Circular clusters | Security | Commits |
|---|---|---|---:|---:|---:|:-:|---:|---:|---:|---:|---:|---:|
| django/django | Python | ✓ | 43.8 | 77 | 3038 | no | 8787 | 56 | 18 | 17 | 170 | 500 (truncated) |
| tiangolo/fastapi | Python | ✓ | 19.5 | 76 | 1131 | no | 1608 | 74 | 54 | 1 | 3 | 500 (truncated) |
| pallets/flask | Python | ✓ | 40.5 | 76 | 83 | no | 171 | 70 | 43 | 1 | 2 | 500 (truncated) |
| facebook/react | JavaScript | ✓ | 50.4 | 83 | 4482 | no | 3527 | 42 | 19 | 22 | 111 | 500 (truncated) |
| expressjs/express | JavaScript (CommonJS) | ✓ | 5.5 | 82 | 141 | no | 153 | 98 | 100 | 0 | 2 | 500 (truncated) |
| vercel/next.js | TypeScript (monorepo) | ✗ | — | — | — | — | — | — | — | — | — | see below |

## What this found

**1. Quality scores were not credible.** `maintainability_score` was
0/100 for Django, FastAPI, React, and Flask — every repo except the
smallest. Root cause and fix:
[quality-score-normalization design doc](../superpowers/specs/2026-07-24-quality-score-normalization-design.md).

**2. The file-walk cap was silently starving real source coverage.**
Django's walk hit the 5,000-file cap having examined only 1,511 of its
2,927 real `.py` files, because non-source clutter (docs, translations,
fixtures) consumed the same budget as real source. Django's `files`
count in this table (3,038) is roughly double what it was before the
fix, and "Cap hit" is correctly `no` for every repo now. Root cause and
fix:
[file-walk-cap design doc](../superpowers/specs/2026-07-24-file-walk-cap-source-only-design.md).

**3. Security findings were not credible either.** Reading (not just
counting) Django's and React's findings found the top results were
almost entirely dummy test-fixture passwords and `eval()`/`exec()` calls
inside test suites and compiler test fixtures — exactly what those files
are supposed to contain. Fixed by demoting (not deleting) findings in
test/fixture paths to `minor` severity:
[security-scanner test-path-demotion design doc](../superpowers/specs/2026-07-24-security-scanner-test-path-demotion-design.md).
A second, sharper bug turned up re-reading Django's findings *after* that
fix: `django/template/smartif.py` defines its own `Operator.eval()`
method (Django's template-expression evaluator), which the scanner's
regex matched identically to a real, dangerous bare `eval(user_input)`
call. Fixed with a negative lookbehind excluding method calls
(`x.eval(...)`) from the dangerous-builtin check. Django's Security
Findings section now leads with genuine `eval()`-based expression
evaluation in `django/template/defaulttags.py` and `smartif.py` — a real,
worth-knowing architectural fact about Django's template engine — instead
of pages of test-fixture noise.

**vercel/next.js still fails to clone** — not an Atlas bug, a Windows
filesystem limitation. Turbopack's test-snapshot fixtures use deeply
nested paths that exceed Windows' default `MAX_PATH` (260 chars) during
checkout. Specific to running Atlas natively on Windows (as this
validation did); Atlas's actual deployment target is a Linux container,
where this limit doesn't exist. Not fixed, since it isn't the highest
priority use of effort — but the raw git error this used to surface
(several hundred lines of `Updating files: NN%` progress noise) is now a
short, clean diagnostic via `cloner.py`'s `_clean_git_error`.

**Would an engineer trust these reports now?** Meaningfully more than at
the start of this validation round. Django's report in particular went
from "everything is 0, everything is critical, nothing is believable" to
a report that correctly differentiates a real, well-known architectural
trait (the `django/__init__.py` circular cluster; genuine `eval()` use in
the template engine) from routine, expected code (test fixtures, a
custom `.eval()` method) — which is the actual bar this project has been
holding itself to all session.
