from app.models import AnalyzeRequest, GraphEdge, GraphNode, GraphResponse, StackReport


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
