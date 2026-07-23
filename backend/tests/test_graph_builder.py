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

    graph = build_graph(files, repo_root=tmp_path)
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


def test_import_resolution_does_not_false_positive_on_substring_match(tmp_path):
    # Regression test: a real-world validation run against pallets/flask and
    # tiangolo/typer found that `import re` / `import os` were resolving to
    # unrelated local files like `core.py` / `macros.py` purely because the
    # old suffix-based matching used `endswith(module + ".py")` with no
    # path-boundary check ("core.py".endswith("re.py") is True).
    files = [
        FileSymbols(
            path=str(tmp_path / "app" / "thing.py"),
            language="python",
            imports=["import re", "import os"],
            defined=[],
            routes=[],
        ),
        FileSymbols(
            path=str(tmp_path / "app" / "core.py"),
            language="python",
            imports=[],
            defined=[],
            routes=[],
        ),
        FileSymbols(
            path=str(tmp_path / "app" / "macros.py"),
            language="python",
            imports=[],
            defined=[],
            routes=[],
        ),
    ]

    graph = build_graph(files, repo_root=tmp_path)
    data = to_node_link(graph)

    import_edges = [e for e in data["edges"] if e["type"] == "import"]
    assert import_edges == []


def test_relative_import_resolves_to_own_package_init(tmp_path):
    handler = str(tmp_path / "app" / "services" / "handler.py")
    package_init = str(tmp_path / "app" / "services" / "__init__.py")
    files = [
        FileSymbols(path=handler, language="python", imports=["from . import shared"], defined=[], routes=[]),
        FileSymbols(path=package_init, language="python", imports=[], defined=["shared"], routes=[]),
    ]

    graph = build_graph(files, repo_root=tmp_path)
    data = to_node_link(graph)

    edge_triples = {(e["source"], e["target"]) for e in data["edges"]}
    assert (handler, package_init) in edge_triples


def test_relative_import_resolves_to_sibling_module(tmp_path):
    handler = str(tmp_path / "app" / "services" / "handler.py")
    util = str(tmp_path / "app" / "services" / "util.py")
    files = [
        FileSymbols(path=handler, language="python", imports=["from .util import helper"], defined=[], routes=[]),
        FileSymbols(path=util, language="python", imports=[], defined=["helper"], routes=[]),
    ]

    graph = build_graph(files, repo_root=tmp_path)
    data = to_node_link(graph)

    edge_triples = {(e["source"], e["target"]) for e in data["edges"]}
    assert (handler, util) in edge_triples


def test_relative_import_resolves_to_parent_package_sibling(tmp_path):
    handler = str(tmp_path / "app" / "services" / "handler.py")
    models = str(tmp_path / "app" / "models.py")
    files = [
        FileSymbols(path=handler, language="python", imports=["from ..models import User"], defined=[], routes=[]),
        FileSymbols(path=models, language="python", imports=[], defined=["User"], routes=[]),
    ]

    graph = build_graph(files, repo_root=tmp_path)
    data = to_node_link(graph)

    edge_triples = {(e["source"], e["target"]) for e in data["edges"]}
    assert (handler, models) in edge_triples


def test_absolute_dotted_import_resolves_exactly(tmp_path):
    main = str(tmp_path / "app" / "main.py")
    user = str(tmp_path / "app" / "services" / "user.py")
    files = [
        FileSymbols(path=main, language="python", imports=["import app.services.user"], defined=[], routes=[]),
        FileSymbols(path=user, language="python", imports=[], defined=[], routes=[]),
    ]

    graph = build_graph(files, repo_root=tmp_path)
    data = to_node_link(graph)

    edge_triples = {(e["source"], e["target"]) for e in data["edges"]}
    assert (main, user) in edge_triples


def test_js_bare_specifier_does_not_resolve_to_local_file(tmp_path):
    # Same class of bug as the Python substring false-positive above: a bare
    # specifier like "react" (an npm package) must not resolve to a local
    # file named e.g. "react.tsx" just because the name matches.
    app = str(tmp_path / "src" / "App.tsx")
    local_react = str(tmp_path / "src" / "react.tsx")
    files = [
        FileSymbols(path=app, language="tsx", imports=["react"], defined=[], routes=[]),
        FileSymbols(path=local_react, language="tsx", imports=[], defined=[], routes=[]),
    ]

    graph = build_graph(files, repo_root=tmp_path)
    data = to_node_link(graph)

    import_edges = [e for e in data["edges"] if e["type"] == "import"]
    assert import_edges == []
