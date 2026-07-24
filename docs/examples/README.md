# Example Reports

Real `POST /documentation` output against real public repos, regenerated
2026-07-24 against the current engine — nothing hand-edited or trimmed
except what the tool itself already caps for readability (dependency
diagram, risk areas, etc.). These two are kept here specifically because
they read well as a first impression; for the fuller validation set
(six repos, chosen for ecosystem diversity rather than how flattering
the output is) see
[`docs/benchmarks/real-world-validation-reports/`](../benchmarks/real-world-validation-reports/)
and the [methodology doc](../benchmarks/2026-07-24-real-world-validation.md).

- [`typer-report.md`](typer-report.md) — [tiangolo/typer](https://github.com/tiangolo/typer),
  a mid-sized Python CLI framework. Overall score 68/100 (maintainability
  97, architecture 39) — 90 quality findings (53 long functions, 26
  high-complexity, 9 naming, 2 circular-import clusters, one spanning 22
  modules), plus git churn/bug-fix history across 500 commits.
- [`express-report.md`](express-report.md) — [expressjs/express](https://github.com/expressjs/express),
  a CommonJS-heavy Node.js repo. Overall score 98/100 (maintainability
  95, architecture 100) — 84 routes detected via `require()`-based
  imports, no circular-dependency clusters.
- [`atlas-self-report.md`](atlas-self-report.md) — Atlas analyzing its
  own repository. Overall 98/100 (architecture 100 — no circular
  imports in its own codebase). Included because running Atlas on
  itself is how a real bug got found and fixed: the security scanner
  was flagging its own source comments that *describe* what
  `eval()`/`exec()`/`pickle.load()` detection does as if they were live
  dangerous code. See the `fix: security scanner no longer flags
  comments describing dangerous patterns` commit — dogfooding, not a
  synthetic test case, caught it.

**Not hiding the imperfect ones:** typer's architecture score (39/100)
is low because of that 22-module cycle, and it's shown here rather than
swapped for a cleaner-looking repo. For an even lower architecture score
on a codebase most engineers already know, see
[facebook/react in the validation set](../benchmarks/real-world-validation-reports/facebook-react-report.md)
(architecture 19/100, 22 circular-import clusters) — a real, checkable
result, not cherry-picked.

Regenerate these yourself:

```bash
curl -X POST http://127.0.0.1:8000/documentation \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/tiangolo/typer"}'
```
