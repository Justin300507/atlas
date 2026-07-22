from app.code_parser import FileSymbols
from app.graph_builder import build_graph, to_node_link


def test_build_graph_creates_module_and_route_nodes():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            imports=["from app.services import util"],
            defined=["run"],
            routes=[("GET", "/items")],
        ),
        FileSymbols(path="app/services.py", language="python", imports=[], defined=["util"], routes=[]),
    ]

    graph = build_graph(files)
    data = to_node_link(graph)

    node_ids = {n["id"] for n in data["nodes"]}
    assert "app/main.py" in node_ids
    assert "app/services.py" in node_ids
    assert "route:GET /items" in node_ids

    edge_triples = {(e["source"], e["target"], e["type"]) for e in data["edges"]}
    assert ("app/main.py", "route:GET /items", "route") in edge_triples
    assert ("app/main.py", "app/services.py", "import") in edge_triples
