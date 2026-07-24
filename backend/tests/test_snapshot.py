from app.models import (
    ArchitectureHealth,
    CriticalModule,
    DebtModule,
    EngineeringHotspot,
    FileChurn,
    GitIntelligenceReport,
    PerformanceFinding,
    PerformanceReport,
    QualityReport,
    SecurityIssue,
    SecurityReport,
    SemanticReport,
    SubsystemOverview,
    TechnicalDebtReport,
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


def test_build_snapshot_leaves_debt_and_performance_none_when_omitted():
    quality = QualityReport(overall_score=80, maintainability_score=90, architecture_score=70, issues=[])
    security = SecurityReport(issues=[])
    git_report = GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )

    snap = build_snapshot("https://github.com/x/y", quality, security, git_report, _semantic())

    assert snap.debt is None
    assert snap.performance is None


def test_build_snapshot_populates_debt_and_performance_when_provided():
    quality = QualityReport(overall_score=80, maintainability_score=90, architecture_score=70, issues=[])
    security = SecurityReport(issues=[])
    git_report = GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )
    debt = TechnicalDebtReport(
        average_debt_score=12.5,
        top_debt_modules=[
            DebtModule(file="hub.py", debt_score=12.5, category="coupling_smell", confidence="high", evidence=["x"])
        ],
        recommended_refactoring_order=["hub.py"],
    )
    performance = PerformanceReport(
        findings=[
            PerformanceFinding(file="hub.py", line=1, kind="very_large_function", message="x", confidence="high")
        ],
        bottleneck_modules=["hub.py"],
    )

    snap = build_snapshot(
        "https://github.com/x/y", quality, security, git_report, _semantic(), debt, performance
    )

    assert snap.debt.average_debt_score == 12.5
    assert snap.debt.top_debt_modules == ["hub.py"]
    assert snap.performance.finding_count == 1
    assert snap.performance.bottleneck_modules == ["hub.py"]
