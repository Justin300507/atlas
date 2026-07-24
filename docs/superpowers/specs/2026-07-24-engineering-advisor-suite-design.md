# Engineering Advisor Suite (v1.3) — design spec

## Credential constraint, stated up front

AI Architect / AI Mentor need an LLM to produce natural-language
explanations. **No API key is configured in this environment** — this
is a real, disclosed constraint, not worked around by fabricating
output. Built as: a `DeterministicExplainer` (default, always
available, zero external calls, template-assembled prose that cites
real numbers — not "AI" in the generative sense, but satisfies "AI must
never invent findings" trivially) plus an `AnthropicExplainer` (real
SDK call, gated on `ATLAS_ANTHROPIC_API_KEY`, falls back to the
deterministic explainer on missing key or any API failure). The
Anthropic path is implemented and unit-tested with a mocked client, but
**not live-validated against a real model call** in this session — that
claim is not made anywhere in this feature's docs.

## Reuse, not new data collection

Technical Debt and Performance Analyzer read `files`, `quality`,
`semantic`, and `git_report` — all already computed by
`run_full_analysis` before these run. No new parsing, no new clone.

## Feature 1 — Technical Debt Engine (`technical_debt.py`)

Per-module debt score, 0-100 (higher = more debt), from four
independently-computed, capped components summed:

- **Complexity+churn** (0-40): this module's churn (commit count) ×
  its complexity-issue count (long_function/high_complexity from
  `QualityReport.issues`), normalized against the repo's own max, ×40.
  The multiplicative form means a module needs *both* factors present
  to score high here — matches Engineering Hotspots' existing "churn
  alone isn't debt" stance from the semantic engine.
- **Centrality+size** (0-25): fan-in-weighted betweenness (reused
  directly from `CriticalModule.criticality_score`) × function count,
  normalized, ×25 — a large, heavily-depended-upon module is riskier
  to change than an equally large, unused one.
- **Coupling/smell involvement** (0-20): flat 20 if the module appears
  in `semantic.coupling_issues` or `semantic.architectural_smells`
  (god module, excessive fan-out, utility dumping), 0 otherwise —
  binary, not scaled, since these are already-classified findings, not
  raw numbers to re-normalize.
- **Circular-cluster membership** (0-15): flat 15 if the module is
  listed in a `circular_import` QualityIssue's cluster, 0 otherwise.

`confidence`: "high" if the module has git history data (churn > 0
somewhere in the repo) and betweenness was computed
(`architecture_health.betweenness_computed`); "low" otherwise (e.g. a
repo with too many modules for betweenness, or no git history) — stated
per-module, not just once for the whole report, since confidence can
differ (a module with churn=0 in a repo that otherwise has git history
still has *some* real signal, just not the churn component).

Debt category is the label of whichever component contributed the most
points — not a separate classifier, just "which evidence dominated."

Top 15 modules by score. Recommended refactoring order = same list,
already sorted descending — not a separate algorithm.

**Debt Timeline**: only rendered when a `ComparisonReport` is available
(i.e. inside `/compare`, not the single-repo report) — a timeline needs
two points, which a single analysis doesn't have. Reuses
`comparison_engine`'s existing before/after pattern rather than adding
a new one.

## Feature 2 — Performance Analyzer (`performance_analyzer.py`)

Static-only, per the mandate — **never estimates runtime**. Checks run
per-function (from `FileSymbols.functions`, already parsed) and
per-module:

- **Very large function**: line span > 150 (3x the existing
  `quality_engine._LONG_FUNCTION_LINES` threshold of 50 — a function
  merely "long" is already a quality issue; a *performance* risk flag
  needs a much higher bar to not just duplicate that finding).
