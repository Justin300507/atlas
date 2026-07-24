from __future__ import annotations

from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols
from .models import (
    ComparisonFinding,
    ComparisonReport,
    FileCoverage,
    GitIntelligenceReport,
    PerformanceReport,
    QualityReport,
    SecurityReport,
    SemanticReport,
    StackReport,
    TechnicalDebtReport,
)
from .semantic_analysis import _LAYER_ORDER

_DIAGRAM_NODE_CAP = 40
_HIGH_CHURN_LIMIT = 10
_RISK_AREAS_LIMIT = 20
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
        _executive_summary(stack, files, quality, git_report, coverage),
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
            _dependency_diagram(graph),
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
        ]
    )
    return "\n\n".join(sections) + "\n"


def _relative(repo_root: Path, path: str) -> str:
    try:
        return PurePath(Path(path).relative_to(repo_root)).as_posix()
    except ValueError:
        return PurePath(path).as_posix()


def _executive_summary(
    stack: StackReport,
    files: list[FileSymbols],
    quality: QualityReport,
    git_report: GitIntelligenceReport,
    coverage: FileCoverage | None = None,
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
    truncation_note = " (history truncated)" if git_report.history_truncated else ""
    lines.append(f"- Commits analyzed: {git_report.commits_analyzed}{truncation_note}")
    return "\n".join(lines)


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
    return "\n".join(lines)


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
    for f in ordered:
        location = f"{f.file}:{f.line}" if f.line else f.file
        lines.append(f"- **{f.confidence} confidence** `{location}` {f.kind}: {f.message}")

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

    lines.append("| Directory | Files |")
    lines.append("|---|---|")
    for directory, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {directory} | {count} |")
    return "\n".join(lines)


def _api_reference(repo_root: Path, files: list[FileSymbols]) -> str:
    lines = ["## API Reference", ""]
    rows = [
        (method, path, _relative(repo_root, f.path))
        for f in files
        for method, path in f.routes
    ]
    if not rows:
        lines.append("No routes detected.")
        return "\n".join(lines)

    lines.append("| Method | Path | File |")
    lines.append("|---|---|---|")
    for method, path, file in sorted(rows, key=lambda r: (r[2], r[1])):
        lines.append(f"| {method} | {path} | {file} |")
    return "\n".join(lines)


def _dependency_diagram(graph: nx.DiGraph) -> str:
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

    lines.append("```mermaid")
    lines.append("graph TD")
    for u, v, d in graph.edges(data=True):
        if d.get("type") == "import" and u in selected_set and v in selected_set:
            lines.append(
                f'    {node_ids[u]}["{PurePath(u).name}"] --> {node_ids[v]}["{PurePath(v).name}"]'
            )
    lines.append("```")

    if len(module_nodes) > _DIAGRAM_NODE_CAP:
        lines.append("")
        lines.append(
            f"_({len(selected)} of {len(module_nodes)} modules shown, capped for readability)_"
        )
    return "\n".join(lines)


def _risk_areas(repo_root: Path, quality: QualityReport) -> str:
    lines = ["## Risk Areas", ""]
    if not quality.issues:
        lines.append("No issues detected.")
        return "\n".join(lines)

    ordered = sorted(quality.issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))
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
