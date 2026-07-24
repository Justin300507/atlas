# Roadmap

Atlas was originally scoped as 10 subsystems; all 10 have now shipped
(v1.3 closed out the last four). This page tracks what's implemented
and validated, and what was considered but not scoped.

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
| Technical Debt Engine | `technical_debt.py` | Weighted score (complexity×churn, centrality×size, coupling/smells, circular-cluster membership) reusing already-computed data — no new parsing or cloning. Validated on Atlas itself and Flask (`src/flask/app.py` correctly ranked #1) |
| Performance Analyzer | `performance_analyzer.py` | Static-only: very-large-function size, high-branch-count (labeled a proxy for nesting, not measured), dependency-bottleneck (criticality ∩ coupling). Deliberately does not attempt N+1/ORM/runtime detection — see [`FAQ.md`](FAQ.md#performance-analyzer) |
| AI Architect / AI Mentor | `ai_explain.py` | Pluggable `Explainer`: a template-based `DeterministicExplainer` (always available) plus an optional `AnthropicExplainer` that only ever narrates a `_grounded_in` evidence list passed to it — it cannot introduce facts Atlas didn't already compute. Falls back to the deterministic explainer on any missing API key, SDK, network error, or safety refusal. The Anthropic call path is unit-tested against a mocked client; no environment this shipped in had real Anthropic credentials, so it was never live-validated against an actual model response — see [`FAQ.md`](FAQ.md#ai-explainer) |

## Also considered, not scoped

- **Impact Analysis** — "if I change `auth.py`, what could break?",
  traversing the existing dependency graph outward from a changed file
  to show blast radius. Floated as a possible signature feature since it
  reuses the graph Atlas already builds (no new engine required), but
  not designed or committed to.

## History of the "feature freeze"

After the fifth core subsystem (Documentation Generator) shipped, the
explicit decision was to stop adding engines and instead prove the
existing five work: real-repo validation, a frontend, deployment,
documentation, and benchmarking. Security Scanner, Semantic Repository
Intelligence, and Repository Comparison were each added and validated
independently after that. The remaining four (Technical Debt Engine,
Performance Analyzer, AI Architect, AI Mentor) shipped together in
v1.3 — all ten originally-scoped subsystems are now implemented. The
general engineering principle that justified the freeze — validate
each engine against real repositories before building the next one —
was kept for every one of these ten, not abandoned when the freeze
itself ended.
