from __future__ import annotations

from .models import (
    AnalysisSnapshot,
    ComparisonFinding,
    ComparisonReport,
    MetricChange,
    SetChange,
)

# See docs/superpowers/specs/2026-07-24-repository-comparison-design.md
# for the rationale behind every threshold below -- a documented
# starting point, not empirically tuned (no historical comparison
# dataset exists yet for this feature).
_SCORE_NOISE_FLOOR = 5
_TOP_N_MODULES = 15


def _metric_change(label: str, before: float, after: float, noise_floor: float = 0) -> MetricChange:
    delta = after - before
    return MetricChange(
        label=label,
        before=before,
        after=after,
        delta=delta,
        significant=abs(delta) > noise_floor,
    )


def _set_change(label: str, before: list[str], after: list[str]) -> SetChange:
    before_set, after_set = set(before), set(after)
    return SetChange(
        label=label,
        added=sorted(after_set - before_set),
        removed=sorted(before_set - after_set),
    )


def compare_snapshots(a: AnalysisSnapshot, b: AnalysisSnapshot) -> ComparisonReport:
    metric_changes = [
        _metric_change("Overall quality score", a.overall_score, b.overall_score, _SCORE_NOISE_FLOOR),
        _metric_change(
            "Maintainability score", a.maintainability_score, b.maintainability_score, _SCORE_NOISE_FLOOR
        ),
        _metric_change(
            "Architecture score", a.architecture_score, b.architecture_score, _SCORE_NOISE_FLOOR
        ),
        _metric_change("Module count", a.module_count, b.module_count),
        _metric_change("Import edge count", a.import_edge_count, b.import_edge_count),
        _metric_change(
            "Circular-dependency clusters",
            a.semantic.circular_cluster_count,
            b.semantic.circular_cluster_count,
        ),
        _metric_change(
            "Articulation points", a.semantic.articulation_point_count, b.semantic.articulation_point_count
        ),
        _metric_change(
            "Dependency concentration (top 5)",
            a.semantic.dependency_concentration_top5_ratio,
            b.semantic.dependency_concentration_top5_ratio,
        ),
        _metric_change(
            "Coupling issues", a.semantic.coupling_issue_count, b.semantic.coupling_issue_count
        ),
        _metric_change("Architectural smells", a.semantic.smell_count, b.semantic.smell_count),
        _metric_change(
            "Critical security findings", a.security.critical_count, b.security.critical_count
        ),
        _metric_change(
            "Important security findings", a.security.important_count, b.security.important_count
        ),
    ]

    set_changes = [
        _set_change("Dependency-criticality top 15", a.semantic.critical_modules, b.semantic.critical_modules),
        _set_change("Engineering hotspots top 15", a.semantic.hotspot_modules, b.semantic.hotspot_modules),
        _set_change("Git churn top 15", a.git.top_churn_files, b.git.top_churn_files),
    ]

    # debt/performance are optional (schema_version 2, v1.3) -- a snapshot
    # from before this feature has them as None, so only compare when both
    # sides actually have the data rather than treating a missing field as
    # a metric change from/to zero.
    if a.debt is not None and b.debt is not None:
        metric_changes.append(
            _metric_change("Average technical debt score", a.debt.average_debt_score, b.debt.average_debt_score)
        )
        set_changes.append(_set_change("Top debt modules", a.debt.top_debt_modules, b.debt.top_debt_modules))

    if a.performance is not None and b.performance is not None:
        metric_changes.append(
            _metric_change("Performance finding count", a.performance.finding_count, b.performance.finding_count)
        )
        set_changes.append(
            _set_change(
                "Performance bottleneck modules",
                a.performance.bottleneck_modules,
                b.performance.bottleneck_modules,
            )
        )

    regressions: list[ComparisonFinding] = []
    improvements: list[ComparisonFinding] = []

    for label, before, after, kind_if_up, kind_if_down in [
        ("Overall quality score", a.overall_score, b.overall_score, "improvement", "regression"),
        ("Maintainability score", a.maintainability_score, b.maintainability_score, "improvement", "regression"),
        ("Architecture score", a.architecture_score, b.architecture_score, "improvement", "regression"),
    ]:
        delta = after - before
        if abs(delta) <= _SCORE_NOISE_FLOOR:
            continue
        kind = kind_if_down if delta < 0 else kind_if_up
        target = regressions if kind == "regression" else improvements
        target.append(
            ComparisonFinding(
                category="quality",
                kind=kind,
                message=f"{label} moved from {before} to {after} ({delta:+.0f})",
                severity="important",
            )
        )

    cluster_delta = b.semantic.circular_cluster_count - a.semantic.circular_cluster_count
    if cluster_delta > 0:
        regressions.append(
            ComparisonFinding(
                category="architecture",
                kind="regression",
                message=f"{cluster_delta} new circular-dependency cluster(s) "
                f"({a.semantic.circular_cluster_count} -> {b.semantic.circular_cluster_count})",
                severity="important",
            )
        )
    elif cluster_delta < 0:
        improvements.append(
            ComparisonFinding(
                category="architecture",
                kind="improvement",
                message=f"{-cluster_delta} circular-dependency cluster(s) removed "
                f"({a.semantic.circular_cluster_count} -> {b.semantic.circular_cluster_count})",
                severity="important",
            )
        )

    for label, before, after in [
        ("critical", a.security.critical_count, b.security.critical_count),
        ("important", a.security.important_count, b.security.important_count),
    ]:
        delta = after - before
        if delta > 0:
            regressions.append(
                ComparisonFinding(
                    category="security",
                    kind="regression",
                    message=f"{delta} new {label} security finding(s) ({before} -> {after})",
                    severity="critical" if label == "critical" else "important",
                )
            )
        elif delta < 0:
            improvements.append(
                ComparisonFinding(
                    category="security",
                    kind="improvement",
                    message=f"{-delta} {label} security finding(s) resolved ({before} -> {after})",
                    severity="minor",
                )
            )

    hotspots_before = set(a.semantic.hotspot_modules)
    hotspots_after = set(b.semantic.hotspot_modules)
    new_hotspots = hotspots_after - hotspots_before
    resolved_hotspots = hotspots_before - hotspots_after
    for module in sorted(new_hotspots):
        regressions.append(
            ComparisonFinding(
                category="semantic",
                kind="regression",
                message=f"{module} newly appeared in the engineering hotspots top {_TOP_N_MODULES}",
                severity="minor",
            )
        )
    for module in sorted(resolved_hotspots):
        improvements.append(
            ComparisonFinding(
                category="semantic",
                kind="improvement",
                message=f"{module} left the engineering hotspots top {_TOP_N_MODULES}",
                severity="minor",
            )
        )

    return ComparisonReport(
        repo_url_a=a.repo_url,
        repo_url_b=b.repo_url,
        generated_at_a=a.generated_at,
        generated_at_b=b.generated_at,
        metric_changes=metric_changes,
        set_changes=set_changes,
        regressions=regressions,
        improvements=improvements,
    )
