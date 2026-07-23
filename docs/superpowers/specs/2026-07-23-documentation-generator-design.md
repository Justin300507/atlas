# Atlas Phase 4: Documentation Generator (v1)

## Purpose

Phases 1-3 gave Atlas structure (stack, module/import/route graph), quality signals,
and Git history. Documentation Generator produces no new raw data — it's a
presentation layer that assembles everything those phases already computed into one
Markdown report a human can actually read, without needing to query four separate
endpoints and mentally merge the JSON. This is the natural next phase because it
consumes, rather than extends, the existing pipeline.

## Scope decisions for this phase

- **New endpoint, `POST /documentation`, not folded into `/analyze`.** Producing a
  full report needs both a structural clone (stack/parse/graph/quality — what
  `/analyze` already does) and a history clone (git intelligence — what
  `/git-intelligence` already does). Those two clone strategies are different
  (`shallow_clone` vs. `clone_with_history`) for the same reason Phase 3 kept them in
  separate endpoints: there's no shared clone to preserve by merging, so a new
  endpoint that calls both pipelines internally is cleaner than bolting a third clone
  strategy onto an existing route.
- **Markdown only, generated deterministically — no LLM call.** This keeps faith with
  Atlas's core architectural bet (deterministic analysis first, AI explains it later):
  every section here is a direct rendering of data Phases 1-3 already produce.
  Nothing in this phase is invented or summarized by a model. A future AI Mentor/AI
  Architect phase can turn this Markdown (or the underlying JSON) into prose — that's
  explicitly out of scope here.
- **Seven sections, chosen because each has a real subsystem behind it already.**
  Applying the same "honest scope" rule as Phase 2 (which shipped 2 of 6 originally-
  envisioned score categories rather than fabricate the other 4):
  1. **Executive Summary** — stack, file/module counts, overall quality score,
     commits analyzed. Pure aggregation of existing response fields.
  2. **Architecture Overview** — module/edge/route counts, plus the modules with the
     highest import in-degree (a cheap, real proxy for "most depended-upon" without
     needing a new centrality subsystem) — pure graph query.
  3. **Directory Guide** — file counts rolled up by top-level directory relative to
     repo root — a groupby over data Phase 1 already extracts.
  4. **API Reference** — every `(method, path)` route Phase 1's parser already finds,
     with its owning file.
  5. **Dependency Diagram** — the existing NetworkX module/import graph rendered as
     Mermaid `graph TD` syntax, capped at the top 40 nodes by degree so a large repo
     still produces a diagram someone could actually read (with a note when capped).
  6. **Risk Areas** — Phase 2's `QualityReport.issues`, grouped by severity, worst
     first. Not a new risk-scoring model — the exact same issues already computed.
  7. **Recent High-Churn Components** — the top of Phase 3's `GitIntelligenceReport.
     churn` list, since "which files change/break most" is exactly what a new hire
     or reviewer wants flagged.
- **Explicitly deferred (no subsystem exists yet, would require fabricating data):**
  - **Data Model** section — Atlas has no ORM/schema-model detector; a "data model"
    section with no real model-extraction behind it would be exactly the kind of
    fabricated category Phase 2 refused to ship for Security/Testing/Documentation
    scores. Deferred until a model-detection subsystem exists.
  - **Narrative Onboarding Guide** — a prose "here's how to get started" walkthrough
    needs synthesis/summarization, which is an AI Engine job (per the roadmap's
    "AI Architect" phase), not a deterministic-rendering job. v1 substitutes a
    **Getting Started** section built entirely from `StackReport` fields (detected
    backend/frontend/db/auth/deployment) — real detected facts, not generated prose.
  - **Ownership / co-change data in the report** — already fully exposed by
    `/git-intelligence` directly; duplicating the entire payload into the Markdown
    report would bloat it for no benefit. The Risk Areas / High-Churn sections are
    the two `/git-intelligence` and `/analyze` outputs judged most useful to surface
    inline; a reader who wants ownership/co-change detail calls that endpoint.

## Architecture

```
POST /documentation  { repo_url }
        │
        ├─ shallow_clone(url)          <- existing, reused as-is
        │     stack = detect(repo_path)
        │     files = [parse_file(p) for p in _iter_source_files(repo_path)]
        │     graph = build_graph(files)
        │     quality = analyze_quality(files, graph)
        │
        ├─ clone_with_history(url, depth=_GIT_HISTORY_COMMITS + 1)   <- existing, reused as-is
        │     commits, truncated = parse_git_log(repo_path, max_commits=_GIT_HISTORY_COMMITS)
        │     git_report = analyze_git_history(commits, truncated)
        │
        ▼
