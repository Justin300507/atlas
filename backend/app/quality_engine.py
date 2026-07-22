from __future__ import annotations

import re

import networkx as nx

from .code_parser import FileSymbols
from .models import QualityIssue, QualityReport

_LONG_FUNCTION_LINES = 50
_HIGH_COMPLEXITY_BRANCHES = 10
_CIRCULAR_IMPORT_PENALTY = 15
_LONG_FUNCTION_PENALTY = 5
_HIGH_COMPLEXITY_PENALTY = 5
_NAMING_VIOLATION_PENALTY = 2

_PY_FUNCTION_NAME = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
_JS_FUNCTION_NAME = re.compile(r"^_{0,2}[a-z][a-zA-Z0-9]*$")
_CLASS_NAME = re.compile(r"^_?[A-Z][a-zA-Z0-9]*$")


def analyze_quality(files: list[FileSymbols], graph: nx.DiGraph) -> QualityReport:
    issues: list[QualityIssue] = []

    architecture_score = 100
    for cycle in _find_import_cycles(graph):
        architecture_score -= _CIRCULAR_IMPORT_PENALTY
        issues.append(
            QualityIssue(
                file=cycle[0],
                line=0,
                kind="circular_import",
                message=f"Circular import: {' -> '.join(cycle + [cycle[0]])}",
                severity="important",
            )
        )

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
    architecture_score = max(0, architecture_score)
    overall_score = round((maintainability_score + architecture_score) / 2)

    return QualityReport(
        overall_score=overall_score,
        maintainability_score=maintainability_score,
        architecture_score=architecture_score,
        issues=issues,
    )


def _find_import_cycles(graph: nx.DiGraph) -> list[list[str]]:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    module_graph = graph.subgraph(module_nodes)
    return [cycle for cycle in nx.simple_cycles(module_graph) if len(cycle) > 1]
