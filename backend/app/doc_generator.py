from __future__ import annotations

from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols
from .models import (
    FileCoverage,
    GitIntelligenceReport,
    QualityReport,
    SecurityReport,
    StackReport,
)

_DIAGRAM_NODE_CAP = 40
_HIGH_CHURN_LIMIT = 10
_RISK_AREAS_LIMIT = 20
_SECURITY_FINDINGS_LIMIT = 20
_SEVERITY_ORDER = {"critical": 0, "important": 1, "minor": 2}


def generate_documentation(
    repo_root: Path,
    stack: StackReport,
    files: list[FileSymbols],
    graph: nx.DiGraph,
    quality: QualityReport,
    security: SecurityReport,
    git_report: GitIntelligenceReport,
    coverage: FileCoverage | None = None,
) -> str:
    sections = [
        _executive_summary(stack, files, quality, git_report, coverage),
        _architecture_overview(graph),
        _directory_guide(repo_root, files),
        _api_reference(repo_root, files),
        _dependency_diagram(graph),
        _risk_areas(repo_root, quality),
        _security_findings(repo_root, security),
        _high_churn_components(git_report),
        _analysis_coverage(),
    ]
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
