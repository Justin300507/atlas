# Example Reports

Real `POST /documentation` output against real public repos, generated
2026-07-23 — nothing hand-edited or trimmed except what the tool itself
already caps for readability (dependency diagram, risk areas, etc.).

- [`typer-report.md`](typer-report.md) — [tiangolo/typer](https://github.com/tiangolo/typer),
  a mid-sized Python CLI framework. Shows: FastAPI-adjacent stack
  detection, a real circular-dependency cluster (22 modules), 89
  high-complexity function findings, and git churn/bug-fix history
  across 500 commits.
- [`express-report.md`](express-report.md) — [expressjs/express](https://github.com/expressjs/express),
  a CommonJS-heavy Node.js repo. Shows: Express stack detection, 84
  routes detected via `require()`-based imports, and a clean
  (no-circular-dependency) architecture score.

Regenerate these yourself:

```bash
curl -X POST http://127.0.0.1:8000/documentation \
  -H "Content-Type: application/json" \
  -d '{"repo_url": "https://github.com/tiangolo/typer"}'
```
