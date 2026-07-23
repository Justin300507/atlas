from app.models import (
    AnalyzeRequest,
    AnalyzeResponse,
    CoChangePair,
    DocumentationResponse,
    FileChurn,
    FileOwnership,
    GitIntelligenceReport,
    GraphEdge,
    GraphNode,
    GraphResponse,
    QualityIssue,
    QualityReport,
    StackReport,
)


def test_stack_report_defaults_to_none():
    report = StackReport()
    assert report.backend is None
    assert report.database is None


def test_analyze_request_requires_repo_url():
    request = AnalyzeRequest(repo_url="https://github.com/example/example")
    assert request.repo_url == "https://github.com/example/example"


def test_graph_response_serializes_nodes_and_edges():
    graph = GraphResponse(
        nodes=[GraphNode(id="a.py", type="module")],
        edges=[GraphEdge(source="a.py", target="b.py", type="import")],
    )
    data = graph.model_dump()
    assert data["nodes"][0]["id"] == "a.py"
    assert data["edges"][0]["type"] == "import"


def test_quality_report_serializes_issues():
    report = QualityReport(
        overall_score=90,
        maintainability_score=85,
        architecture_score=95,
        issues=[
            QualityIssue(
                file="app/main.py",
                line=10,
                kind="long_function",
                message="Function 'run' is 60 lines",
                severity="minor",
            )
        ],
    )
    data = report.model_dump()
    assert data["overall_score"] == 90
    assert data["issues"][0]["kind"] == "long_function"


def test_analyze_response_requires_quality():
    response = AnalyzeResponse(
        stack=StackReport(),
        graph=GraphResponse(nodes=[], edges=[]),
        quality=QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[]),
    )
    assert response.quality.overall_score == 100


def test_git_intelligence_report_serializes():
    report = GitIntelligenceReport(
        commits_analyzed=3,
        history_truncated=False,
        churn=[FileChurn(file="a.py", commit_count=2, bug_fix_count=1)],
        ownership=[
            FileOwnership(
                file="a.py",
                top_author="alice@example.com",
                top_author_commits=1,
                total_commits=2,
                ownership_ratio=0.5,
            )
        ],
        co_changes=[CoChangePair(file_a="a.py", file_b="b.py", co_change_count=1)],
    )
    data = report.model_dump()
    assert data["commits_analyzed"] == 3
    assert data["churn"][0]["bug_fix_count"] == 1
    assert data["co_changes"][0]["co_change_count"] == 1


def test_documentation_response_serializes_markdown():
    response = DocumentationResponse(markdown="## Executive Summary\n\nhello")
    assert "Executive Summary" in response.model_dump()["markdown"]
