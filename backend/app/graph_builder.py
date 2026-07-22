from __future__ import annotations

import re
from pathlib import PurePath

import networkx as nx

from .code_parser import FileSymbols

_PY_IMPORT_MODULE_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")


def build_graph(files: list[FileSymbols]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for f in files:
        graph.add_node(f.path, type="module")

    for f in files:
        for imp in f.imports:
            target = _resolve_import_target(imp, files)
            if target and target != f.path:
                graph.add_edge(f.path, target, type="import")
        for method, route_path in f.routes:
            route_id = f"route:{method} {route_path}"
            graph.add_node(route_id, type="route")
            graph.add_edge(f.path, route_id, type="route")

    return graph


def _extract_module_name(raw_import: str) -> str | None:
    match = _PY_IMPORT_MODULE_RE.match(raw_import)
    if match:
        return match.group(1) or match.group(2)
    return raw_import.strip("'\"./ ") or None


def _resolve_import_target(imp: str, files: list[FileSymbols]) -> str | None:
    module = _extract_module_name(imp)
    if not module:
        return None
    module_as_path = module.replace(".", "/")
    for f in files:
        candidate = PurePath(f.path).as_posix()
        if candidate.endswith(module_as_path + ".py"):
            return f.path
        if candidate.endswith(module_as_path + ".js") or candidate.endswith(module_as_path + ".ts"):
            return f.path
    return None


def to_node_link(graph: nx.DiGraph) -> dict:
    return {
        "nodes": [{"id": n, "type": d.get("type", "module")} for n, d in graph.nodes(data=True)],
        "edges": [
            {"source": u, "target": v, "type": d.get("type", "import")}
            for u, v, d in graph.edges(data=True)
        ],
    }
