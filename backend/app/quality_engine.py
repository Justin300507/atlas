from __future__ import annotations

import re

import networkx as nx

from .code_parser import FileSymbols
from .models import QualityIssue, QualityReport

_LONG_FUNCTION_LINES = 50
_HIGH_COMPLEXITY_BRANCHES = 10
_LONG_FUNCTION_PENALTY = 5
_HIGH_COMPLEXITY_PENALTY = 5
_NAMING_VIOLATION_PENALTY = 2

# Circular-import scoring is based on strongly connected components (SCCs) of
# the module graph, not on nx.simple_cycles: a single real "these N modules
# are mutually entangled" fact can contain a combinatorial number of distinct
# simple cycles (verified on pallets/flask and tiangolo/typer during real-repo
# validation — one ~50-module cluster produced tens of thousands of simple
# cycles), which turns one structural finding into an unusable issue count and
# floors the score at 0 for almost any real, moderately interconnected repo.
# An SCC of size > 1 is one distinct entangled cluster and gets exactly one
# QualityIssue, regardless of how many simple cycles run through it.
_PER_CLUSTER_PENALTY = 10
_LARGEST_CLUSTER_PENALTY_PER_MODULE = 2
_MAX_LARGEST_CLUSTER_PENALTY = 40
_PARTICIPATION_PENALTY_SCALE = 30
_CLUSTER_FILES_SHOWN = 20

_PY_FUNCTION_NAME = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
_JS_FUNCTION_NAME = re.compile(r"^_{0,2}[a-z][a-zA-Z0-9]*$")
_CLASS_NAME = re.compile(r"^_?[A-Z][a-zA-Z0-9]*$")


def analyze_quality(files: list[FileSymbols], graph: nx.DiGraph) -> QualityReport:
    issues: list[QualityIssue] = []

    architecture_score, cluster_issues = _score_circular_dependencies(graph)
    issues.extend(cluster_issues)

    maintainability_score = 100
    for f in files:
        function_pattern = _PY_FUNCTION_NAME if f.language == "python" else _JS_FUNCTION_NAME

        for fn in f.functions:
            length = fn.end_line - fn.start_line + 1
            if length > _LONG_FUNCTION_LINES:
                maintainability_score -= _LONG_FUNCTION_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=fn.start_line,
                        kind="long_function",
                        message=f"Function '{fn.name}' is {length} lines (threshold {_LONG_FUNCTION_LINES})",
                        severity="minor",
                    )
                )
            if fn.branch_count > _HIGH_COMPLEXITY_BRANCHES:
                maintainability_score -= _HIGH_COMPLEXITY_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=fn.start_line,
                        kind="high_complexity",
                        message=f"Function '{fn.name}' has branch count {fn.branch_count} (threshold {_HIGH_COMPLEXITY_BRANCHES})",
                        severity="important",
                    )
                )
            if not function_pattern.match(fn.name):
                maintainability_score -= _NAMING_VIOLATION_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=fn.start_line,
                        kind="naming_convention",
                        message=f"Function name '{fn.name}' doesn't follow the expected convention",
                        severity="minor",
                    )
                )

        for class_name in f.class_names:
            if not _CLASS_NAME.match(class_name):
                maintainability_score -= _NAMING_VIOLATION_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=0,
                        kind="naming_convention",
                        message=f"Class name '{class_name}' doesn't follow PascalCase convention",
                        severity="minor",
                    )
                )

    maintainability_score = max(0, maintainability_score)
    overall_score = round((maintainability_score + architecture_score) / 2)

    return QualityReport(
        overall_score=overall_score,
        maintainability_score=maintainability_score,
        architecture_score=architecture_score,
        issues=issues,
    )


def _find_circular_dependency_clusters(graph: nx.DiGraph) -> list[list[str]]:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    module_graph = graph.subgraph(module_nodes)
    return [
        sorted(scc) for scc in nx.strongly_connected_components(module_graph) if len(scc) > 1
    ]


def _cluster_severity(size: int) -> str:
    if size >= 10:
        return "critical"
    if size >= 5:
        return "important"
    return "minor"


def _score_circular_dependencies(graph: nx.DiGraph) -> tuple[int, list[QualityIssue]]:
    clusters = _find_circular_dependency_clusters(graph)
    if not clusters:
        return 100, []

    total_modules = sum(1 for _, d in graph.nodes(data=True) if d.get("type") == "module")
    modules_in_clusters = {module for cluster in clusters for module in cluster}
    participation_ratio = len(modules_in_clusters) / total_modules if total_modules else 0.0
    largest_cluster_size = max(len(cluster) for cluster in clusters)

    score = 100
    score -= len(clusters) * _PER_CLUSTER_PENALTY
    score -= min(_MAX_LARGEST_CLUSTER_PENALTY, largest_cluster_size * _LARGEST_CLUSTER_PENALTY_PER_MODULE)
    score -= round(participation_ratio * _PARTICIPATION_PENALTY_SCALE)
    score = max(0, score)

    issues = [_cluster_issue(cluster) for cluster in clusters]
    return score, issues


def _cluster_issue(cluster: list[str]) -> QualityIssue:
    shown = cluster[:_CLUSTER_FILES_SHOWN]
    remainder = len(cluster) - len(shown)
    listing = ", ".join(shown)
    if remainder > 0:
        listing += f", and {remainder} more"
    return QualityIssue(
        file=cluster[0],
        line=0,
        kind="circular_import",
        message=f"Circular dependency cluster of {len(cluster)} modules: {listing}",
        severity=_cluster_severity(len(cluster)),
    )
