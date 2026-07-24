from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from tree_sitter_languages import get_parser

_LANGUAGE_BY_EXT = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "tsx",
}

_ROUTE_PATTERN = re.compile(
    rb"""(?:@app|@router|app|router)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


_BRANCH_NODE_TYPES: dict[str, set[str]] = {
    "python": {
        "if_statement",
        "elif_clause",
        "for_statement",
        "while_statement",
        "except_clause",
        "conditional_expression",
    },
    "javascript": {
        "if_statement",
        "for_statement",
        "for_in_statement",
        "while_statement",
        "do_statement",
        "switch_case",
        "catch_clause",
        "ternary_expression",
    },
}
_BRANCH_NODE_TYPES["typescript"] = _BRANCH_NODE_TYPES["javascript"]
_BRANCH_NODE_TYPES["tsx"] = _BRANCH_NODE_TYPES["javascript"]


@dataclass
class FunctionInfo:
    name: str
    start_line: int
    end_line: int
    branch_count: int


@dataclass
class FileSymbols:
    path: str
    language: str
    imports: list[str] = field(default_factory=list)
    defined: list[str] = field(default_factory=list)
    routes: list[tuple[str, str]] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)


def language_for(path: Path) -> str | None:
    return _LANGUAGE_BY_EXT.get(path.suffix)


def _text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _module_call_argument(node, source: bytes) -> str | None:
    """Return the string argument of a `require(...)` call or a dynamic
    `import(...)` expression, or None if this call_expression is neither."""
    children = node.children
    if not children:
        return None
    head = children[0]
    is_require = head.type == "identifier" and _text(head, source) == "require"
    is_dynamic_import = head.type == "import"
    if not is_require and not is_dynamic_import:
        return None
    for child in children:
        if child.type != "arguments":
            continue
        for arg in child.children:
            if arg.type == "string":
                return _text(arg, source).strip("'\"")
    return None


def _extract_imports(root, source: bytes, lang: str) -> list[str]:
    imports: list[str] = []

    def walk(node):
        if lang == "python" and node.type in ("import_statement", "import_from_statement"):
            imports.append(_text(node, source).strip())
        elif lang in ("javascript", "typescript", "tsx") and node.type == "import_statement":
            for child in node.children:
                if child.type == "string":
                    imports.append(_text(child, source).strip("'\""))
        elif lang in ("javascript", "typescript", "tsx") and node.type == "call_expression":
            specifier = _module_call_argument(node, source)
            if specifier is not None:
                imports.append(specifier)
        for child in node.children:
            walk(child)

    walk(root)
    return imports


def _extract_defined(root, source: bytes, lang: str) -> list[str]:
    defined: list[str] = []
    target_types = (
        ("function_definition", "class_definition")
        if lang == "python"
        else ("function_declaration", "class_declaration")
    )

    def walk(node):
        if node.type in target_types:
            for child in node.children:
                if child.type in ("identifier", "type_identifier"):
                    defined.append(_text(child, source))
                    break
        for child in node.children:
            walk(child)

    walk(root)
    return defined


def _string_node_byte_ranges(root) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []

    def walk(node):
        if node.type == "string":
            ranges.append((node.start_byte, node.end_byte))
            return  # nothing inside a string literal needs separate matching
        for child in node.children:
            walk(child)

    walk(root)
    return ranges


def _extract_routes(root, source: bytes) -> list[tuple[str, str]]:
    # A raw regex scan over the whole file can't distinguish a real
    # `@app.get("/x")` decorator from the same text appearing inside a
    # string literal -- e.g. an LLM prompt template embedding example API
    # code as documentation. A real decorator's own path argument is a
    # *separate*, later string node than the "@app.get(" text itself, so
    # excluding matches whose start falls inside *any* string node's byte
    # range filters out the embedded-in-a-string case without touching
    # real decorators. Reported against a real repo where routes were
    # extracted from *_prompt.py files (2026-07-24).
    string_ranges = _string_node_byte_ranges(root)
    routes: list[tuple[str, str]] = []
    for m in _ROUTE_PATTERN.finditer(source):
        if any(start <= m.start() < end for start, end in string_ranges):
            continue
        routes.append((m.group(1).decode("ascii").upper(), m.group(2).decode("utf-8", errors="ignore")))
    return routes


def _count_branches(node, lang: str) -> int:
    branch_types = _BRANCH_NODE_TYPES.get(lang, set())
    count = 0

    def walk(n):
        nonlocal count
        if n.type in branch_types:
            count += 1
        for child in n.children:
            walk(child)

    walk(node)
    return count


def _extract_functions(root, source: bytes, lang: str) -> list[FunctionInfo]:
    functions: list[FunctionInfo] = []
    target_types = ("function_definition",) if lang == "python" else ("function_declaration",)

    def walk(node):
        if node.type in target_types:
            name = None
            for child in node.children:
                if child.type in ("identifier", "type_identifier"):
                    name = _text(child, source)
                    break
            if name:
                functions.append(
                    FunctionInfo(
                        name=name,
                        start_line=node.start_point[0] + 1,
                        end_line=node.end_point[0] + 1,
                        branch_count=_count_branches(node, lang),
                    )
                )
        for child in node.children:
            walk(child)

    walk(root)
    return functions


def _extract_class_names(root, source: bytes, lang: str) -> list[str]:
    class_types = ("class_definition",) if lang == "python" else ("class_declaration",)
    names: list[str] = []

    def walk(node):
        if node.type in class_types:
            for child in node.children:
                if child.type in ("identifier", "type_identifier"):
                    names.append(_text(child, source))
                    break
        for child in node.children:
            walk(child)

    walk(root)
    return names


def parse_file(path: Path) -> FileSymbols | None:
    lang = language_for(path)
    if lang is None:
        return None
    source = path.read_bytes()
    parser = get_parser(lang)
    tree = parser.parse(source)
    imports = _extract_imports(tree.root_node, source, lang)
    defined = _extract_defined(tree.root_node, source, lang)
    routes = _extract_routes(tree.root_node, source)
    functions = _extract_functions(tree.root_node, source, lang)
    class_names = _extract_class_names(tree.root_node, source, lang)
    return FileSymbols(
        path=str(path),
        language=lang,
        imports=imports,
        defined=defined,
        routes=routes,
        functions=functions,
        class_names=class_names,
    )