- **Deep nesting**: reuses `FunctionInfo.branch_count` as a proxy
  (Atlas's parser doesn't currently track nesting *depth* separately
  from branch *count* — stated as a real limitation, not a nesting-depth
  algorithm dressed up as one) — branch_count > 25 flagged as
  "high branch count, may indicate deep nesting" (hedged language, not
  an assertion of depth Atlas didn't actually measure).
- **Large parameter count**: Atlas's parser doesn't currently extract
  function signatures/parameter lists (`FunctionInfo` has no
  `parameters` field) — **not implemented**, disclosed as a limitation
  rather than approximated from something that isn't real evidence.
- **Heavy import concentration**: module fan-out ≥ repo's 95th
  percentile (reuses `semantic.coupling_issues`' `excessive_fan_out`/
  `god_module` findings directly — not a new computation).
- **Dependency bottleneck**: module is both an articulation point
  (`is_articulation_point`, computed in `semantic_analysis.py`) and in
  the dependency-criticality top 15 — every other module's import path
  may route through one file with no alternative.
- **Repeated imports** / **N² iteration patterns**: **not implemented**.
  Detecting either deterministically needs data Atlas doesn't parse
  (import statement bodies beyond the resolved target; loop-nesting
  AST structure). Disclosed as a limitation, not approximated.

Every finding cites the real number that triggered it (line span,
branch count, percentile) — same "evidence in the message" convention
as `security_scanner.py`/`quality_engine.py`.

## Feature 3+4 — AI Architect / AI Mentor (`ai_explain.py`)

One shared module, two thin call sites, since both need identical
plumbing (assemble evidence → explain) and differ only in framing
(Architect = describe the system; Mentor = teach from a specific
finding).

```
Explainer protocol: explain(prompt_kind, evidence: dict) -> ExplanationResult
  - DeterministicExplainer: string.Template-based, always succeeds
  - AnthropicExplainer: real API call, wraps DeterministicExplainer as
    its own fallback on ImportError (SDK not installed), missing key,
    or any request exception
```

`ExplanationResult` includes `source: "deterministic" | "anthropic"` —
every explanation discloses which one produced it, so a report reader
(or a test) can tell without guessing.

AI Architect prompt kinds: `architecture_summary`, `subsystem_summary`,
`dependency_explanation`, `critical_module_explanation`,
`layer_explanation`, `hotspot_explanation`, `repository_overview`.

AI Mentor: `explain_finding(finding)` — takes one concrete finding
(a `QualityIssue`, `SecurityIssue`, `CouplingIssue`, or
`ArchitecturalSmell` — already-typed Atlas objects, not free text) and
produces a grounded explanation + suggested refactoring framed as
teaching. Refuses (returns a fixed "insufficient evidence" result, not
a fabricated explanation) if given anything Atlas didn't actually flag.

## Integration

Both engines run inside `run_full_analysis`, feeding new Documentation
Report sections — this is also how frontend integration happens for
free: `MarkdownReport.tsx` already renders whatever markdown
`doc_generator` produces, so no frontend code changes are needed to
"add" these sections to the UI, matching the mandate's "keep UI
consistent, no redesign."

AI explanations are **not** run inside `run_full_analysis` by default
(an API call — even a deterministic-fallback one — adds latency to
every job regardless of whether anyone reads the explanation).
`/ai-architect` and `/ai-mentor` are separate, on-demand endpoints that
clone+analyze fresh (same pattern as `/git-intelligence`), not baked
into every job.

## API

- `POST /technical-debt` (repo_url) → `TechnicalDebtReport`
- `POST /performance-analysis` (repo_url) → `PerformanceReport`
- `POST /ai-architect` (repo_url, prompt_kind) → explanation +
  `source` field
- `POST /ai-mentor` (repo_url, finding reference) → explanation +
  `source` field

## Limitations (→ FAQ.md)

- Performance Analyzer doesn't detect N² patterns or large parameter
  counts (no signature/loop-structure parsing exists yet) — disclosed,
  not approximated.
- "Deep nesting" is inferred from branch count, not actual AST nesting
  depth.
- AI explanations, when the Anthropic path is used, are non-
  deterministic (the same evidence can produce differently-worded
  output on different calls) — the *evidence* is deterministic, the
  *prose* is not, and the report says so.
- The Anthropic integration is implemented and unit-tested with a
  mocked client, not live-validated against a real API call in this
  session (no credentials available).
