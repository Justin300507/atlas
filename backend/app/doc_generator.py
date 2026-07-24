from __future__ import annotations

from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols
from .models import (
    ComparisonFinding,
    ComparisonReport,
    DebtModule,
    FileCoverage,
    GitIntelligenceReport,
    PerformanceFinding,
    PerformanceReport,
    QualityIssue,
    QualityReport,
    SecurityIssue,
    SecurityReport,
    SemanticReport,
    StackReport,
    TechnicalDebtReport,
)
from .security_scanner import _looks_like_test_path
from .semantic_analysis import _LAYER_ORDER

_DIAGRAM_NODE_CAP = 40
_HIGH_CHURN_LIMIT = 10
_RISK_AREAS_LIMIT = 20
_PERFORMANCE_FINDINGS_LIMIT = 20
_DEBT_CONCENTRATION_TOP_N = 3
_COMPARISON_DIAGRAM_CAP = 15
_SECURITY_FINDINGS_LIMIT = 20
_SEVERITY_ORDER = {"critical": 0, "important": 1, "minor": 2}
_CRITICAL_MODULE_DIAGRAM_CAP = 15


def generate_documentation(
    repo_root: Path,
    stack: StackReport,
    files: list[FileSymbols],
    graph: nx.DiGraph,
    quality: QualityReport,
    security: SecurityReport,
    git_report: GitIntelligenceReport,
    coverage: FileCoverage | None = None,
    semantic: SemanticReport | None = None,
    debt: TechnicalDebtReport | None = None,
    performance: PerformanceReport | None = None,
) -> str:
    sections = [
        _executive_summary(stack, files, quality, security, git_report, coverage, semantic, debt),
        _architecture_overview(graph),
    ]
    if semantic is not None:
        sections.append(_architecture_health(semantic))
        sections.append(_dependency_criticality(repo_root, semantic, graph))
        sections.append(_subsystem_overview(repo_root, semantic))
    sections.extend(
        [
            _directory_guide(repo_root, files),
            _api_reference(repo_root, files),
            _dependency_diagram(repo_root, graph),
            _risk_areas(repo_root, quality),
        ]
    )
    if semantic is not None:
        sections.append(_engineering_hotspots(semantic))
        sections.append(_coupling_and_smells(semantic))
    if debt is not None:
        sections.append(_technical_debt(debt))
    if performance is not None:
        sections.append(_performance_analysis(performance))
    sections.extend(
        [
            _security_findings(repo_root, security),
            _high_churn_components(git_report),
            _analysis_coverage(),
            _executive_recommendations(semantic, debt, performance),
        ]
    )
    return "\n\n".join(sections) + "\n"


def _relative(repo_root: Path, path: str) -> str:
    try:
        return PurePath(Path(path).relative_to(repo_root)).as_posix()
    except ValueError:
        return PurePath(path).as_posix()


_HEALTH_LABEL_THRESHOLDS = [(85, "Strong"), (70, "Good"), (50, "Moderate")]
_HEALTH_LABEL_DEFAULT = "Needs attention"

# A documented starting point (like the other score thresholds in this
# file), not empirically tuned -- no historical corpus of "does a human
# agree this repo's health is Strong/Good/Moderate" exists yet.
def _health_label(score: int) -> str:
    for floor, label in _HEALTH_LABEL_THRESHOLDS:
        if score >= floor:
            return label
    return _HEALTH_LABEL_DEFAULT


# "Concentrated" here means the same threshold used to decide whether the
# Technical Debt section's own concentration note is worth showing at all
# -- half or more of the combined debt score sitting in just the top 3
# modules is a genuinely lopsided distribution, not an arbitrary cutoff.
_DEBT_CONCENTRATION_NARRATIVE_THRESHOLD = 0.5


def _health_qualifiers(
    semantic: SemanticReport | None, debt: TechnicalDebtReport | None
) -> list[str]:
    # A numeric-score bucket alone can read as more reassuring than the
    # underlying evidence supports -- e.g. "Good overall quality" next to
    # 3 circular-dependency clusters and several god modules read as
    # contradictory. Each qualifier here is a plain presence check against
    # a finding already computed and shown elsewhere in the report -- not
    # a new judgment call, just surfacing what's already there next to the
    # headline label. Reported (2026-07-24).
    qualifiers: list[str] = []
    if semantic is not None:
        if semantic.architecture_health.circular_cluster_count > 0:
            qualifiers.append("circular-dependency clusters")
        if any(c.kind == "god_module" for c in semantic.coupling_issues):
            qualifiers.append("god-module coupling")
    if debt is not None and debt.top_debt_modules:
        ratio = _debt_concentration_ratio(debt.top_debt_modules)
        if ratio is not None and ratio >= _DEBT_CONCENTRATION_NARRATIVE_THRESHOLD:
            qualifiers.append("concentrated technical debt")
    return qualifiers


