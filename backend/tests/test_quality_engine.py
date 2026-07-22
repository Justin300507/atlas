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


def test_circular_import_detected_and_penalized():
    files = [_clean_file("a.py"), _clean_file("b.py")]
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")

    report = analyze_quality(files, graph)

    assert report.architecture_score == 85
    assert report.overall_score == round((100 + 85) / 2)
    kinds = {issue.kind for issue in report.issues}
    assert "circular_import" in kinds


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
