import networkx as nx

from app.code_parser import FileSymbols, FunctionInfo
from app.quality_engine import analyze_quality


def _clean_file(path: str) -> FileSymbols:
    return FileSymbols(
        path=path,
        language="python",
        functions=[FunctionInfo(name="ok", start_line=1, end_line=5, branch_count=1)],
        class_names=["Widget"],
    )


def test_clean_repo_scores_100():
    files = [_clean_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.overall_score == 100
    assert report.maintainability_score == 100
    assert report.architecture_score == 100
    assert report.issues == []


def test_small_circular_dependency_cluster_penalized_and_classified_minor():
    files = [_clean_file("a.py"), _clean_file("b.py")]
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")

    report = analyze_quality(files, graph)

    # 1 cluster (-10) + largest-cluster-size penalty (2 modules * 2 = 4) +
    # participation penalty (100% of modules entangled * 30) = 100 - 44 = 56.
    assert report.architecture_score == 56
    assert report.overall_score == round((100 + 56) / 2)
    circular_issues = [i for i in report.issues if i.kind == "circular_import"]
    assert len(circular_issues) == 1
    assert circular_issues[0].severity == "minor"


def test_densely_connected_cluster_reported_as_one_cluster_not_many_cycles():
    # Regression test: a real-repo validation run against pallets/flask and
    # tiangolo/typer found that enumerating simple cycles (nx.simple_cycles)
    # turns one real "these modules are mutually entangled" fact into tens of
    # thousands of individual cycle enumerations once a strongly connected
    # component exists — a fully-connected 4-node cluster alone produces many
    # distinct simple cycles, but it is still exactly one entangled cluster.
    nodes = ["a.py", "b.py", "c.py", "d.py"]
    files = [_clean_file(n) for n in nodes]
    graph = nx.DiGraph()
    for n in nodes:
        graph.add_node(n, type="module")
    for u in nodes:
        for v in nodes:
            if u != v:
                graph.add_edge(u, v, type="import")

    report = analyze_quality(files, graph)

    circular_issues = [i for i in report.issues if i.kind == "circular_import"]
    assert len(circular_issues) == 1
    assert report.architecture_score == 52


def test_large_circular_dependency_cluster_classified_critical_and_message_capped():
    nodes = [f"mod_{i:02d}.py" for i in range(25)]
    files = [_clean_file(n) for n in nodes]
    graph = nx.DiGraph()
    for n in nodes:
        graph.add_node(n, type="module")
    for i in range(25):
        graph.add_edge(nodes[i], nodes[(i + 1) % 25], type="import")

    report = analyze_quality(files, graph)

    circular_issues = [i for i in report.issues if i.kind == "circular_import"]
    assert len(circular_issues) == 1
    issue = circular_issues[0]
    assert issue.severity == "critical"
    assert "Circular dependency cluster of 25 modules" in issue.message
    assert "and 5 more" in issue.message
    assert report.architecture_score == 20


def test_long_function_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="huge", start_line=1, end_line=60, branch_count=0)],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 95
    kinds = {issue.kind for issue in report.issues}
    assert "long_function" in kinds


def test_high_complexity_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="tangled", start_line=1, end_line=5, branch_count=11)],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 95
    kinds = {issue.kind for issue in report.issues}
    assert "high_complexity" in kinds


def test_naming_violations_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="BadName", start_line=1, end_line=2, branch_count=0)],
            class_names=["lowercase_class"],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 96
    kinds = [issue.kind for issue in report.issues]
    assert kinds.count("naming_convention") == 2


def test_architecture_score_floors_at_zero_with_many_clusters():
    files = []
    graph = nx.DiGraph()
    for i in range(20):
        a, b = f"c{i}_a.py", f"c{i}_b.py"
        files.append(_clean_file(a))
        files.append(_clean_file(b))
        graph.add_node(a, type="module")
        graph.add_node(b, type="module")
        graph.add_edge(a, b, type="import")
        graph.add_edge(b, a, type="import")

    report = analyze_quality(files, graph)

    assert report.architecture_score == 0


def test_scores_never_go_below_zero():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[
                FunctionInfo(name="Bad" * 10, start_line=1, end_line=200, branch_count=50)
                for _ in range(50)
            ],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 0
    assert report.overall_score >= 0