def _executive_summary(
    stack: StackReport,
    files: list[FileSymbols],
    quality: QualityReport,
    security: SecurityReport,
    git_report: GitIntelligenceReport,
    coverage: FileCoverage | None = None,
    semantic: SemanticReport | None = None,
    debt: TechnicalDebtReport | None = None,
) -> str:
    lines = ["## Executive Summary", ""]
    for label, value in [
        ("Backend", stack.backend),
        ("Frontend", stack.frontend),
        ("Database", stack.database),
        ("Auth", stack.auth),
        ("Deployment", stack.deployment),
        ("Architecture", stack.architecture),
    ]:
        lines.append(f"- {label}: {value or 'Not detected'}")
    lines.append(f"- Files analyzed: {len(files)}{_coverage_note(coverage)}")
    lines.append(
        f"- Overall quality score: {quality.overall_score}/100 "
        f"(maintainability {quality.maintainability_score}, architecture {quality.architecture_score})"
    )
    # Requested: "a short narrative helps readers understand the report
    # before diving into details" -- and a note on what actually drives the
    # numbers, since a plausible-sounding guess at the formula (dependency
    # concentration, coupling, modularity) would be wrong: architecture
    # score is purely circular-dependency-cluster-based, maintainability is
    # purely function-length/complexity/naming-based. Neither factors in
    # coupling, dependency concentration, bridges, or articulation points
    # -- those are computed and reported (Architecture Health, Dependency
    # Criticality, Coupling & Smells) but deliberately don't feed into this
    # score. Widening the formula to include them would change what every
    # existing comparison/snapshot means, so that's a real design decision
    # for its own pass, not a wording fix (2026-07-24).
    qualifiers = _health_qualifiers(semantic, debt)
    qualifier_clause = f", with {', '.join(qualifiers)}" if qualifiers else ""
    lines.append(
        f"- Repository health: {_health_label(quality.overall_score)} overall quality"
        f"{qualifier_clause}."
    )
    lines.append(
        "  _Maintainability reflects how often functions exceed length/complexity/"
        "naming thresholds, as a proportion rather than a raw count. Architecture "
        "score reflects circular-dependency clusters only (how many, how large, and "
        "how many modules participate) -- bridges, articulation points, dependency "
        "concentration, coupling, and dependency criticality are analyzed and shown "
        "separately below but don't feed into this score. Overall is the average of "
        "the two._"
    )
    # A reader who sees "100/100" and only later scrolls to a critical
    # security finding reasonably reads that as contradictory -- the score
    # never included security to begin with, but nothing said so. State it
    # explicitly, right next to the score, every time. Reported by a user
    # reading a real one-file repo's report (2026-07-24).
    lines.append(f"- Security findings: {_security_summary(security)} -- not reflected in the score above")
    truncation_note = " (history truncated)" if git_report.history_truncated else ""
    lines.append(f"- Commits analyzed: {git_report.commits_analyzed}{truncation_note}")
    return "\n".join(lines)


def _security_summary(security: SecurityReport) -> str:
    counts = {"critical": 0, "important": 0, "minor": 0}
    for issue in security.issues:
        if issue.severity in counts:
            counts[issue.severity] += 1
    if not security.issues:
        return "none detected"
    return f"{counts['critical']} critical, {counts['important']} important, {counts['minor']} minor"


def _coverage_note(coverage: FileCoverage | None) -> str:
    if coverage is None:
        return ""
    notes = []
    if coverage.files_capped:
        notes.append("repository truncated at the file-count cap")
    if coverage.files_skipped_oversized:
        notes.append(f"{coverage.files_skipped_oversized} skipped for exceeding the size limit")
    if coverage.files_parse_failed:
        notes.append(f"{coverage.files_parse_failed} failed to parse")
    return f" ({'; '.join(notes)})" if notes else ""


def _architecture_overview(graph: nx.DiGraph) -> str:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    route_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "route"]
    import_edges = [1 for _, _, d in graph.edges(data=True) if d.get("type") == "import"]

    if len(module_nodes) <= 1:
        # A single module has zero possible import edges by definition --
        # showing "Modules: 1 / Import edges: 0 / Routes: 0" isn't a
        # finding, it's a guaranteed consequence of size. Say so instead of
        # implying the analysis ran and came up empty. Reported against a
        # real one-file repo (2026-07-24).
        return "\n".join(
            [
                "## Architecture Overview",
                "",
                "Repository has 1 module or fewer -- too small for "
                "meaningful architecture/dependency-graph analysis. "
                "Import-graph metrics below (dependency concentration, "
                "coupling, criticality ranking) are omitted rather than "
                "shown as trivially zero.",
            ]
        )

    lines = [
        "## Architecture Overview",
        "",
        f"- Modules: {len(module_nodes)}",
        f"- Import edges: {len(import_edges)}",
        f"- Routes: {len(route_nodes)}",
    ]

    if module_nodes:
        by_in_degree = sorted(module_nodes, key=lambda n: (-graph.in_degree(n), n))[:10]
        top = [(n, graph.in_degree(n)) for n in by_in_degree if graph.in_degree(n) > 0]
        if top:
            lines.append("")
            lines.append("Most depended-upon modules:")
            for path, count in top:
                lines.append(f"- {PurePath(path).name} ({count} importers)")

    return "\n".join(lines)


