from pathlib import Path

import networkx as nx

from app.code_parser import FileSymbols
from app.doc_generator import generate_documentation
from app.models import (
    FileChurn,
    GitIntelligenceReport,
    QualityIssue,
    QualityReport,
    StackReport,
)

REPO_ROOT = Path("/repo")


def _file(rel_path: str, **kwargs) -> FileSymbols:
    return FileSymbols(path=str(REPO_ROOT / rel_path), language="python", **kwargs)


def _empty_quality() -> QualityReport:
    return QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[])


def _empty_git() -> GitIntelligenceReport:
    return GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )


def test_executive_summary_reports_stack_and_scores():
    stack = StackReport(backend="FastAPI", database="PostgreSQL")
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, stack, files, graph, _empty_quality(), _empty_git())

    assert "## Executive Summary" in doc
    assert "FastAPI" in doc
    assert "PostgreSQL" in doc
    assert "Files analyzed: 1" in doc
    assert "100" in doc


def test_api_reference_lists_routes_with_relative_paths():
    files = [_file("app/main.py", routes=[("GET", "/users"), ("POST", "/users")])]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_git())

    assert "## API Reference" in doc
    assert "GET" in doc and "/users" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_directory_guide_groups_by_top_level_directory():
    files = [_file("app/main.py"), _file("app/utils.py"), _file("scripts/run.py")]
    graph = nx.DiGraph()

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_git())

    assert "## Directory Guide" in doc
    assert "app" in doc
    assert "scripts" in doc


def test_architecture_overview_ranks_most_depended_upon_module():
    a = str(REPO_ROOT / "a.py")
    b = str(REPO_ROOT / "b.py")
    c = str(REPO_ROOT / "c.py")
    graph = nx.DiGraph()
    for n in (a, b, c):
        graph.add_node(n, type="module")
    graph.add_edge(a, c, type="import")
    graph.add_edge(b, c, type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_git())

    assert "## Architecture Overview" in doc
    assert "c.py" in doc


def test_risk_areas_lists_quality_issues_with_relative_paths():
    quality = QualityReport(
        overall_score=90,
        maintainability_score=85,
        architecture_score=95,
        issues=[
            QualityIssue(
                file=str(REPO_ROOT / "app/main.py"),
                line=10,
                kind="long_function",
                message="Function 'run' is 60 lines",
                severity="minor",
            )
        ],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_git())

    assert "## Risk Areas" in doc
    assert "long_function" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_risk_areas_caps_at_20_with_overflow_note():
    # Regression test: a real-repo validation run produced tens of thousands
    # of quality issues before the circular-import scoring redesign, and
    # dumping all of them into the report produced tens of megabytes of
    # Markdown. Risk Areas must never render more than a bounded number of
    # findings inline.
    issues = [
        QualityIssue(file=f"app/mod_{i}.py", line=1, kind="long_function", message="x", severity="minor")
        for i in range(25)
    ]
    quality = QualityReport(overall_score=0, maintainability_score=0, architecture_score=100, issues=issues)

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_git())

    section = doc.split("## Risk Areas")[1].split("## ")[0]
    assert section.count("mod_") == 20
    assert "and 5 additional findings" in section


def test_high_churn_section_lists_top_files_and_truncation_state():
    git_report = GitIntelligenceReport(
        commits_analyzed=500,
        history_truncated=True,
        churn=[FileChurn(file="app/main.py", commit_count=12, bug_fix_count=3)],
        ownership=[],
        co_changes=[],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), git_report)

    assert "## Recent High-Churn Components" in doc
    assert "app/main.py" in doc
    assert "12" in doc
    assert "truncated" in doc.lower()


def test_dependency_diagram_caps_at_40_nodes_with_note():
    graph = nx.DiGraph()
    for i in range(45):
        graph.add_node(str(REPO_ROOT / f"mod_{i}.py"), type="module")
    for i in range(44):
        graph.add_edge(str(REPO_ROOT / f"mod_{i}.py"), str(REPO_ROOT / f"mod_{i + 1}.py"), type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_git())

    assert "## Dependency Diagram" in doc
    assert "```mermaid" in doc
    assert "capped for readability" in doc


def test_dependency_diagram_ranks_by_import_degree_not_route_degree():
    graph = nx.DiGraph()
    chain = [str(REPO_ROOT / f"mod_{i}.py") for i in range(40)]
    for node in chain:
        graph.add_node(node, type="module")
    for i in range(39):
        graph.add_edge(chain[i], chain[i + 1], type="import")

    route_heavy = str(REPO_ROOT / "route_heavy.py")
    graph.add_node(route_heavy, type="module")
    for i in range(20):
        route_id = f"route:GET /path{i}"
        graph.add_node(route_id, type="route")
        graph.add_edge(route_heavy, route_id, type="route")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_git())

    assert "route_heavy.py" not in doc
    assert "mod_0.py" in doc
    assert "mod_39.py" in doc


def test_empty_repo_renders_without_crashing():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_git()
    )

    for header in (
        "## Executive Summary",
        "## Architecture Overview",
        "## Directory Guide",
        "## API Reference",
        "## Dependency Diagram",
        "## Risk Areas",
        "## Recent High-Churn Components",
    ):
        assert header in doc
