# Semantic Repository Intelligence Engine — design spec

## Goal

Atlas's existing `graph_builder.py` produces a real import graph but only
ever reports raw counts off it (module/edge/route totals, top-10
in-degree). This engine adds real graph-theoretic and cross-signal
analysis on top of data Atlas already computes — no new parsing, no new
data collection, no LLM calls. Every finding must trace to a specific
computed number, exactly like every existing engine.

## What this explicitly does NOT attempt (and why)

Read this section before the "Fixed" one below — it's the difference
between this being a defensible v1 and an overclaimed one.

- **Feature envy, dependency inversion violations without a confirmed
  layer**: both require knowing intended architectural direction. Feature
  envy (a function using another module's data more than its own) isn't
  derivable from a file-level import graph at all — no function-to-data
  edges exist in the current model. Not attempted. Dependency-inversion
  violations *are* attempted, but only when layer detection (Phase 2)
  reaches its confidence threshold; with low confidence, nothing is
  reported rather than guessing a direction.
- **Facade detection is a heuristic, stated as one**: "high in-degree,
  low out-degree, filename is `__init__.py`/`index.{js,ts,jsx,tsx}`" is a
  real, checkable signal (Python/JS's own facade convention), not a
  guess about intent — but it's still a pattern match, not proof the
  module is *designed* as a facade. Reported as "facade pattern", not
  "this is a facade."
- **Layer detection can and will say "insufficient evidence"**: matched
  against a fixed vocabulary list (see Phase 2). A repo using
  unconventional naming gets no layer assignment rather than a forced,
  low-confidence guess. This directly gates layering-violation detection
  in Phase 5 — no layers, no violations reported.
- **No new visualizations beyond two Mermaid diagrams** (critical-module
  graph, subsystem graph gated on layer confidence): the existing
  dependency diagram already proved the "cap at N nodes, rank by
  degree" pattern works; reusing it rather than inventing a new
  rendering approach.

## Data already available (no new collection)

- `graph: nx.DiGraph` — module + route nodes, import + route edges
  (`graph_builder.py`).
- `files: list[FileSymbols]` — per-file functions (with line spans,
  branch counts), imports, class names (`code_parser.py`).
- `quality: QualityReport` — existing `long_function`/`high_complexity`
  issues, keyed by absolute file path.
- `git_report: GitIntelligenceReport` — churn keyed by **repo-relative**
  path (from `git log`, unlike everything else above which is
  absolute) — path normalization is required to join this with the
  graph/quality data, same as `quality_engine._relative()` already does.

## Phase 1 — Architecture metrics (`semantic_analysis.py`)

Computed once per module-only subgraph (`graph.subgraph(module_nodes)` —
route nodes excluded, same convention as `quality_engine`'s circular-
import detection and `doc_generator`'s diagram ranking, both of which
already learned the hard way that route edges pollute degree-based
ranking).

- `fan_in` / `fan_out`: import in/out-degree (NetworkX `in_degree`/
  `out_degree` on the import-only subgraph).
- `betweenness_centrality`, `closeness_centrality`: `nx.betweenness_centrality`/
  `nx.closeness_centrality`, standard NetworkX, no custom algorithm.
  O(V·E) for betweenness — see Performance below for the size guard.
- Strongly connected components: **already exists** in
  `quality_engine._find_circular_dependency_clusters`; reused, not
  reimplemented, to avoid two slightly-different definitions of "cycle"
  in the same report.
- Articulation points / bridges: `nx.articulation_points`/`nx.bridges`
  require an **undirected** view (`graph.to_undirected()`) — these are
  classically undirected-graph concepts (a module whose removal
  disconnects the graph doesn't have a natural directed analogue without
  picking a direction convention, so the standard undirected definition
  is used, same as every graph-theory reference for these).
- `dependency_criticality`: not a new metric, a **ranking** —
  `fan_in + betweenness_centrality * fan_in` (fan-in-weighted
  betweenness), top 15. Rationale: fan-in alone answers "who imports
  this" but not "does removing it fragment the graph"; betweenness
  alone can rank a low-fan-in bridge module above a widely-depended-on
  one that happens to sit in a well-connected cluster. The product
  favors modules that are both heavily used *and* structurally
  load-bearing — stated as a heuristic ranking, not a proof of "impact."

## Phase 2 — Layer detection

Fixed vocabulary, matched against each module's directory path segments
(case-insensitive substring match against path parts, not filenames —
`api/routes.py` matches "api", `src/api_client.py` does not, avoiding
a false match on an unrelated file that merely contains "api" in its
name):

```
presentation/ui/views/templates/components  → presentation
api/routes/controllers/endpoints            → api
services/handlers                           → service
domain/models/entities                      → domain
infrastructure/adapters/clients             → infrastructure
db/database/repositories/persistence/dao    → persistence
```

A module can match more than one layer's vocabulary (e.g. no
segment matches, or `api/services/foo.py` matches both `api` and
`service`) — resolved by **first matching segment wins, scanning path
segments left to right** (outermost directory is the strongest signal
for where a module "lives"). Confidence = `(modules assigned a layer) /
(total modules)`. **Below 40% confidence, Phase 2 reports "insufficient
evidence for layer detection" and assigns no layers at all** — this
also disables Phase 5's layering-violation check, per the "never guess"
requirement. 40% chosen deliberately low (not 80%+): the goal is
catching the *common* case of a repo using zero conventional naming,
not requiring near-total coverage — a repo where zero modules match any
layer keyword should say so; a repo where half do has enough signal to
be worth reporting on the half it found, but that's still a real
scope judgment, not derived from data, and is disclosed as such in the
report/FAQ, not framed as an empirically-tuned constant.

Layer *order* for violation detection uses the canonical order listed
above (presentation → api → service → domain → infrastructure →
persistence). A violation is an import edge from a later-layer module to
an earlier-layer module (e.g. persistence → presentation) — going the
"wrong way" per that fixed order. Same-layer edges are never flagged.

## Phase 3 — Engineering hotspots

`hotspot_score = normalize(churn) * normalize(centrality) * normalize(complexity)`
per module, where:
- `churn` = commit_count from `GitIntelligenceReport.churn` (0 if the
  module never appears — most files won't be in the top-20 churn list,
  so this is looked up from the *full* per-file commit counts computed
  inside `git_intelligence.py`, not just the already-truncated top-20
  list `GitIntelligenceReport` exposes — see "Wiring" below, this is
  the one place the existing report shape doesn't have what's needed
  and `analyze_git_history` gets a small additive return value, not a
  behavior change to its existing fields).
- `centrality` = fan_in + betweenness_centrality from Phase 1.
- `complexity` = count of this module's `long_function` +
  `high_complexity` issues from `QualityReport.issues` (already
  computed, just filtered by file).
- `normalize(x) = x / (max(x) or 1)` across all modules — each factor
  scaled 0–1 before multiplying, so no single factor's raw scale (churn
  counts vs. betweenness' 0–1 range vs. issue counts) dominates by unit
  choice alone.

Modules with `churn == 0` score 0 regardless of the other two factors —
deliberate: "hotspot" means *actively* risky, not just structurally
important or currently messy. A load-bearing module nobody has touched
in the analyzed window isn't a maintenance hotspot by this definition,
even if Phase 1 ranks it highly central.

## Phase 4 — Coupling analysis

All thresholds below are **percentile-based within the repo being
analyzed**, not fixed magic numbers — a 20-import fan-out means
something different in a 40-module repo than a 4,000-module one. Uses
`statistics.quantiles` (stdlib, no new dependency).

- **God module**: fan_out at or above the repo's own 95th percentile
  AND file has ≥15 functions (avoids flagging a small file that
  happens to import a lot — e.g. a routes-registration file — as a
  "god module" purely on import count with no accompanying size).
- **Excessive fan-out**: fan_out ≥ 95th percentile alone (no size
  gate) — reported separately from "god module" since high fan-out
  without size is a different, milder smell (a thin orchestration
  layer, not necessarily a dumping ground).
- **Dependency concentration**: repo-level, not per-module — what
  fraction of all import edges point at the top 5 modules by fan_in.
  Reported as one number (e.g. "the top 5 modules receive 34% of all
  import edges") with no fixed pass/fail threshold — this is
  descriptive context for a human reader, not a finding with a
  severity, since there's no principled universal "healthy"
  concentration percentage to assert.

## Phase 5 — Architectural smells

- **Circular dependencies**: reused from `quality_engine`, not
  reimplemented (see Phase 1).
- **Isolated components**: `fan_in == 0 and fan_out == 0` in the
  import-only subgraph. Real and unambiguous — a module the import
  graph shows zero connection to.
- **Facade pattern**: filename is `__init__.py` or
  `index.{js,jsx,ts,tsx}`, AND fan_in ≥ repo's 75th percentile, AND
  fan_out ≤ repo's 25th percentile. Stated as a pattern match (see
  scope-cuts section above), not an intent claim.
- **Utility dumping**: fan_in ≥ 75th percentile AND fan_out ≤ 25th
  percentile AND ≥15 functions AND filename does *not* match the
  facade pattern above (a genuine utils/helpers module gets imported
  everywhere, exports little, and — unlike a facade — actually
  contains substantial unrelated logic rather than just re-exporting).
- **Layering violations**: gated on Phase 2 reaching its confidence
  threshold (see above). Each violating edge reported individually,
  capped at 20 shown (same convention as Risk Areas/Security Findings).

## Phase 6 — Report sections

New sections in `doc_generator.py`, inserted after the existing
Architecture Overview (keeps the existing five original sections'
positions stable — no reordering of what's already there):

- **Architecture Health** — Phase 1 summary: module/edge counts already
  shown, plus SCC count (already computed, just displayed), articulation
  point count, bridge count.
- **Dependency Criticality** — top 15 ranked list from Phase 1.
- **Engineering Hotspots** — top 15 ranked list from Phase 3.
- **Coupling & Architectural Smells** — Phase 4 + Phase 5 findings,
  combined into one section (both are "structural problems", splitting
  them into two sections read as more separate than the underlying
  analysis actually is).
- **Subsystem Overview** — Phase 2 layer breakdown (module count per
  layer) if confidence threshold met, otherwise one line stating layer
  detection didn't reach enough confidence and why (coverage %).

## Phase 7 — Visualizations

Two new Mermaid diagrams, both reusing `doc_generator._dependency_diagram`'s
existing cap-and-rank pattern (not a new rendering approach):
- **Critical module graph**: top 15 by dependency_criticality, edges
  between them only (same "both endpoints in the selected set" rule as
  the existing diagram).
- **Subsystem graph**: one node per detected layer, edge weight = import
  edge count between layers. Only rendered if Phase 2 met its confidence
  threshold — no diagram, not a low-confidence one, otherwise.

## Performance

Betweenness centrality is O(V·E) — the one genuinely expensive addition.
Guarded the same way the existing co-change analysis guards its own
O(k²) risk (`git_intelligence._MAX_FILES_PER_COMMIT_FOR_COCHANGE`): a
module-count ceiling (`_MAX_MODULES_FOR_BETWEENNESS`, see implementation)
above which betweenness is skipped and Phase 1's report says so
explicitly, rather than silently taking minutes on a Django-scale repo.
Measured against real repos before picking the exact constant — see the
validation results in the implementation commits/report, not asserted
here in advance.

## Known limitations (to fold into `FAQ.md` once implemented)

- Layer detection depends entirely on directory-naming convention; a
  repo that organizes by feature (not by layer) will correctly get "no
  layers detected", not a wrong answer, but also not the layering
  analysis at all.
- Betweenness centrality is skipped above the module-count ceiling — see
  Performance above for the actual number, determined empirically.
- Facade/utility-dumping detection is percentile-based within the one
  repo being analyzed — a repo with unusually uniform fan-in/fan-out
  across all modules may report smells that a human wouldn't consider
  meaningfully "high", since even the 95th percentile of a flat
  distribution is still just "the top values that happen to exist."
- **Found while writing tests, not by inspection**: percentile
  thresholds degenerate to the floor value (usually 0) when the large
  majority of modules share that value — a repo where e.g. 90%+ of
  modules have zero fan-out will compute p95_fan_out = 0, which the
  `p95 > 0` guard correctly turns into "report nothing" rather than
  "flag everything with fan_out >= 0." This is the right behavior (no
  real variance to rank against), not a bug, but it does mean coupling/
  smell detection under-reports on repos with very sparse, undifferentiated
  connectivity — validated as working correctly on real repos (59-module
  Atlas itself, plus the real-repo validation batch) where fan-in/fan-out
  distributions have enough natural spread for the percentiles to be
  meaningful. Documented and regression-tested
  (`test_sparse_repo_with_no_variance_reports_no_coupling_findings`), not
  silently discovered later.
