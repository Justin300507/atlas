# Roadmap

Atlas was originally scoped as 10 subsystems. This page tracks which are
shipped and validated, and what's deliberately not built yet. The
backend is currently **feature-frozen** — see [`CONTRIBUTING.md`](CONTRIBUTING.md)
— so nothing below is in active development; this is a map for whoever
picks the next phase, not a promise of dates.

## Implemented and validated

Validated means: run against real public repositories (not just unit
tests) and checked for believable output — see
[`docs/benchmarks/`](docs/benchmarks/).

| Subsystem | Module(s) | Notes |
|---|---|---|
| Repository Intelligence | `stack_detector.py` | Stack/framework/DB/deployment heuristics |
| Architecture Graph | `graph_builder.py`, `code_parser.py` | Python + JS/TS/TSX import & route graph |
| Code Quality Engine | `quality_engine.py` | Maintainability + Architecture scores only — see [`FAQ.md`](FAQ.md#quality-scoring) for the categories that were never built |
| Security Scanner | `security_scanner.py` | Regex-based secrets/exec/deserialization detection — see [`FAQ.md`](FAQ.md#security-scanner) for what it doesn't catch |
| Git Intelligence | `git_intelligence.py`, `git_log_parser.py` | Churn, ownership, co-change, bounded to last 500 commits |
| Documentation Generator | `doc_generator.py` | Assembles the final Markdown report, no LLM involved |
| Semantic Repository Intelligence | `semantic_analysis.py` | Architecture metrics, dependency criticality, layer detection, engineering hotspots, coupling/smell detection — validated on Django, Flask, and requests |
| Repository Comparison | `comparison_engine.py`, `snapshot.py` | Deterministic diffing between two completed jobs' snapshots — added/removed/changed, documented regression/improvement thresholds. Commit/branch-level comparison not supported (cloner only fetches HEAD) |

## Not yet built

These four were in the original 10-subsystem vision and are **not**
implemented. Their designs below are the original intent, not a
committed spec — each would need its own design doc (per the
[`CONTRIBUTING.md`](CONTRIBUTING.md) convention) before implementation
starts.

- **AI Architect** — natural-language Q&A grounded in the existing
  dependency graph ("why is X slow", tracing a call path like
  API→Service→DB→Response). This is the one subsystem that would
  introduce an LLM call into the product. The intended design keeps it
  bounded and accurate rather than a raw "ask an LLM about the repo" —
  scope the question to a relevant subgraph and relevant files first,
  then call a model on that narrow context, so the answer stays
  traceable to real graph data. See
  [`ARCHITECTURE.md`](ARCHITECTURE.md#why-deterministic-analysis-not-an-llm-wrapper)
  for why this is treated as an addition on top of the deterministic
  core, not a replacement for it.
- **Technical Debt Analyzer** — refactor targets, duplicated logic,
  unused dependencies, outdated libraries, with risk/effort estimates.
  Would need duplicate-code detection (cross-file similarity hashing)
  that doesn't exist anywhere in the current pipeline.
- **Performance Analyzer** — N+1 query detection, missing indexes,
  blocking I/O, memory-heavy patterns. Would likely need
  framework-specific detectors (ORM call patterns differ by framework),
  similar to why the security scanner doesn't attempt weak-auth/CORS
  checks today.
- **AI Mentor** — Q&A and feature-placement guidance grounded in the
  actual codebase (e.g. "where should this new endpoint live"). Depends
  on AI Architect's scoped-context approach existing first.

## Also considered, not scoped

- **Impact Analysis** — "if I change `auth.py`, what could break?",
  traversing the existing dependency graph outward from a changed file
  to show blast radius. Floated as a possible signature feature since it
  reuses the graph Atlas already builds (no new engine required), but
  not designed or committed to.

## Why the backend is frozen right now

After the fifth core subsystem (Documentation Generator) shipped, the
explicit decision was to stop adding engines and instead prove the
existing five work: real-repo validation, a frontend, deployment,
documentation, and benchmarking — the work this public beta prep
reflects. Security Scanner was added after that decision (validated
independently), but the general principle held: ship fewer engines,
validate them harder, before adding more. Any of the four "not yet
built" subsystems should only be started after there's real user
feedback suggesting it's the right next investment, not because it was
on the original list.
