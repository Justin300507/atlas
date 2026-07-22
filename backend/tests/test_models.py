from app.models import AnalyzeRequest, AnalyzeResponse, GraphEdge, GraphNode, GraphResponse, QualityIssue, QualityReport, StackReport


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
