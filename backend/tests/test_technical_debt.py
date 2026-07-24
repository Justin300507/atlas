import networkx as nx

from app.code_parser import FileSymbols, FunctionInfo
from app.git_log_parser import Commit, FileChange
from app.models import (
    ArchitectureHealth,
    QualityIssue,
    QualityReport,
    SemanticReport,
    SubsystemOverview,
)
from app.technical_debt import analyze_technical_debt


def _file(path: str, functions: int = 0) -> FileSymbols:
    return FileSymbols(
        path=path,
        language="python",
        functions=[
            FunctionInfo(name=f"fn{i}", start_line=i, end_line=i + 1, branch_count=1)
            for i in range(functions)
        ],
    )


def _semantic(**overrides) -> SemanticReport:
    defaults = dict(
        architecture_health=ArchitectureHealth(
            module_count=3,
            import_edge_count=2,
            circular_cluster_count=0,
            articulation_point_count=0,
            bridge_count=0,
            betweenness_computed=True,
            dependency_concentration_top5_ratio=0.0,
        ),
        critical_modules=[],
        subsystem_overview=SubsystemOverview(confident=False, coverage_ratio=0.0, layer_counts={}, layer_edges=[]),
        hotspots=[],
        coupling_issues=[],
        architectural_smells=[],
    )
    defaults.update(overrides)
    return SemanticReport(**defaults)


def _quality(issues=None) -> QualityReport:
    return QualityReport(overall_score=90, maintainability_score=90, architecture_score=100, issues=issues or [])


def _commit(paths: list[str]) -> Commit:
    return Commit(hash="h", author_email="a@x.com", message="x", files=[FileChange(path=p, additions=1, deletions=0) for p in paths])


def test_module_with_no_signal_gets_no_debt_score():
    graph = nx.DiGraph()
    graph.add_node("clean.py", type="module")
    files = [_file("clean.py")]

    report = analyze_technical_debt(files, graph, _quality(), _semantic(), [])

    assert report.top_debt_modules == []
    assert report.average_debt_score == 0.0


def test_high_churn_and_complexity_together_score_higher_than_either_alone():
    graph = nx.DiGraph()
    for n in ("hot.py", "churny_only.py", "complex_only.py"):
        graph.add_node(n, type="module")
    files = [_file("hot.py", functions=1), _file("churny_only.py", functions=1), _file("complex_only.py", functions=1)]
    quality = _quality(
        issues=[
            QualityIssue(file="hot.py", line=1, kind="high_complexity", message="x", severity="important"),
            QualityIssue(file="complex_only.py", line=1, kind="high_complexity", message="x", severity="important"),
        ]
    )
    commits = [_commit(["hot.py"]), _commit(["hot.py"]), _commit(["churny_only.py"])]

    report = analyze_technical_debt(files, graph, quality, _semantic(), commits)

    scores = {m.file: m.debt_score for m in report.top_debt_modules}
    assert scores["hot.py"] > scores.get("churny_only.py", 0)
    assert scores["hot.py"] > scores.get("complex_only.py", 0)


def test_isolated_component_smell_does_not_count_as_debt():
    # Regression test for a real bug found by dogfooding on Atlas's own
    # repo: lumping every architectural_smell into the debt score flagged
    # a disconnected, trivially-safe-to-change file the same as a real
    # god module.
    from app.models import ArchitecturalSmell

    graph = nx.DiGraph()
    graph.add_node("orphan.py", type="module")
    files = [_file("orphan.py")]
    semantic = _semantic(
        architectural_smells=[
            ArchitecturalSmell(file="orphan.py", kind="isolated_component", message="x", severity="minor")
        ]
    )

    report = analyze_technical_debt(files, graph, _quality(), semantic, [])

    assert report.top_debt_modules == []


def test_utility_dumping_smell_does_count_as_debt():
    from app.models import ArchitecturalSmell

    graph = nx.DiGraph()
    graph.add_node("utils.py", type="module")
    files = [_file("utils.py")]
    semantic = _semantic(
        architectural_smells=[
            ArchitecturalSmell(file="utils.py", kind="utility_dumping", message="x", severity="minor")
        ]
    )

    report = analyze_technical_debt(files, graph, _quality(), semantic, [])

    assert len(report.top_debt_modules) == 1
    assert report.top_debt_modules[0].category == "coupling_smell"


def test_circular_cluster_membership_counts_as_debt():
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")
    files = [_file("a.py"), _file("b.py")]

    report = analyze_technical_debt(files, graph, _quality(), _semantic(), [])

    assert {m.file for m in report.top_debt_modules} == {"a.py", "b.py"}
    assert all(m.category == "circular_cluster" for m in report.top_debt_modules)


def test_confidence_is_low_without_git_history():
    from app.models import ArchitecturalSmell

    graph = nx.DiGraph()
    graph.add_node("utils.py", type="module")
    files = [_file("utils.py")]
    semantic = _semantic(
        architectural_smells=[
            ArchitecturalSmell(file="utils.py", kind="utility_dumping", message="x", severity="minor")
        ]
    )

    report = analyze_technical_debt(files, graph, _quality(), semantic, [])  # no commits

    assert report.top_debt_modules[0].confidence == "low"


def test_confidence_is_low_when_betweenness_was_not_computed():
    from app.models import ArchitecturalSmell

    graph = nx.DiGraph()
    graph.add_node("utils.py", type="module")
    files = [_file("utils.py")]
    semantic = _semantic(
        architecture_health=ArchitectureHealth(
            module_count=1, import_edge_count=0, circular_cluster_count=0,
            articulation_point_count=0, bridge_count=0, betweenness_computed=False,
            dependency_concentration_top5_ratio=0.0,
        ),
        architectural_smells=[
            ArchitecturalSmell(file="utils.py", kind="utility_dumping", message="x", severity="minor")
        ],
    )
    commits = [_commit(["utils.py"])]

    report = analyze_technical_debt(files, graph, _quality(), semantic, commits)

    assert report.top_debt_modules[0].confidence == "low"


def test_recommended_refactoring_order_matches_top_debt_modules_sorted():
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")
    files = [_file("a.py"), _file("b.py")]

    report = analyze_technical_debt(files, graph, _quality(), _semantic(), [])

    assert report.recommended_refactoring_order == [m.file for m in report.top_debt_modules]
