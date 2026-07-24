from app.comparison_engine import compare_snapshots
from app.models import (
    AnalysisSnapshot,
    SnapshotGitSummary,
    SnapshotSecuritySummary,
    SnapshotSemanticSummary,
)


def _snapshot(**overrides) -> AnalysisSnapshot:
    defaults = dict(
        repo_url="https://github.com/x/y",
        generated_at="2026-01-01T00:00:00",
        overall_score=80,
        maintainability_score=90,
        architecture_score=70,
        module_count=10,
        import_edge_count=20,
        security=SnapshotSecuritySummary(critical_count=0, important_count=0, minor_count=0),
        git=SnapshotGitSummary(commits_analyzed=100, top_churn_files=["a.py"]),
        semantic=SnapshotSemanticSummary(
            circular_cluster_count=0,
            articulation_point_count=1,
            dependency_concentration_top5_ratio=0.5,
            critical_modules=["a.py", "b.py"],
            hotspot_modules=["c.py"],
            coupling_issue_count=0,
            smell_count=0,
        ),
    )
    defaults.update(overrides)
    return AnalysisSnapshot(**defaults)


def test_score_change_within_noise_floor_is_not_significant_or_flagged():
    a = _snapshot(overall_score=80)
    b = _snapshot(overall_score=83)

    report = compare_snapshots(a, b)

    overall = next(m for m in report.metric_changes if m.label == "Overall quality score")
    assert overall.delta == 3
    assert overall.significant is False
    assert report.regressions == []
    assert report.improvements == []


def test_score_drop_beyond_noise_floor_is_a_regression():
    a = _snapshot(overall_score=80)
    b = _snapshot(overall_score=70)

    report = compare_snapshots(a, b)

    assert any(f.kind == "regression" and "Overall quality score" in f.message for f in report.regressions)


def test_score_rise_beyond_noise_floor_is_an_improvement():
    a = _snapshot(overall_score=70)
    b = _snapshot(overall_score=82)

    report = compare_snapshots(a, b)

    assert any(f.kind == "improvement" for f in report.improvements)


def test_new_circular_cluster_is_always_a_regression_no_threshold():
    a = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=0, articulation_point_count=0, dependency_concentration_top5_ratio=0.0,
        critical_modules=[], hotspot_modules=[], coupling_issue_count=0, smell_count=0,
    ))
    b = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=1, articulation_point_count=0, dependency_concentration_top5_ratio=0.0,
        critical_modules=[], hotspot_modules=[], coupling_issue_count=0, smell_count=0,
    ))

    report = compare_snapshots(a, b)

    assert any(f.category == "architecture" and f.kind == "regression" for f in report.regressions)


def test_removed_circular_cluster_is_an_improvement():
    a = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=2, articulation_point_count=0, dependency_concentration_top5_ratio=0.0,
        critical_modules=[], hotspot_modules=[], coupling_issue_count=0, smell_count=0,
    ))
    b = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=0, articulation_point_count=0, dependency_concentration_top5_ratio=0.0,
        critical_modules=[], hotspot_modules=[], coupling_issue_count=0, smell_count=0,
    ))

    report = compare_snapshots(a, b)

    assert any(f.category == "architecture" and f.kind == "improvement" for f in report.improvements)


def test_new_critical_security_finding_is_a_regression_minor_change_is_not():
    a = _snapshot(security=SnapshotSecuritySummary(critical_count=0, important_count=0, minor_count=5))
    b = _snapshot(security=SnapshotSecuritySummary(critical_count=1, important_count=0, minor_count=8))

    report = compare_snapshots(a, b)

    assert any(f.category == "security" and "critical" in f.message for f in report.regressions)
    # The minor-count jump (5 -> 8) must not itself produce a regression finding.
    assert not any("minor" in f.message and f.kind == "regression" for f in report.regressions)


def test_resolved_security_finding_is_an_improvement():
    a = _snapshot(security=SnapshotSecuritySummary(critical_count=1, important_count=0, minor_count=0))
    b = _snapshot(security=SnapshotSecuritySummary(critical_count=0, important_count=0, minor_count=0))

    report = compare_snapshots(a, b)

    assert any(f.category == "security" and f.kind == "improvement" for f in report.improvements)


def test_new_hotspot_is_a_minor_regression_resolved_hotspot_is_an_improvement():
    a = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=0, articulation_point_count=0, dependency_concentration_top5_ratio=0.0,
        critical_modules=[], hotspot_modules=["old.py"], coupling_issue_count=0, smell_count=0,
    ))
    b = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=0, articulation_point_count=0, dependency_concentration_top5_ratio=0.0,
        critical_modules=[], hotspot_modules=["new.py"], coupling_issue_count=0, smell_count=0,
    ))

    report = compare_snapshots(a, b)

    assert any("new.py" in f.message and f.kind == "regression" for f in report.regressions)
    assert any("old.py" in f.message and f.kind == "improvement" for f in report.improvements)


def test_set_changes_report_added_and_removed_critical_modules():
    a = _snapshot()  # critical_modules=["a.py", "b.py"]
    b = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=0, articulation_point_count=1, dependency_concentration_top5_ratio=0.5,
        critical_modules=["a.py", "c.py"], hotspot_modules=["c.py"], coupling_issue_count=0, smell_count=0,
    ))

    report = compare_snapshots(a, b)

    criticality_change = next(s for s in report.set_changes if s.label == "Dependency-criticality top 15")
    assert criticality_change.added == ["c.py"]
    assert criticality_change.removed == ["b.py"]


def test_criticality_change_alone_is_not_classified_regression_or_improvement():
    a = _snapshot()
    b = _snapshot(semantic=SnapshotSemanticSummary(
        circular_cluster_count=0, articulation_point_count=1, dependency_concentration_top5_ratio=0.5,
        critical_modules=["a.py", "c.py"], hotspot_modules=["c.py"], coupling_issue_count=0, smell_count=0,
    ))

    report = compare_snapshots(a, b)

    assert not any("Dependency-criticality" in f.message for f in report.regressions + report.improvements)


def test_identical_snapshots_produce_no_findings():
    a = _snapshot()
    b = _snapshot()

    report = compare_snapshots(a, b)

    assert report.regressions == []
    assert report.improvements == []
    assert all(not m.significant for m in report.metric_changes)
