# Atlas Phase 2: Code Quality Engine (v1)

## Purpose

Phase 1 gave Atlas the ability to clone a repo, detect its stack, and build a
module/import/route graph. Phase 2 uses that same infrastructure to compute
deterministic code-quality signals and fold them into the `/analyze` response, moving
Atlas one step closer to "why is this codebase good or bad," not just "what is it."

## Scope decisions for this phase

- **Extend the existing `POST /analyze` response, not a new endpoint.** A repo is
  already cloned, parsed, and graphed per request; adding a `quality` field reuses
  that work instead of triggering a second clone.
- **Honest scoring scope.** The original product vision described six score
  categories (Maintainability, Architecture, Testing, Security, Documentation,
  Overall). This phase only has real data for two of them —
  **Maintainability** (naming, function length, complexity) and **Architecture**
  (circular imports) — so v1 reports only those two plus an Overall, rather than
  fabricating Testing/Security/Documentation numbers with no subsystem behind them.
  Those three become their own future phases (Testing detection, Security Scanner,
  Documentation Generator), each adding its own score once it exists.
- **Four checks for v1, chosen because they're cheaply and reliably computable from
  data Phase 1 already extracts or can extract with a small parser extension:**
  1. **Circular imports** — the import graph already exists (`graph_builder.py`);
     this is pure graph analysis, no parser changes needed.
  2. **Long functions** — flag functions/methods over a line-count threshold.
  3. **High complexity** — flag functions with a high cyclomatic-style branch count
     (if/for/while/except/case/catch/logical-and/or, per language).
  4. **Naming convention violations** — Python functions should be `snake_case`,
     classes `PascalCase`; JS/TS functions `camelCase`, classes `PascalCase`.
- **Explicitly deferred** (need more infrastructure than a phase 2 should add):
  duplicate-code detection (needs cross-file similarity hashing), dead-code detection
  (needs a real call graph, not just imports), and the three score categories above.

## Architecture

Phase 1's `code_parser.parse_file` currently returns `FileSymbols` with a flat
`defined: list[str]` of function/class names and never surfaces line numbers or
branch counts — nothing downstream consumes `defined` today (confirmed in Phase 1's
final review), so it's safe to leave untouched and add a new, richer field alongside
it rather than break existing consumers.

```
FileSymbols (existing, UNCHANGED: path, language, imports, defined, routes)
        +
FileSymbols.functions: list[FunctionInfo]   <- NEW field
        │  FunctionInfo(name, start_line, end_line, branch_count)
        ▼
quality_engine.analyze_quality(files: list[FileSymbols], graph: nx.DiGraph) -> QualityReport
        │
        ├─ circular imports  <- nx.simple_cycles(graph) restricted to "module" nodes
        ├─ long functions    <- FunctionInfo where (end_line - start_line) > threshold
        ├─ high complexity   <- FunctionInfo where branch_count > threshold
        └─ naming violations <- regex checks against FileSymbols.defined names,
                                 cross-referenced with FunctionInfo/class detection
        │
        ▼
QualityReport(overall_score, maintainability_score, architecture_score, issues[])
        │
        ▼
AnalyzeResponse gains a `quality: QualityReport` field; POST /analyze wires it in
```

### Components

- **`code_parser.py` (modified)** — add `FunctionInfo` dataclass and a
  `functions: list[FunctionInfo]` field to `FileSymbols`. Populate it during the
  existing tree-sitter walk: for each `function_definition`/`function_declaration`
  node, record its name, `start_point[0]`/`end_point[0]` (tree-sitter gives 0-indexed
  line numbers), and a branch count from walking its subtree for branch-like node
  types. This is an additive change — no existing field's type or meaning changes, so
  Phase 1's `graph_builder`/`main.py` code that consumes `FileSymbols` is unaffected.
- **`quality_engine.py` (new)** — pure functions consuming `list[FileSymbols]` and the
  `nx.DiGraph` from `graph_builder.build_graph`; no I/O, no network, fully unit
  testable against constructed `FileSymbols`/`DiGraph` objects. Produces `QualityReport`.
- **`models.py` (modified)** — add `QualityIssue` (file, line, kind, message,
  severity) and `QualityReport` (overall_score, maintainability_score,
  architecture_score, issues) Pydantic models; add `quality: QualityReport` to
  `AnalyzeResponse`.
- **`main.py` (modified)** — after `build_graph`, call `quality_engine.analyze_quality`
  and include the result in the response.

## Scoring

Start both `maintainability_score` and `architecture_score` at 100 and subtract fixed
per-issue penalties, floored at 0:

- Circular import cycle found: -15 per distinct cycle (architecture_score)
- Long function (> 50 lines): -5 per function (maintainability_score)
- High complexity (branch count > 10): -5 per function (maintainability_score)
- Naming violation: -2 per violation (maintainability_score)

`overall_score` = average of the two category scores, rounded to nearest int. Simple,
documented, not tuned against real-world repos yet — this is a v1 heuristic, not a
calibrated model, and later phases may revisit the weights once there's usage data.

## Error handling

`analyze_quality` never raises for malformed input it can reasonably skip (e.g. a
`FunctionInfo` with equal start/end line contributes 0-length, not a crash) — quality
analysis degrades gracefully the same way Phase 1's parsing does, since one odd
function shouldn't take down the whole `/analyze` response.

## Testing

- Unit tests for `code_parser`'s new `FunctionInfo` extraction against small fixture
  functions with known line spans and known branch counts (Python and JS).
- Unit tests for `quality_engine.analyze_quality` against hand-constructed
  `FileSymbols`/`DiGraph` inputs covering: a clean repo (score 100/100), a repo with
  one circular import, one long function, one high-complexity function, and one
  naming violation — asserting both the specific issue is reported and the score
  deduction is correct.
- One API-level test confirming `POST /analyze`'s response includes a `quality` field
  with the expected shape, using the existing `fastapi_repo` fixture (mocked clone,
  no network — same pattern as Phase 1's API tests).
- No live-network dependency added.

## Tech stack (this phase)

No new dependencies — `tree-sitter` (already used) provides `start_point`/`end_point`
per node; `networkx` (already used) provides `simple_cycles`.

## Out of scope for this phase (explicitly deferred)

Duplicate-code detection, dead-code detection, Testing/Security/Documentation scores,
any frontend/UI to visualize the quality report, persistence of quality history over
time (would need Phase 1's still-deferred database).
