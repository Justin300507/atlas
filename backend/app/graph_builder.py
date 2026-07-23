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

    py_index, py_index_root_stripped = _build_python_module_index(files, repo_root)
    js_index = _build_js_path_index(files, repo_root)

    for f in files:
        container_parts = _module_parts(repo_root, f.path)[:-1]
        for imp in f.imports:
            target = _resolve_import_target(
                f, imp, container_parts, py_index, py_index_root_stripped, js_index
            )
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


def _build_python_module_index(
    files: list[FileSymbols], repo_root: Path | None
) -> tuple[dict[str, str], dict[str, str]]:
    index: dict[str, str] = {}
    # Fallback index with exactly one leading path segment stripped, keyed the
    # same way. Absolute imports are written relative to whatever directory
    # is actually on sys.path (often not the repo root itself — a top-level
    # "src/" layout is the single most common case, e.g. pallets/flask ships
    # as src/flask/... but its own code does `from flask.helpers import x`,
    # not `from src.flask.helpers import x`). Only consulted when the exact
    # repo-root-relative path doesn't match, so it can't shadow a real match.
    root_stripped_index: dict[str, str] = {}
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
        if len(parts) > 1:
            root_stripped_index.setdefault(".".join(parts[1:]), f.path)
    return index, root_stripped_index


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


def _resolve_python_import(
    module: str,
    container_parts: list[str],
    index: dict[str, str],
    root_stripped_index: dict[str, str],
) -> str | None:
    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        remainder = module[dots:]
        levels_up = dots - 1
        if levels_up > len(container_parts):
            return None
        base = container_parts[: len(container_parts) - levels_up] if levels_up else list(container_parts)
        remainder_parts = [p for p in remainder.split(".") if p] if remainder else []
        dotted = ".".join(base + remainder_parts)
        if not dotted:
            return None
        # Relative imports are anchored to the importing file's own location,
        # which is already unambiguous — no "which directory is the import
        # root" question, so no root-stripped fallback needed here.
        return index.get(dotted)

    if not module:
        return None
    return index.get(module) or root_stripped_index.get(module)


def _strip_js_extension(segment: str) -> str:
    for ext in _JS_EXTENSIONS:
        if segment.endswith(ext):
            return segment[: -len(ext)]
    return segment


def _resolve_js_import(
    imp: str, container_parts: list[str], index: dict[tuple[str, ...], str]
) -> str | None:
    if not imp.startswith("."):
        # A bare specifier (e.g. "react", "express") is an external package,
        # not a local file — resolving it against local files by suffix is
        # exactly the false-positive-prone shortcut this function replaces.
        return None

    segments = imp.split("/")
    if segments:
        # The index is built with extensions already stripped (Node ESM
        # allows "./utils" and "./utils.js" to refer to the same file); strip
        # the same way here so an explicit-extension specifier still matches.
        segments[-1] = _strip_js_extension(segments[-1])

    parts = list(container_parts)
    for segment in segments:
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
    py_index_root_stripped: dict[str, str],
    js_index: dict[tuple[str, ...], str],
) -> str | None:
    if f.language == "python":
        match = _PY_IMPORT_MODULE_RE.match(imp)
        if not match:
            return None
        module = match.group(1) or match.group(2)
        if not module:
            return None
        return _resolve_python_import(module, container_parts, py_index, py_index_root_stripped)
    return _resolve_js_import(imp, container_parts, js_index)


def to_node_link(graph: nx.DiGraph) -> dict:
    return {
        "nodes": [{"id": n, "type": d.get("type", "module")} for n, d in graph.nodes(data=True)],
        "edges": [
            {"source": u, "target": v, "type": d.get("type", "import")}
            for u, v, d in graph.edges(data=True)
        ],
    }
