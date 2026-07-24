from __future__ import annotations

from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols
from .git_log_parser import Commit
from .models import DebtModule, QualityReport, SemanticReport, TechnicalDebtReport
from .quality_engine import _find_circular_dependency_clusters

# See docs/superpowers/specs/2026-07-24-engineering-advisor-suite-design.md
# for the rationale behind every weight below. Components are capped so
# they sum to exactly 100 -- a module can't exceed a "full debt" score
# by accumulating more than four independently-real signals.
_COMPLEXITY_CHURN_WEIGHT = 40
_CENTRALITY_SIZE_WEIGHT = 25
_COUPLING_SMELL_POINTS = 20
_CIRCULAR_CLUSTER_POINTS = 15
_TOP_N = 15

# Only these architectural_smell kinds represent an actual maintenance
# risk -- found via dogfooding on Atlas's own repo: lumping in every
# smell initially flagged vite.config.ts (an isolated_component --
# disconnected, so trivially safe to change) and would have flagged a
# facade_pattern (often a deliberate, healthy re-export convention) the
# same as a real god_module. Neither is "debt" in the sense this score
# means. coupling_issues (god_module/excessive_fan_out) are all
# debt-relevant by construction, so no filtering needed there.
_DEBT_RELEVANT_SMELL_KINDS = {"utility_dumping", "layering_violation"}


def _relative(repo_root: Path | None, path: str) -> str:
    if repo_root is not None:
        try:
            return PurePath(Path(path).relative_to(repo_root)).as_posix()
        except ValueError:
            pass
    return PurePath(path).as_posix()


def analyze_technical_debt(
    files: list[FileSymbols],
    graph: nx.DiGraph,
    quality: QualityReport,
    semantic: SemanticReport,
    commits: list[Commit],
    repo_root: Path | None = None,
) -> TechnicalDebtReport:
    churn_by_relpath: dict[str, int] = {}
    for commit in commits:
        for fc in commit.files:
            churn_by_relpath[fc.path] = churn_by_relpath.get(fc.path, 0) + 1

    complexity_by_relpath: dict[str, int] = {}
    for issue in quality.issues:
        if issue.kind in ("long_function", "high_complexity"):
            rel = _relative(repo_root, issue.file)
            complexity_by_relpath[rel] = complexity_by_relpath.get(rel, 0) + 1

    centrality_by_relpath = {m.file: m.criticality_score for m in semantic.critical_modules}

    coupling_smell_relpaths = {i.file for i in semantic.coupling_issues} | {
        s.file for s in semantic.architectural_smells if s.kind in _DEBT_RELEVANT_SMELL_KINDS
    }

    circular_relpaths = {
        _relative(repo_root, module)
        for cluster in _find_circular_dependency_clusters(graph)
        for module in cluster
    }

    function_counts = {_relative(repo_root, f.path): len(f.functions) for f in files}

    raw = []
    for f in files:
        rel = _relative(repo_root, f.path)
        raw.append(
            (
                rel,
                churn_by_relpath.get(rel, 0),
                complexity_by_relpath.get(rel, 0),
                centrality_by_relpath.get(rel, 0.0),
                function_counts.get(rel, 0),
            )
        )

    max_churn = max((r[1] for r in raw), default=0) or 1
    max_complexity = max((r[2] for r in raw), default=0) or 1
    max_centrality = max((r[3] for r in raw), default=0.0) or 1.0
    max_functions = max((r[4] for r in raw), default=0) or 1

    has_git_history = commits and any(churn_by_relpath.values())
    betweenness_computed = semantic.architecture_health.betweenness_computed

    modules: list[DebtModule] = []
    for rel, churn, complexity, centrality, functions in raw:
        components = {
            "complexity_churn": (churn / max_churn) * (complexity / max_complexity) * _COMPLEXITY_CHURN_WEIGHT,
            "centrality_size": (centrality / max_centrality) * (functions / max_functions) * _CENTRALITY_SIZE_WEIGHT,
            "coupling_smell": _COUPLING_SMELL_POINTS if rel in coupling_smell_relpaths else 0,
            "circular_cluster": _CIRCULAR_CLUSTER_POINTS if rel in circular_relpaths else 0,
        }
        score = sum(components.values())
        if score <= 0:
            continue

        category = max(components, key=components.get)
        evidence = []
        if churn:
            evidence.append(f"{churn} commit(s) touching this file")
        if complexity:
            evidence.append(f"{complexity} complexity issue(s) (long/high-complexity functions)")
        if centrality:
            evidence.append(f"dependency-criticality score {centrality:.2f}")
        if rel in coupling_smell_relpaths:
            evidence.append("flagged as a coupling issue or architectural smell")
        if rel in circular_relpaths:
            evidence.append("member of a circular-dependency cluster")

        confidence = "high" if (churn_by_relpath.get(rel, 0) > 0 and betweenness_computed) else "low"
        if not has_git_history:
            confidence = "low"

        modules.append(
            DebtModule(
                file=rel,
                debt_score=round(score, 2),
                category=category,
                confidence=confidence,
                evidence=evidence,
            )
        )

    modules.sort(key=lambda m: -m.debt_score)
    top = modules[:_TOP_N]
    average = round(sum(m.debt_score for m in modules) / len(modules), 2) if modules else 0.0

    return TechnicalDebtReport(
        average_debt_score=average,
        top_debt_modules=top,
        recommended_refactoring_order=[m.file for m in top],
    )
