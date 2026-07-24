from app.models import (
    ArchitectureHealth,
    CriticalModule,
    EngineeringHotspot,
    FileChurn,
    GitIntelligenceReport,
    QualityReport,
    SecurityIssue,
    SecurityReport,
    SemanticReport,
    SubsystemOverview,
)
from app.snapshot import build_snapshot


def _semantic(**overrides) -> SemanticReport:
    defaults = dict(
        architecture_health=ArchitectureHealth(
            module_count=10,
            import_edge_count=20,
            circular_cluster_count=1,
            articulation_point_count=2,
            bridge_count=3,
            betweenness_computed=True,
            dependency_concentration_top5_ratio=0.5,
        ),
        critical_modules=[
            CriticalModule(file="a.py", fan_in=5, fan_out=0, betweenness=0.1, criticality_score=5.1)
        ],
        subsystem_overview=SubsystemOverview(confident=False, coverage_ratio=0.0, layer_counts={}, layer_edges=[]),
        hotspots=[
            EngineeringHotspot(file="b.py", churn=3, centrality=1.0, complexity_issues=2, hotspot_score=0.5)
        ],
        coupling_issues=[],
        architectural_smells=[],
    )
    defaults.update(overrides)
    return SemanticReport(**defaults)


def test_build_snapshot_summarizes_all_five_areas():
    quality = QualityReport(overall_score=80, maintainability_score=90, architecture_score=70, issues=[])
    security = SecurityReport(
        issues=[
            SecurityIssue(file="a.py", line=1, kind="dangerous_execution", message="x", severity="critical"),
            SecurityIssue(file="b.py", line=2, kind="dangerous_execution", message="x", severity="important"),
            SecurityIssue(file="c.py", line=3, kind="dangerous_execution", message="x", severity="minor"),
        ]
    )
    git_report = GitIntelligenceReport(
        commits_analyzed=100,
        history_truncated=False,
        churn=[FileChurn(file="a.py", commit_count=10, bug_fix_count=2)],
        ownership=[],
        co_changes=[],
    )
    semantic = _semantic()

    snap = build_snapshot("https://github.com/x/y", quality, security, git_report, semantic)

    assert snap.repo_url == "https://github.com/x/y"
    assert snap.overall_score == 80
    assert snap.module_count == 10
    assert snap.import_edge_count == 20
    assert snap.security.critical_count == 1
    assert snap.security.important_count == 1
    assert snap.security.minor_count == 1
    assert snap.git.commits_analyzed == 100
    assert snap.git.top_churn_files == ["a.py"]
    assert snap.semantic.circular_cluster_count == 1
    assert snap.semantic.critical_modules == ["a.py"]
    assert snap.semantic.hotspot_modules == ["b.py"]


def test_snapshot_is_json_roundtrippable():
    quality = QualityReport(overall_score=80, maintainability_score=90, architecture_score=70, issues=[])
    security = SecurityReport(issues=[])
    git_report = GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )
    semantic = _semantic()

    snap = build_snapshot("https://github.com/x/y", quality, security, git_report, semantic)
    from app.models import AnalysisSnapshot

    restored = AnalysisSnapshot.model_validate_json(snap.model_dump_json())
    assert restored == snap