def _architecture_health(semantic: SemanticReport) -> str:
    h = semantic.architecture_health
    if h.module_count <= 1:
        # Circular clusters, articulation points, bridges, and dependency
        # concentration are all trivially zero for a single-module repo --
        # matches the Architecture Overview note above, not a separate
        # "insufficient evidence" case.
        return "\n".join(
            [
                "## Architecture Health",
                "",
                "Repository has 1 module or fewer -- architecture-health "
                "metrics (circular clusters, articulation points, bridges, "
                "dependency concentration) require more than one module to "
                "be meaningful and are omitted here.",
            ]
        )
    lines = [
        "## Architecture Health",
        "",
        f"- Strongly connected (circular-dependency) clusters: {h.circular_cluster_count}",
        "- Articulation points (single modules whose removal disconnects the "
        f"import graph): {h.articulation_point_count}",
        "- Bridge edges (single import edges whose removal disconnects the "
        f"import graph): {h.bridge_count}",
        "- Dependency concentration: the top 5 most-depended-upon modules "
        f"receive {h.dependency_concentration_top5_ratio:.0%} of all import edges",
    ]
    if not h.betweenness_computed:
        lines.append("")
        lines.append(
            f"_Betweenness/closeness centrality skipped — {h.module_count} modules "
            "exceeds this analysis' computation ceiling. Dependency Criticality below "
            "is ranked by fan-in only for this repository, not the fan-in-weighted "
            "betweenness used on smaller repos._"
        )
    return "\n".join(lines)


def _dependency_criticality(repo_root: Path, semantic: SemanticReport, graph: nx.DiGraph) -> str:
    lines = [
        "## Dependency Criticality",
        "",
        "Modules ranked by how much of the codebase would likely be affected if "
        "they changed — fan-in weighted by betweenness centrality (how often a "
        "module sits on the only path between two others), not fan-in alone. A "
        "heuristic ranking, not a proof of impact.",
    ]
    if not semantic.critical_modules:
        lines.append("")
        lines.append("No modules with incoming dependencies detected.")
        return "\n".join(lines)

    lines.append("")
    lines.append("| Module | Fan-in | Fan-out | Betweenness |")
    lines.append("|---|---:|---:|---:|")
    for m in semantic.critical_modules:
        lines.append(f"| {m.file} | {m.fan_in} | {m.fan_out} | {m.betweenness:.3f} |")

    diagram = _critical_module_diagram(repo_root, semantic, graph)
    if diagram:
        lines.append("")
        lines.append(diagram)
    return "\n".join(lines)


def _critical_module_diagram(repo_root: Path, semantic: SemanticReport, graph: nx.DiGraph) -> str:
    selected = {m.file for m in semantic.critical_modules[:_CRITICAL_MODULE_DIAGRAM_CAP]}
    if not selected:
        return ""

    node_ids: dict[str, str] = {}
    diagram_lines = ["```mermaid", "graph TD"]
    drawn = False
    for u, v, d in graph.edges(data=True):
        if d.get("type") != "import":
            continue
        ru, rv = _relative(repo_root, u), _relative(repo_root, v)
        if ru not in selected or rv not in selected:
            continue
        for rel in (ru, rv):
            if rel not in node_ids:
                node_ids[rel] = f"n{len(node_ids)}"
        diagram_lines.append(
            f'    {node_ids[ru]}["{PurePath(ru).name}"] --> {node_ids[rv]}["{PurePath(rv).name}"]'
        )
        drawn = True
    diagram_lines.append("```")
    return "\n".join(diagram_lines) if drawn else ""


def _subsystem_overview(repo_root: Path, semantic: SemanticReport) -> str:
    s = semantic.subsystem_overview
    lines = ["## Subsystem Overview", ""]
    if not s.confident:
        lines.append(
            f"Insufficient evidence for layer detection — only {s.coverage_ratio:.0%} of "
            "modules matched a recognized layer-naming convention (presentation / api / "
            "service / domain / infrastructure / persistence). Not guessing at this "
            "repository's architecture rather than forcing a low-confidence answer."
        )
        return "\n".join(lines)

    lines.append(
        f"Layer detection matched {s.coverage_ratio:.0%} of modules against a fixed "
        "directory-naming vocabulary:"
    )
    lines.append("")
    lines.append("| Layer | Modules |")
    lines.append("|---|---:|")
    for layer in _LAYER_ORDER:
        if layer in s.layer_counts:
            lines.append(f"| {layer} | {s.layer_counts[layer]} |")

    if s.layer_edges:
        lines.append("")
        lines.append("```mermaid")
        lines.append("graph TD")
        for e in s.layer_edges:
            lines.append(f'    {e.from_layer}["{e.from_layer}"] -->|"{e.edge_count}"| {e.to_layer}["{e.to_layer}"]')
        lines.append("```")
    return "\n".join(lines)