doc_generator.generate_documentation(
    repo_root: Path, stack, files, graph, quality, git_report
) -> str  (Markdown)
        │
        ▼
DocumentationResponse(markdown: str)
```

### Components

- **`doc_generator.py` (new)** — a single pure function,
  `generate_documentation(repo_root: Path, stack: StackReport, files: list[FileSymbols],
  graph: nx.DiGraph, quality: QualityReport, git_report: GitIntelligenceReport) -> str`,
  returning a Markdown string. No I/O — takes already-computed data, same "pure
  function over structured input" shape as `quality_engine.analyze_quality` and
  `git_intelligence.analyze_git_history`. `repo_root` is used only to render paths
  relative to the repo instead of the absolute temp-clone path (`FileSymbols.path` is
  an absolute filesystem path today, by existing Phase 1 design — that's unchanged;
  this function is the first consumer that needs a human-readable relative path, so
  it relativizes internally rather than changing what `FileSymbols.path` stores
  everywhere else).
- **`models.py` (modified)** — add `DocumentationResponse(markdown: str)`. Does not
  touch any existing model.
- **`main.py` (modified)** — add `POST /documentation`, performing both clones
  (reusing `shallow_clone`, `clone_with_history`, and every existing helper
  function/constant as-is) and calling `generate_documentation`.

## Report format details

- **Directory Guide** groups by the first path segment of each file's path relative
  to `repo_root` (files directly at repo root go under a literal `.` bucket), sorted
  by file count descending.
- **Architecture Overview**'s "most depended-upon modules" ranks module-type graph
  nodes by in-degree (number of other modules importing them) descending, top 10,
  ties broken by path for determinism.
- **Dependency Diagram** caps at the top 40 nodes by total degree (in + out). If the
  graph has more than 40 nodes, the diagram includes a `_(N of M modules shown, capped
  for readability)_` note — same truncation-honesty principle Phase 3 applied to
  commit history, applied here to diagram size instead.
- **Risk Areas** lists issues sorted by severity (`critical` > `important` > `minor`;
  `QualityIssue.severity` today only ever produces `"important"`/`"minor"` per
  Phase 2's `quality_engine.py`, so `"critical"` is included in the sort order for
  forward compatibility but won't appear from current data).
- **Recent High-Churn Components** takes `git_report.churn[:10]` (the list is already
  sorted descending and capped at 20 by Phase 3; this section just takes the top 10
  of that for a scannable report) and calls out `bug_fix_count > 0` explicitly.
- Every section that reports on possibly-partial data says so: quality section notes
  nothing extra (Phase 2 doesn't currently expose a truncation flag — out of scope to
  add here), but the Git section explicitly states `history_truncated` and
  `commits_analyzed` inline, since Phase 3 already computes that flag and hiding it in
  the generated report would undercut the reason it exists.

## Error handling

`generate_documentation` never raises for an empty repo (zero files, zero commits) —
it renders each section with an explicit "None detected" line rather than crashing,
same degrade-gracefully posture as every prior phase's engine.

## Testing

- Unit tests for `generate_documentation` against small hand-constructed
  `StackReport`/`FileSymbols` list/`nx.DiGraph`/`QualityReport`/`GitIntelligenceReport`
  inputs, asserting each section's expected content appears in the output string
  (e.g. a known route appears in the API Reference section, a known high-churn file
  appears in the churn section, directory grouping is correct for a 2-directory
  input).
- One test asserting the Mermaid diagram cap: a graph with 45 module nodes produces a
  diagram with the "capped for readability" note and no more than 40 module nodes
  rendered.
- One test for the empty-repo case (`files=[]`, `graph` with no nodes, zero-issue
  `QualityReport`, zero-commit `GitIntelligenceReport`) confirming no exception and
  every section still renders a header with a "None detected"-style line.
- One API-level test for `POST /documentation` with both `shallow_clone` and
  `clone_with_history` monkeypatched to yield local fixture repos (reusing the
  existing `fastapi_repo` fixture for structure, and a freshly-built local git repo
  for history — same monkeypatch pattern as the `/analyze` and `/git-intelligence`
  tests), asserting the response has a non-empty `markdown` field containing expected
  section headers.
- No live-network dependency added.

## Tech stack (this phase)

No new dependencies. Markdown/Mermaid are generated as plain strings — no templating
engine needed for this phase's fixed section set.

## Out of scope for this phase (explicitly deferred)

Data Model section (no ORM/schema detector subsystem), narrative Onboarding Guide
(needs an AI Engine, not built yet), any HTML/PDF rendering of the report (Markdown
only), persisting generated docs over time, and a frontend to display the report —
all consistent with prior phases' deferred-until-a-real-subsystem-exists discipline.
