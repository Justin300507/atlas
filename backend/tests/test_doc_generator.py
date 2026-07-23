from pathlib import Path

import networkx as nx

from app.code_parser import FileSymbols
from app.doc_generator import generate_documentation
from app.models import (
    FileChurn,
    FileCoverage,
    GitIntelligenceReport,
    QualityIssue,
    QualityReport,
    SecurityIssue,
    SecurityReport,
    StackReport,
)

REPO_ROOT = Path("/repo")


def _file(rel_path: str, **kwargs) -> FileSymbols:
    return FileSymbols(path=str(REPO_ROOT / rel_path), language="python", **kwargs)


def _empty_quality() -> QualityReport:
    return QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[])


def _empty_security() -> SecurityReport:
    return SecurityReport(issues=[])


def _empty_git() -> GitIntelligenceReport:
    return GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )


def test_executive_summary_reports_stack_and_scores():
    stack = StackReport(backend="FastAPI", database="PostgreSQL")
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, stack, files, graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## Executive Summary" in doc
    assert "FastAPI" in doc
    assert "PostgreSQL" in doc
    assert "Files analyzed: 1" in doc
    assert "100" in doc


def test_executive_summary_omits_coverage_note_when_not_capped():
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")
    coverage = FileCoverage(
        files_analyzed=1, files_capped=False, files_skipped_oversized=0, files_parse_failed=0
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git(), coverage
    )

    assert "Files analyzed: 1\n" in doc


def test_executive_summary_surfaces_truncation_when_file_cap_hit():
    # Regression test for the silent-truncation gap found during real-world
    # validation (2026-07-24): a capped analysis must say so in the report
    # itself, not just in an internal field nobody reads.
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")
    coverage = FileCoverage(
        files_analyzed=5000, files_capped=True, files_skipped_oversized=12, files_parse_failed=3
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git(), coverage
    )

    assert "repository truncated at the file-count cap" in doc
    assert "12 skipped for exceeding the size limit" in doc
    assert "3 failed to parse" in doc


def test_api_reference_lists_routes_with_relative_paths():
    files = [_file("app/main.py", routes=[("GET", "/users"), ("POST", "/users")])]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## API Reference" in doc
    assert "GET" in doc and "/users" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_directory_guide_groups_by_top_level_directory():
    files = [_file("app/main.py"), _file("app/utils.py"), _file("scripts/run.py")]
    graph = nx.DiGraph()

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git())

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

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

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

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git())

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

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git())

    section = doc.split("## Risk Areas")[1].split("## ")[0]
    assert section.count("mod_") == 20
    assert "and 5 additional findings" in section


def test_security_findings_lists_issues_with_relative_paths():
    security = SecurityReport(
        issues=[
            SecurityIssue(
                file=str(REPO_ROOT / "app/config.py"),
                line=5,
                kind="hardcoded_secret",
                message="Hardcoded AWS access key detected",
                severity="critical",
            )
        ]
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), security, _empty_git()
    )

    assert "## Security Findings" in doc
    assert "hardcoded_secret" in doc
    assert "app/config.py" in doc
    assert str(REPO_ROOT) not in doc


def test_security_findings_reports_none_detected_when_clean():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    section = doc.split("## Security Findings")[1].split("## ")[0]
    assert "No issues detected." in section


def test_high_churn_section_lists_top_files_and_truncation_state():
    git_report = GitIntelligenceReport(
        commits_analyzed=500,
        history_truncated=True,
        churn=[FileChurn(file="app/main.py", commit_count=12, bug_fix_count=3)],
        ownership=[],
        co_changes=[],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), git_report)

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

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

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

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    assert "route_heavy.py" not in doc
    assert "mod_0.py" in doc
    assert "mod_39.py" in doc


def test_empty_repo_renders_without_crashing():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    for header in (
        "## Executive Summary",
        "## Architecture Overview",
        "## Directory Guide",
        "## API Reference",
        "## Dependency Diagram",
        "## Risk Areas",
        "## Security Findings",
        "## Recent High-Churn Components",
        "## Analysis Coverage",
    ):
        assert header in doc


def test_analysis_coverage_footer_discloses_support_and_limitations():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    assert "## Analysis Coverage" in doc
    assert "Python imports" in doc
    assert "ES Module" in doc
    assert "CommonJS" in doc
    assert "Git history" in doc
    assert "Security scanning" in doc
    assert "can't be resolved statically" in doc
    assert "pattern-based" in doc
    assert "heuristic engineering signals" in doc