def _engineering_hotspots(semantic: SemanticReport) -> str:
    lines = [
        "## Engineering Hotspots",
        "",
        "Modules ranked by git churn × dependency centrality × complexity issues, "
        "each factor normalized against this repository before multiplying. A module "
        "with zero recent churn never appears here regardless of how central or "
        "complex it is — this section is about active maintenance risk, not general "
        "importance.",
    ]
    if not semantic.hotspots:
        lines.append("")
        lines.append("No modules had all three risk factors (churn, centrality, complexity) present.")
        return "\n".join(lines)

    lines.append("")
    lines.append("| Module | Churn (commits) | Centrality | Complexity issues | Hotspot score |")
    lines.append("|---|---:|---:|---:|---:|")
    for h in semantic.hotspots:
        lines.append(
            f"| {h.file} | {h.churn} | {h.centrality:.3f} | {h.complexity_issues} | {h.hotspot_score:.3f} |"
        )
    return "\n".join(lines)


def _coupling_and_smells(semantic: SemanticReport) -> str:
    lines = ["## Coupling & Architectural Smells", ""]
    findings = [(i.severity, i.kind, i.file, i.message) for i in semantic.coupling_issues]
    findings += [(s.severity, s.kind, s.file, s.message) for s in semantic.architectural_smells]
    if not findings:
        lines.append("No coupling issues or architectural smells detected.")
        return "\n".join(lines)

    findings.sort(key=lambda f: _SEVERITY_ORDER.get(f[0], 99))
    for severity, kind, file, message in findings:
        lines.append(f"- **{severity}** `{file}` {kind}: {message}")
    return "\n".join(lines)


def _technical_debt(debt: TechnicalDebtReport) -> str:
    lines = [
        "## Technical Debt",
        "",
        "Modules ranked by a weighted combination of complexity-under-churn, "
        "dependency-criticality-under-size, coupling/architectural smells, and "
        "circular-dependency membership. Confidence is `low` where git history "
        "or betweenness centrality was unavailable for this repository — the "
        "score itself is still shown, but treat it as a rougher estimate.",
    ]
    if not debt.top_debt_modules:
        lines.append("")
        lines.append("No modules had any of the four debt signals present.")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"Average debt score across flagged modules: {debt.average_debt_score:.2f}")
    lines.append("")
    lines.append("| Module | Debt score | Primary driver | Confidence | Evidence |")
    lines.append("|---|---:|---|:-:|---|")
    for m in debt.top_debt_modules:
        lines.append(
            f"| {m.file} | {m.debt_score:.2f} | {m.category} | {m.confidence} | "
            f"{'; '.join(m.evidence)} |"
        )

    concentration = _debt_concentration_note(debt.top_debt_modules)
    if concentration:
        lines.append("")
        lines.append(concentration)
    return "\n".join(lines)


def _debt_concentration_ratio(modules: list[DebtModule]) -> float | None:
    if len(modules) <= _DEBT_CONCENTRATION_TOP_N:
        return None
    total = sum(m.debt_score for m in modules)
    if total <= 0:
        return None
    top_total = sum(m.debt_score for m in modules[:_DEBT_CONCENTRATION_TOP_N])
    return top_total / total


def _debt_concentration_note(modules: list[DebtModule]) -> str | None:
    # A reader shouldn't have to eyeball a 15-row table to tell whether
    # debt is spread evenly or concentrated in a handful of modules --
    # state the measured concentration among the modules actually shown.
    # Deliberately doesn't name *why* those modules are central (Atlas
    # doesn't know their purpose, e.g. "orchestration") -- only the
    # measured score concentration, which it does know.
    ratio = _debt_concentration_ratio(modules)
    if ratio is None:
        return None
    return (
        f"The top {_DEBT_CONCENTRATION_TOP_N} of the {len(modules)} modules shown account for "
        f"{ratio:.0%} of their combined debt score."
    )


def _performance_analysis(performance: PerformanceReport) -> str:
    lines = [
        "## Performance Analysis",
        "",
        "Static, deterministic signals only — Atlas doesn't execute code or "
        "profile runtime behavior, so nothing here is a measured performance "
        "cost. Findings marked `low` confidence are proxy signals, not direct "
        "measurements.",
    ]
    if not performance.findings:
        lines.append("")
        lines.append("No performance findings detected.")
        return "\n".join(lines)

    lines.append("")
    ordered = sorted(performance.findings, key=lambda f: (f.confidence != "high", f.file, f.line))
    lines.extend(_findings_by_kind_breakdown(ordered, _PERFORMANCE_FINDINGS_LIMIT))
    shown = ordered[:_PERFORMANCE_FINDINGS_LIMIT]
    for f in shown:
        location = f"{f.file}:{f.line}" if f.line else f.file
        lines.append(f"- **{f.confidence} confidence** `{location}` {f.kind}: {f.message}")

    remainder = len(ordered) - len(shown)
    if remainder > 0:
        lines.append("")
        lines.append(f"_...and {remainder} additional findings._")

    if performance.bottleneck_modules:
        lines.append("")
        lines.append("Dependency bottlenecks (critical-path modules also flagged for coupling):")
        for module in performance.bottleneck_modules:
            lines.append(f"- {module}")
    return "\n".join(lines)


