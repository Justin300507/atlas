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
    r"""(?:@app|@router|app|router)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*["']([^"']+)["']""",
    re.IGNORECASE,
)


@dataclass
class FileSymbols:
    path: str
    language: str
    imports: list[str] = field(default_factory=list)
    defined: list[str] = field(default_factory=list)
    routes: list[tuple[str, str]] = field(default_factory=list)


def language_for(path: Path) -> str | None:
    return _LANGUAGE_BY_EXT.get(path.suffix)


def _text(node, source: bytes) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8", errors="ignore")


def _extract_imports(root, source: bytes, lang: str) -> list[str]:
    imports: list[str] = []

    def walk(node):
        if lang == "python" and node.type in ("import_statement", "import_from_statement"):
            imports.append(_text(node, source).strip())
        elif lang in ("javascript", "typescript", "tsx") and node.type == "import_statement":
            for child in node.children:
                if child.type == "string":
                    imports.append(_text(child, source).strip("'\""))
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


def parse_file(path: Path) -> FileSymbols | None:
    lang = language_for(path)
    if lang is None:
        return None
    source = path.read_bytes()
    parser = get_parser(lang)
    tree = parser.parse(source)
    imports = _extract_imports(tree.root_node, source, lang)
    defined = _extract_defined(tree.root_node, source, lang)
    raw_routes = _ROUTE_PATTERN.findall(source.decode("utf-8", errors="ignore"))
    routes = [(method.upper(), route_path) for method, route_path in raw_routes]
    return FileSymbols(path=str(path), language=lang, imports=imports, defined=defined, routes=routes)
