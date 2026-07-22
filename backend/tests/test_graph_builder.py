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


def test_build_graph_resolves_imports_with_native_path_separators(tmp_path):
    # Regression test for a Windows path-separator bug: `f.path` comes from
    # `str(path)` on a real pathlib.Path built via rglob, which uses the OS
    # native separator (backslash on Windows). Hardcoded forward-slash string
    # literals (as used above) hide that bug, so this test builds files via a
    # real tmp_path + rglob walk instead.
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    (app_dir / "main.py").write_text("from app.services import util\n")
    (app_dir / "services.py").write_text("def util():\n    pass\n")

    py_files = sorted(tmp_path.rglob("*.py"), key=lambda p: p.name)
    main_path, services_path = py_files[0], py_files[1]

    files = [
        FileSymbols(
            path=str(main_path),
            language="python",
            imports=["from app.services import util"],
            defined=["run"],
            routes=[],
        ),
        FileSymbols(path=str(services_path), language="python", imports=[], defined=["util"], routes=[]),
    ]

    graph = build_graph(files)
    data = to_node_link(graph)

    edge_triples = {(e["source"], e["target"], e["type"]) for e in data["edges"]}
    assert (str(main_path), str(services_path), "import") in edge_triples


def test_build_graph_resolves_import_to_tsx_and_jsx_targets():
    files = [
        FileSymbols(
            path="src/App.tsx",
            language="tsx",
            imports=["./components/Button", "./components/Widget"],
            defined=["App"],
            routes=[],
        ),
        FileSymbols(
            path="src/components/Button.tsx",
            language="tsx",
            imports=[],
            defined=["Button"],
            routes=[],
        ),
        FileSymbols(
            path="src/components/Widget.jsx",
            language="javascript",
            imports=[],
            defined=["Widget"],
            routes=[],
        ),
    ]

    graph = build_graph(files)
    data = to_node_link(graph)

    edge_triples = {(e["source"], e["target"], e["type"]) for e in data["edges"]}
    assert ("src/App.tsx", "src/components/Button.tsx", "import") in edge_triples
    assert ("src/App.tsx", "src/components/Widget.jsx", "import") in edge_triples