def _directory_guide(repo_root: Path, files: list[FileSymbols]) -> str:
    counts: dict[str, int] = {}
    for f in files:
        rel = _relative(repo_root, f.path)
        parts = rel.split("/")
        top_dir = parts[0] if len(parts) > 1 else "."
        counts[top_dir] = counts.get(top_dir, 0) + 1

    lines = ["## Directory Guide", ""]
    if not counts:
        lines.append("No files detected.")
        return "\n".join(lines)
    if len(counts) == 1:
        # A one-row table ("." | 1) isn't a breakdown -- it's the same fact
        # ("Files analyzed") restated as a table. Say it as a sentence
        # instead. Reported against a real one-file repo (2026-07-24).
        (only_dir, only_count) = next(iter(counts.items()))
        location = "the repository root" if only_dir == "." else f"`{only_dir}`"
        lines.append(f"All {only_count} file(s) are in {location} -- not enough directory structure for a breakdown.")
        return "\n".join(lines)

    lines.append("| Directory | Files |")
    lines.append("|---|---|")
    for directory, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {directory} | {count} |")
    return "\n".join(lines)


def _api_reference(repo_root: Path, files: list[FileSymbols]) -> str:
    lines = ["## API Reference", ""]
    all_rows = [(method, path, f) for f in files for method, path in f.routes]

    # Routes defined in test/fixture files (mock servers, reliability
    # harnesses, example endpoints) aren't part of the production API a
    # caller would actually hit -- reuses security_scanner's own test-path
    # heuristic rather than inventing a second one. Reported against a real
    # 440-file repo whose API Reference included backend/tests/
    # reliability/... routes (2026-07-24).
    rows = [
        (method, path, _relative(repo_root, f.path))
        for method, path, f in all_rows
        if not _looks_like_test_path(f.path)
    ]
    excluded = len(all_rows) - len(rows)
    exclusion_note = (
        f"_{excluded} additional route(s) found only in test/fixture paths -- "
        "excluded as not part of the production API._"
        if excluded
        else None
    )

    if not rows:
        lines.append("No production routes detected.")
        if exclusion_note:
            lines.append("")
            lines.append(exclusion_note)
        return "\n".join(lines)

    lines.append("| Method | Path | File |")
    lines.append("|---|---|---|")
    for method, path, file in sorted(rows, key=lambda r: (r[2], r[1])):
        lines.append(f"| {method} | {path} | {file} |")
    if exclusion_note:
        lines.append("")
        lines.append(exclusion_note)
    return "\n".join(lines)


