from __future__ import annotations

from datetime import datetime, timezone

from .models import (
    AnalysisSnapshot,
    GitIntelligenceReport,
    QualityReport,
    SecurityReport,
    SemanticReport,
    SnapshotGitSummary,
    SnapshotSecuritySummary,
    SnapshotSemanticSummary,
)

# See docs/superpowers/specs/2026-07-24-repository-comparison-design.md.
# Deliberately excludes full file lists, full markdown, and the full
# dependency graph -- only counts, scores, and the top-N ranked lists
# Atlas already caps elsewhere (critical modules, hotspots), so a
# snapshot stays a few KB, not a copy of the whole analysis.
_TOP_N_MODULES = 15


def build_snapshot(
    repo_url: str,
    quality: QualityReport,
    security: SecurityReport,
    git_report: GitIntelligenceReport,
    semantic: SemanticReport,
) -> AnalysisSnapshot:
    security_counts = {"critical": 0, "important": 0, "minor": 0}
    for issue in security.issues:
        if issue.severity in security_counts:
            security_counts[issue.severity] += 1

    return AnalysisSnapshot(
        repo_url=repo_url,
        generated_at=datetime.now(timezone.utc).isoformat(),
        overall_score=quality.overall_score,
        maintainability_score=quality.maintainability_score,
        architecture_score=quality.architecture_score,
        module_count=semantic.architecture_health.module_count,
        import_edge_count=semantic.architecture_health.import_edge_count,
        security=SnapshotSecuritySummary(
            critical_count=security_counts["critical"],
            important_count=security_counts["important"],
            minor_count=security_counts["minor"],
        ),
        git=SnapshotGitSummary(
            commits_analyzed=git_report.commits_analyzed,
            top_churn_files=[c.file for c in git_report.churn[:_TOP_N_MODULES]],
        ),
        semantic=SnapshotSemanticSummary(
            circular_cluster_count=semantic.architecture_health.circular_cluster_count,
            articulation_point_count=semantic.architecture_health.articulation_point_count,
            dependency_concentration_top5_ratio=semantic.architecture_health.dependency_concentration_top5_ratio,
            critical_modules=[m.file for m in semantic.critical_modules[:_TOP_N_MODULES]],
            hotspot_modules=[h.file for h in semantic.hotspots[:_TOP_N_MODULES]],
            coupling_issue_count=len(semantic.coupling_issues),
            smell_count=len(semantic.architectural_smells),
        ),
    )
