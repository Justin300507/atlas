from __future__ import annotations

import re
from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols

_PY_IMPORT_MODULE_RE = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))")
_JS_EXTENSIONS = (".js", ".jsx", ".ts", ".tsx")


def build_graph(files: list[FileSymbols], repo_root: Path | None = None) -> nx.DiGraph:
    graph = nx.DiGraph()
    for f in files:
        graph.add_node(f.path, type="module")

    py_index = _build_python_module_index(files, repo_root)
    js_index = _build_js_path_index(files, repo_root)

    for f in files:
        container_parts = _module_parts(repo_root, f.path)[:-1]
        for imp in f.imports:
            target = _resolve_import_target(f, imp, container_parts, py_index, js_index)
            if target and target != f.path:
                graph.add_edge(f.path, target, type="import")
        for method, route_path in f.routes:
            route_id = f"route:{method} {route_path}"
            graph.add_node(route_id, type="route")
            graph.add_edge(f.path, route_id, type="route")

    return graph


def _module_parts(repo_root: Path | None, path: str) -> list[str]:
    rel = PurePath(path)
    if repo_root is not None:
        try:
            rel = PurePath(Path(path).relative_to(repo_root))
        except ValueError:
            rel = PurePath(path)
    return [part for part in rel.as_posix().split("/") if part not in ("", ".")]


def _build_python_module_index(files: list[FileSymbols], repo_root: Path | None) -> dict[str, str]:
    index: dict[str, str] = {}
    for f in files:
        if f.language != "python":
            continue
        parts = _module_parts(repo_root, f.path)
        if not parts:
            continue
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        elif parts[-1].endswith(".py"):
            parts = parts[:-1] + [parts[-1][: -len(".py")]]
        if not parts:
            continue
        index[".".join(parts)] = f.path
    return index


def _build_js_path_index(files: list[FileSymbols], repo_root: Path | None) -> dict[tuple[str, ...], str]:
    index: dict[tuple[str, ...], str] = {}
    for f in files:
        if f.language not in ("javascript", "typescript", "tsx"):
            continue
        parts = _module_parts(repo_root, f.path)
        if not parts:
            continue
        stem = parts[-1]
        for ext in _JS_EXTENSIONS:
            if stem.endswith(ext):
                stem = stem[: -len(ext)]
                break
        index[tuple(parts[:-1] + [stem])] = f.path
        if stem == "index":
            index[tuple(parts[:-1])] = f.path
    return index


def _resolve_python_import(module: str, container_parts: list[str], index: dict[str, str]) -> str | None:
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        remainder = module[dots:]
        levels_up = dots - 1
        if levels_up > len(container_parts):
            return None
        base = container_parts[: len(container_parts) - levels_up] if levels_up else list(container_parts)
        remainder_parts = [p for p in remainder.split(".") if p] if remainder else []
        dotted = ".".join(base + remainder_parts)
    else:
        dotted = module
    if not dotted:
        return None
    return index.get(dotted)


def _resolve_js_import(
    imp: str, container_parts: list[str], index: dict[tuple[str, ...], str]
) -> str | None:
    if not imp.startswith("."):
        # A bare specifier (e.g. "react", "express") is an external package,
        # not a local file — resolving it against local files by suffix is
        # exactly the false-positive-prone shortcut this function replaces.
        return None

    parts = list(container_parts)
    for segment in imp.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return index.get(tuple(parts))


def _resolve_import_target(
    f: FileSymbols,
    imp: str,
    container_parts: list[str],
    py_index: dict[str, str],
    js_index: dict[tuple[str, ...], str],
) -> str | None:
    if f.language == "python":
        match = _PY_IMPORT_MODULE_RE.match(imp)
        if not match:
            return None
        module = match.group(1) or match.group(2)
        if not module:
            return None
        return _resolve_python_import(module, container_parts, py_index)
    return _resolve_js_import(imp, container_parts, js_index)


def to_node_link(graph: nx.DiGraph) -> dict:
    return {
        "nodes": [{"id": n, "type": d.get("type", "module")} for n, d in graph.nodes(data=True)],
        "edges": [
            {"source": u, "target": v, "type": d.get("type", "import")}
            for u, v, d in graph.edges(data=True)
        ],
    }