def _system_overview_diagram(repo_root: Path, graph: nx.DiGraph) -> str:
    """A directory-level rollup of the import graph. Two parts: a module-
    count line covering every top-level directory that has at least one
    parsed source module (not just ones with cross-directory import
    edges -- a real repo's tests/ and docs/ directories had real file
    counts but no import edges to backend/, so they were invisible in an
    edges-only diagram), and a Mermaid diagram of the cross-directory
    import edges themselves. Shown only when the detailed module diagram
    is large enough to be capped, since that's exactly when a single
    module-level diagram stops being readable. Reported: "for
    repositories this large, render two graphs" / "expand it slightly to
    show key top-level directories" (2026-07-24)."""
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    dir_of: dict[str, str] = {}
    for n in module_nodes:
        rel = _relative(repo_root, n)
        parts = rel.split("/")
        dir_of[n] = parts[0] if len(parts) > 1 else "."

    dir_counts: dict[str, int] = {}
    for d in dir_of.values():
        dir_counts[d] = dir_counts.get(d, 0) + 1

    edge_counts: dict[tuple[str, str], int] = {}
    for u, v, d in graph.edges(data=True):
        if d.get("type") != "import" or u not in dir_of or v not in dir_of:
            continue
        du, dv = dir_of[u], dir_of[v]
        if du == dv:
            continue  # only cross-directory structure belongs in an overview
        edge_counts[(du, dv)] = edge_counts.get((du, dv), 0) + 1

    if len(dir_counts) <= 1 and not edge_counts:
        return ""

    lines: list[str] = []
    if len(dir_counts) > 1:
        ranked = sorted(dir_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append(
            "Top-level directories with analyzed source modules: "
            + ", ".join(f"`{d}` ({c})" for d, c in ranked)
            + ". Non-code directories (docs, config, etc.) aren't part of "
            "the import graph and don't appear here."
        )
        lines.append("")

    if edge_counts:
        dir_names = sorted({d for pair in edge_counts for d in pair})
        node_ids = {d: f"d{i}" for i, d in enumerate(dir_names)}
        lines.append("```mermaid")
        lines.append("graph TD")
        for (du, dv), count in sorted(edge_counts.items()):
            lines.append(f'    {node_ids[du]}["{du}"] -->|"{count}"| {node_ids[dv]}["{dv}"]')
        lines.append("```")
    else:
        lines.append("_No cross-directory import edges detected between top-level directories._")
    return "\n".join(lines)


def _dependency_diagram(repo_root: Path, graph: nx.DiGraph) -> str:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    lines = ["## Dependency Diagram", ""]
    if not module_nodes:
        lines.append("No modules detected.")
        return "\n".join(lines)

    # Rank by import-edge degree only: this diagram only ever draws import
    # edges, so ranking by total graph degree (which route edges also count
    # toward) can let an import-disconnected, route-heavy module consume a
    # cap slot while rendering as an invisible, edge-less node.
    import_degree: dict[str, int] = dict.fromkeys(module_nodes, 0)
    for u, v, d in graph.edges(data=True):
        if d.get("type") != "import":
            continue
        if u in import_degree:
            import_degree[u] += 1
        if v in import_degree:
            import_degree[v] += 1

    selected = sorted(module_nodes, key=lambda n: (-import_degree[n], n))[:_DIAGRAM_NODE_CAP]
    selected_set = set(selected)
    node_ids = {n: f"n{i}" for i, n in enumerate(selected)}
    is_capped = len(module_nodes) > _DIAGRAM_NODE_CAP

    if is_capped:
        overview = _system_overview_diagram(repo_root, graph)
        if overview:
            lines.append(
                "This repository is large enough that a single module-level "
                "diagram isn't readable on its own -- a directory-level "
                "**System Overview** is shown first, followed by the "
                "**Detailed Module Diagram** below it."
            )
            lines.append("")
            lines.append("**System Overview**")
            lines.append("")
            lines.append(overview)
            lines.append("")
            lines.append("**Detailed Module Diagram**")
            lines.append("")

    lines.append("```mermaid")
    lines.append("graph TD")
    for u, v, d in graph.edges(data=True):
        if d.get("type") == "import" and u in selected_set and v in selected_set:
            lines.append(
                f'    {node_ids[u]}["{PurePath(u).name}"] --> {node_ids[v]}["{PurePath(v).name}"]'
            )
    lines.append("```")

    if is_capped:
        lines.append("")
        lines.append(
            f"_({len(selected)} of {len(module_nodes)} modules shown, capped for readability)_"
        )
    return "\n".join(lines)


def _findings_by_kind_breakdown(
    ordered: list[QualityIssue] | list[SecurityIssue] | list[PerformanceFinding], limit: int
) -> list[str]:
    # A flat capped list gives no sense of shape when there are hundreds of
    # findings -- a reader facing "...and 576 additional findings" has no
    # way to tell whether that's 576 near-duplicates of one pattern or 576
    # genuinely distinct problems. Only shown when the cap actually hides
    # something. Reported against a real 440-file repo (2026-07-24).
    if len(ordered) <= limit:
        return []
    kind_counts: dict[str, int] = {}
    for issue in ordered:
        kind_counts[issue.kind] = kind_counts.get(issue.kind, 0) + 1
    plural = "y" if len(kind_counts) == 1 else "ies"
    lines = [f"{len(ordered)} findings across {len(kind_counts)} categor{plural}:", ""]
    for kind, count in sorted(kind_counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"- {kind}: {count}")
    lines.append("")
    lines.append(f"Highest-severity findings shown below (top {limit}):")
    lines.append("")
    return lines


def _risk_areas(repo_root: Path, quality: QualityReport) -> str:
    lines = ["## Risk Areas", ""]
    if not quality.issues:
        lines.append("No issues detected.")
        return "\n".join(lines)

    ordered = sorted(quality.issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))
    lines.extend(_findings_by_kind_breakdown(ordered, _RISK_AREAS_LIMIT))
    shown = ordered[:_RISK_AREAS_LIMIT]
    for issue in shown:
        rel = _relative(repo_root, issue.file)
        lines.append(f"- **{issue.severity}** `{rel}:{issue.line}` {issue.kind}: {issue.message}")

    remainder = len(ordered) - len(shown)
    if remainder > 0:
        lines.append("")
        lines.append(f"_...and {remainder} additional findings._")
    return "\n".join(lines)


