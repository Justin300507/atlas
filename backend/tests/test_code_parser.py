from pathlib import Path

from app.code_parser import language_for, parse_file

FIXTURES = Path(__file__).parent / "fixtures"


def test_language_for_recognizes_extensions():
    assert language_for(Path("a.py")) == "python"
    assert language_for(Path("a.tsx")) == "tsx"
    assert language_for(Path("a.md")) is None


def test_parse_python_file_extracts_imports_defs_and_routes():
    symbols = parse_file(FIXTURES / "python_symbols" / "sample.py")
    assert symbols is not None
    assert any("fastapi" in imp for imp in symbols.imports)
    assert "list_items" in symbols.defined
    assert "ItemService" in symbols.defined
    assert ("GET", "/items") in symbols.routes


def test_parse_js_file_extracts_imports_defs_and_routes():
    symbols = parse_file(FIXTURES / "js_symbols" / "sample.js")
    assert symbols is not None
    assert any("express" in imp for imp in symbols.imports)
    assert "helper" in symbols.defined
    assert "ItemService" in symbols.defined
    assert ("GET", "/items") in symbols.routes
