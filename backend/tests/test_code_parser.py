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


def test_route_pattern_inside_a_string_literal_is_not_extracted_as_a_real_route():
    # Regression test: a raw regex scan over the whole file text can't
    # distinguish a real `@app.get(...)` decorator from the same text
    # appearing inside an LLM prompt template string embedding example API
    # code as documentation. Reported against a real repo where routes
    # were extracted from *_prompt.py files (2026-07-24).
    symbols = parse_file(FIXTURES / "python_symbols" / "prompt_with_embedded_route_text.py")
    assert symbols is not None
    assert symbols.routes == []


def test_route_pattern_inside_a_comment_is_not_extracted_as_a_real_route(tmp_path):
    # Regression test found via dogfooding on Atlas's own code_parser.py:
    # the fix for routes-inside-string-literals didn't cover comments,
    # since tree-sitter comment nodes aren't string nodes -- this file's
    # own docstring-style comments describing that fix (containing example
    # text like "@app.get(...)") were themselves extracted as fake routes
    # (2026-07-24).
    path = tmp_path / "commented.py"
    path.write_text('# See the real decorator: @app.get("/users")\ndef f():\n    pass\n')

    symbols = parse_file(path)

    assert symbols is not None
    assert symbols.routes == []


def test_parse_js_file_extracts_imports_defs_and_routes():
    symbols = parse_file(FIXTURES / "js_symbols" / "sample.js")
    assert symbols is not None
    assert any("express" in imp for imp in symbols.imports)
    assert "helper" in symbols.defined
    assert "ItemService" in symbols.defined
    assert ("GET", "/items") in symbols.routes


def test_parse_js_file_extracts_commonjs_require_calls():
    symbols = parse_file(FIXTURES / "commonjs" / "sample.js")
    assert symbols is not None
    assert "express" in symbols.imports
    assert "./router" in symbols.imports
    assert "./side-effect" in symbols.imports
    assert "nested-package" in symbols.imports
    # require(dynamicPath) has a non-literal argument — can't be resolved
    # statically, so it must not produce a bogus "dynamicPath" entry.
    assert "dynamicPath" not in symbols.imports
    assert "./computed" not in symbols.imports
    assert "./lazy-module" in symbols.imports


def test_parse_python_file_extracts_function_line_spans_and_branch_counts():
    symbols = parse_file(FIXTURES / "function_info" / "branchy.py")
    assert symbols is not None
    by_name = {f.name: f for f in symbols.functions}
    assert by_name["classify"].start_line == 1
    assert by_name["classify"].end_line == 7
    assert by_name["classify"].branch_count == 2
    assert by_name["simple"].start_line == 10
    assert by_name["simple"].end_line == 11
    assert by_name["simple"].branch_count == 0


def test_parse_js_file_extracts_function_line_spans_and_branch_counts():
    symbols = parse_file(FIXTURES / "function_info" / "branchy.js")
    assert symbols is not None
    by_name = {f.name: f for f in symbols.functions}
    assert by_name["classify"].start_line == 1
    assert by_name["classify"].end_line == 9
    assert by_name["classify"].branch_count == 2
    assert by_name["simple"].start_line == 11
    assert by_name["simple"].end_line == 13
    assert by_name["simple"].branch_count == 0


def test_parse_python_file_extracts_class_names():
    symbols = parse_file(FIXTURES / "python_symbols" / "sample.py")
    assert symbols is not None
    assert "ItemService" in symbols.class_names


def test_parse_js_file_extracts_class_names():
    symbols = parse_file(FIXTURES / "js_symbols" / "sample.js")
    assert symbols is not None
    assert "ItemService" in symbols.class_names