def _security_findings(repo_root: Path, security: SecurityReport) -> str:
    lines = ["## Security Findings", ""]
    if not security.issues:
        lines.append("No issues detected.")
        return "\n".join(lines)

    ordered = sorted(security.issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))
    lines.extend(_findings_by_kind_breakdown(ordered, _SECURITY_FINDINGS_LIMIT))
    shown = ordered[:_SECURITY_FINDINGS_LIMIT]
    for issue in shown:
        rel = _relative(repo_root, issue.file)
        lines.append(f"- **{issue.severity}** `{rel}:{issue.line}` {issue.kind}: {issue.message}")

    remainder = len(ordered) - len(shown)
    if remainder > 0:
        lines.append("")
        lines.append(f"_...and {remainder} additional findings._")
    return "\n".join(lines)


def _high_churn_components(git_report: GitIntelligenceReport) -> str:
    lines = ["## Recent High-Churn Components", ""]
    top = git_report.churn[:_HIGH_CHURN_LIMIT]
    if not top:
        lines.append("No git history detected.")
        return "\n".join(lines)

    truncation_note = (
        " (history truncated — repo has more commits than analyzed)"
        if git_report.history_truncated
        else ""
    )
    lines.append(f"Analyzed {git_report.commits_analyzed} commits{truncation_note}.")
    lines.append("")
    lines.append("| File | Commits | Bug fixes |")
    lines.append("|---|---|---|")
    for churn in top:
        lines.append(f"| {churn.file} | {churn.commit_count} | {churn.bug_fix_count} |")
    return "\n".join(lines)


def _executive_recommendations(
    semantic: SemanticReport | None,
    debt: TechnicalDebtReport | None,
    performance: PerformanceReport | None,
) -> str:
    # A closing action list, not a new analysis -- every line here points
    # back to a finding already shown elsewhere in this report. No new
    # judgment calls (e.g. never labels a file "an orchestrator" -- Atlas
    # doesn't know what a file does, only what its measured signals are).
    # Requested: "turn the report from a diagnostic document into an
    # action plan" (2026-07-24).
    lines = ["## Executive Recommendations", ""]
    items: list[str] = []
    named_files: set[str] = set()

    if debt is not None and debt.top_debt_modules:
        top = debt.top_debt_modules[0]
        items.append(
            f"Reduce technical debt in `{top.file}` -- the highest-scored module "
            f"({top.debt_score:.2f}), driven primarily by {top.category}."
        )
        named_files.add(top.file)

    if semantic is not None:
        god_modules = [
            c for c in semantic.coupling_issues if c.kind == "god_module" and c.file not in named_files
        ]
        if god_modules:
            top_god = god_modules[0]
            items.append(f"Refactor `{top_god.file}` to reduce coupling -- {top_god.message}.")
            named_files.add(top_god.file)

    if performance is not None:
        large_functions = [f for f in performance.findings if f.kind == "very_large_function"]
        if large_functions:
            items.append(
                f"Break down the {len(large_functions)} function(s) flagged as very large "
                "(see Performance Analysis for the full list)."
            )

    if semantic is not None and semantic.architecture_health.circular_cluster_count > 0:
        n = semantic.architecture_health.circular_cluster_count
        items.append(
            f"Address the {n} circular-dependency cluster{'s' if n != 1 else ''} "
            "(see Architecture Health)."
        )

    if not items:
        lines.append(
            "No significant priorities identified -- no god modules, very-large "
            "functions, circular-dependency clusters, or high-debt modules were flagged."
        )
        return "\n".join(lines)

    lines.append(
        "Derived directly from findings shown elsewhere in this report, ordered by which "
        "signal was strongest -- not a separate judgment call."
    )
    lines.append("")
    for item in items:
        lines.append(f"- {item}")
    return "\n".join(lines)


def _analysis_coverage() -> str:
    # A fixed, version-of-the-tool-level disclosure, not conditional on this
    # specific repo's contents: every report should say the same thing about
    # what Atlas can and can't see, so a reader knows what to trust before
    # they've analyzed a second repo that might hit a gap this one didn't.
    return "\n".join(
        [
            "## Analysis Coverage",
            "",
            "**Supported:**",
            "- Python imports (absolute and relative)",
            "- ES Module imports (JS/TS `import` syntax)",
            "- CommonJS imports (JS/TS `require()` calls)",
            "- Dynamic ES imports (JS/TS `import(...)` expressions)",
            "- Git history (commit churn, ownership, co-change)",
            "- Repository structure and stack detection",
            "- Security scanning for hardcoded secrets, dangerous shell/eval "
            "execution, and unsafe deserialization",
            "",
            "**Limitations:**",
            "- Imports whose target isn't a string literal (e.g. "
            "`require(somePathVariable)`) can't be resolved statically and are skipped.",
            "- Security scanning is pattern-based (not full static analysis) and "
            "can miss real issues or flag safe code that matches a risky pattern.",
            "- Quality and architecture scores are heuristic engineering signals, "
            "not guarantees of correctness or safety.",
            "- Very large repositories are capped (5,000 source files, 2MB per "
            "file, 50,000 total filesystem entries) — see \"Files analyzed\" "
            "above for whether this repository hit a cap.",
        ]
    )


def generate_comparison_report(comparison: ComparisonReport) -> str:
    sections = [
        _comparison_executive_summary(comparison),
        _comparison_metric_changes(comparison),
        _comparison_findings("Regressions", comparison.regressions),
        _comparison_findings("Improvements", comparison.improvements),
        _comparison_set_changes(comparison),
        _comparison_critical_module_diagram(comparison),
        _comparison_limitations(),
    ]
    return "\n\n".join(s for s in sections if s) + "\n"


def _comparison_executive_summary(comparison: ComparisonReport) -> str:
    lines = [
        "## Executive Summary",
        "",
        f"- Repo A: {comparison.repo_url_a} (analyzed {comparison.generated_at_a})",
        f"- Repo B: {comparison.repo_url_b} (analyzed {comparison.generated_at_b})",
        f"- Regressions found: {len(comparison.regressions)}",
        f"- Improvements found: {len(comparison.improvements)}",
    ]
    if not comparison.regressions and not comparison.improvements:
        lines.append(
            "- No metric moved beyond this analysis' significance thresholds — "
            "see Metric Changes below for the raw deltas regardless."
        )
    lines.append(
        "- **Never read this as \"better\" or \"worse\" overall** — only the "
        "specific measurable changes below are asserted; nothing here is a "
        "composite verdict."
    )
    return "\n".join(lines)


def _comparison_metric_changes(comparison: ComparisonReport) -> str:
    lines = [
        "## Metric Changes",
        "",
        "Every tracked metric, not just the ones significant enough to be a "
        "regression or improvement finding — see the `significant` column. "
        "Score deltas of 5 points or less are within this analysis' documented "
        "noise floor.",
        "",
        "| Metric | Before | After | Delta | Significant |",
        "|---|---:|---:|---:|:-:|",
    ]
    for m in comparison.metric_changes:
        lines.append(
            f"| {m.label} | {m.before:g} | {m.after:g} | {m.delta:+.2f} | "
            f"{'yes' if m.significant else 'no'} |"
        )
    return "\n".join(lines)


def _comparison_findings(title: str, findings: list[ComparisonFinding]) -> str:
    lines = [f"## {title}", ""]
    if not findings:
        lines.append(f"No {title.lower()} found.")
        return "\n".join(lines)
    for f in findings:
        lines.append(f"- **{f.severity}** [{f.category}] {f.message}")
    return "\n".join(lines)


def _comparison_set_changes(comparison: ComparisonReport) -> str:
    lines = ["## Set Changes", ""]
    any_changes = False
    for s in comparison.set_changes:
        if not s.added and not s.removed:
            continue
        any_changes = True
        lines.append(f"**{s.label}**")
        if s.added:
            lines.append(f"- Added: {', '.join(s.added)}")
        if s.removed:
            lines.append(f"- Removed: {', '.join(s.removed)}")
        lines.append("")
    if not any_changes:
        lines.append("No changes in any tracked top-N list.")
    return "\n".join(lines).rstrip()


def _comparison_critical_module_diagram(comparison: ComparisonReport) -> str:
    criticality = next(
        (s for s in comparison.set_changes if s.label == "Dependency-criticality top 15"), None
    )
    if criticality is None or (not criticality.added and not criticality.removed):
        return ""

    added = criticality.added[:_COMPARISON_DIAGRAM_CAP]
    removed = criticality.removed[:_COMPARISON_DIAGRAM_CAP]
    lines = [
        "## Critical Module Changes",
        "",
        "Modules that entered or left the dependency-criticality top 15 "
        "between A and B — not a claim about why, just what changed.",
        "",
        "```mermaid",
        "graph LR",
    ]
    for i, m in enumerate(added):
        lines.append(f'    added{i}["+ {PurePath(m).name}"]:::added')
    for i, m in enumerate(removed):
        lines.append(f'    removed{i}["- {PurePath(m).name}"]:::removed')
    lines.append("    classDef added fill:#d4edda,stroke:#28a745")
    lines.append("    classDef removed fill:#f8d7da,stroke:#dc3545")
    lines.append("```")
    return "\n".join(lines)


def _comparison_limitations() -> str:
    return "\n".join(
        [
            "## Limitations",
            "",
            "- Comparison only works between two completed Atlas jobs (by job "
            "ID) — there is currently no support for comparing arbitrary "
            "commits or branches directly; Atlas only clones the HEAD of a "
            "repo URL.",
            "- Thresholds (score noise floor, top-N list size) are a "
            "documented starting point, not empirically tuned against a "
            "historical comparison dataset.",
            "- A dependency-criticality or hotspot set change is reported as "
            "a fact, not classified as a regression or improvement on its "
            "own — becoming more central isn't inherently good or bad "
            "without knowing why.",
            "- Comparing two unrelated repositories (not two runs of the "
            "same one) is technically possible and will produce a mostly "
            "\"everything is different\" report — not detected or warned "
            "about separately.",
        ]
    )
