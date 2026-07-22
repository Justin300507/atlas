# Atlas Phase 2: Code Quality Engine (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Phase 1's `POST /analyze` response with a deterministic `quality`
field reporting circular imports, long functions, high-complexity functions, and
naming-convention violations, rolled up into Maintainability/Architecture/Overall
scores.

**Architecture:** Extend `code_parser.FileSymbols` with per-function line spans and
branch counts (additive, no existing field changes) and a class-name list. A new
`quality_engine.py` module consumes that data plus the existing import graph to
produce a `QualityReport`, which `main.py` wires into the `/analyze` response
alongside the existing `stack` and `graph` fields.

**Tech Stack:** Same as Phase 1 — no new dependencies. Uses `tree-sitter` node
`start_point`/`end_point` (already available on every parsed node) and `networkx`'s
`simple_cycles` (already a dependency via `graph_builder.py`).

## Global Constraints

- Python 3.11+ only; all code lives under `backend/`.
- Stateless: no database, no persistence layer.
- No live-network calls in the default test run.
- Additive only: `FileSymbols`'s existing fields (`path`, `language`, `imports`,
  `defined`, `routes`) keep their current types and meaning — Phase 1's
  `graph_builder.py` and `main.py` code that already consumes `FileSymbols` must
  keep working unmodified except where a task explicitly says to wire in the new
  `quality` field.
- Score categories are limited to what this phase can honestly compute:
  `maintainability_score` and `architecture_score`, averaged into `overall_score`.
  Do not add Testing/Security/Documentation scores — no subsystem produces that data
  yet.
- Thresholds/penalties (exact values below) are v1 heuristics, not tuned against
  real repos — implement them exactly as specified, don't second-guess the numbers.

---

### Task 1: Extend code parser with function line spans, branch counts, and class names

**Files:**
- Modify: `backend/app/code_parser.py`
- Create: `backend/tests/fixtures/function_info/branchy.py`
- Create: `backend/tests/fixtures/function_info/branchy.js`
- Modify: `backend/tests/test_code_parser.py` (add tests, do not remove existing ones)

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `@dataclass FunctionInfo(name: str, start_line: int, end_line: int, branch_count: int)`
  - `FileSymbols` gains two new fields: `functions: list[FunctionInfo]` and
    `class_names: list[str]` (both default to empty list via `field(default_factory=list)`).
    Existing fields (`path`, `language`, `imports`, `defined`, `routes`) are unchanged.
  - Used by Task 3 (`quality_engine`).

- [ ] **Step 1: Create fixture files with known line spans and branch structure**

Create `backend/tests/fixtures/function_info/branchy.py`:

```python
def classify(x):
    if x > 0:
        return "positive"
    elif x < 0:
        return "negative"
    else:
        return "zero"


def simple():
    return 1
```

Create `backend/tests/fixtures/function_info/branchy.js`:

```javascript
function classify(x) {
  if (x > 0) {
    return "positive";
  } else if (x < 0) {
    return "negative";
  } else {
    return "zero";
  }
}

function simple() {
  return 1;
}
```

- [ ] **Step 2: Write the failing tests**

Add to `backend/tests/test_code_parser.py` (keep all existing tests in the file
as-is, add these new ones):

```python
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_code_parser.py -v`
Expected: the four new tests FAIL (`FileSymbols` has no `functions`/`class_names`
fields yet); all pre-existing tests in the file still PASS.

- [ ] **Step 4: Implement the extension**

In `backend/app/code_parser.py`, add the branch-node-type table, the `FunctionInfo`
dataclass, and extend `FileSymbols`:

```python
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
```

Add `functions` and `class_names` fields to the existing `FileSymbols` dataclass
(keep every existing field exactly as-is):

```python
@dataclass
class FileSymbols:
    path: str
    language: str
    imports: list[str] = field(default_factory=list)
    defined: list[str] = field(default_factory=list)
    routes: list[tuple[str, str]] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    class_names: list[str] = field(default_factory=list)
```

Add the extraction helpers (place near the existing `_extract_imports`/`_extract_defined`):

```python
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
```

Update `parse_file` to populate the two new fields (keep every existing line, add
two calls and two constructor arguments):

```python
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
```

**If actual Tree-sitter output doesn't match these assumptions:** the line-span
assertions (`start_line`/`end_line`) are purely positional and should hold regardless
of exact grammar node names. The `branch_count` assertions depend on the exact node
type names in `_BRANCH_NODE_TYPES`; if a real parse shows different type names (e.g.
JS "else if" doesn't nest as a plain `if_statement`, or Python's `elif` isn't
`elif_clause`), inspect the actual tree (print node types recursively) and adjust
`_BRANCH_NODE_TYPES` so the test's *qualitative* intent holds: `classify` must have
`branch_count > 0` and strictly greater than `simple`'s `branch_count` of `0`. If you
must change an exact expected number in the test to match verified real output,
document exactly what you found and why in your report — do not guess repeatedly.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_code_parser.py -v`
Expected: all tests pass (pre-existing + 4 new).

Run the full fast suite to confirm no regression: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all previously-passing tests still pass (this change is additive to
`FileSymbols`, so `graph_builder.py`/`main.py` consumers must be unaffected).

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/code_parser.py backend/tests/fixtures/function_info backend/tests/test_code_parser.py
git commit -m "feat: extract function line spans, branch counts, and class names"
```

---

### Task 2: Add QualityIssue/QualityReport models

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Consumes: nothing new.
- Produces:
  - `QualityIssue(file: str, line: int, kind: str, message: str, severity: str)`
  - `QualityReport(overall_score: int, maintainability_score: int, architecture_score: int, issues: list[QualityIssue])`
  - `AnalyzeResponse` gains a required `quality: QualityReport` field.
  - Used by Task 3 (`quality_engine`) and Task 4 (`main.py`).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py` (keep existing tests):

```python
from app.models import QualityIssue, QualityReport


def test_quality_report_serializes_issues():
    report = QualityReport(
        overall_score=90,
        maintainability_score=85,
        architecture_score=95,
        issues=[
            QualityIssue(
                file="app/main.py",
                line=10,
                kind="long_function",
                message="Function 'run' is 60 lines",
                severity="minor",
            )
        ],
    )
    data = report.model_dump()
    assert data["overall_score"] == 90
    assert data["issues"][0]["kind"] == "long_function"


def test_analyze_response_requires_quality():
    response = AnalyzeResponse(
        stack=StackReport(),
        graph=GraphResponse(nodes=[], edges=[]),
        quality=QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[]),
    )
    assert response.quality.overall_score == 100
```

(`AnalyzeResponse`, `StackReport`, `GraphResponse` are already imported at the top of
`test_models.py` from Task 2 of Phase 1 — add `QualityIssue, QualityReport` to that
existing `from app.models import ...` line rather than duplicating the import line.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError` (`QualityIssue`/`QualityReport` don't exist yet) or
`AnalyzeResponse` missing-field validation error.

- [ ] **Step 3: Implement the models**

In `backend/app/models.py`, add these two classes and update `AnalyzeResponse` (keep
every existing class exactly as-is):

```python
class QualityIssue(BaseModel):
    file: str
    line: int
    kind: str
    message: str
    severity: str


class QualityReport(BaseModel):
    overall_score: int
    maintainability_score: int
    architecture_score: int
    issues: list[QualityIssue]
```

Update the existing `AnalyzeResponse` class to add the new required field:

```python
class AnalyzeResponse(BaseModel):
    stack: StackReport
    graph: GraphResponse
    quality: QualityReport
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: all tests pass (pre-existing + 2 new).

This will break `test_api.py`'s existing tests that construct `AnalyzeResponse`
indirectly via the real `/analyze` endpoint, since `quality` is now required —
that's expected and gets fixed in Task 4. Confirm this is the *only* other test file
affected: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"` —
expect `test_api.py`'s `test_analyze_returns_stack_and_graph` and
`test_analyze_skips_unparseable_file_and_continues` to now fail with a
`ResponseValidationError` or similar (missing `quality`), and every other test file
to still pass. Do not try to fix `test_api.py` in this task — that's Task 4's job.

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add QualityIssue and QualityReport models"
```

---

### Task 3: Quality engine (circular imports, long functions, complexity, naming)

**Files:**
- Create: `backend/app/quality_engine.py`
- Create: `backend/tests/test_quality_engine.py`

**Interfaces:**
- Consumes: `app.code_parser.FileSymbols` and `FunctionInfo` (Task 1);
  `app.models.QualityIssue`, `QualityReport` (Task 2); `networkx.DiGraph` as produced
  by `app.graph_builder.build_graph` (Phase 1).
- Produces: `analyze_quality(files: list[FileSymbols], graph: nx.DiGraph) -> QualityReport`,
  importable as `from app.quality_engine import analyze_quality`. Used by Task 4
  (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_quality_engine.py`:

```python
import networkx as nx

from app.code_parser import FileSymbols, FunctionInfo
from app.quality_engine import analyze_quality


def _clean_file(path: str) -> FileSymbols:
    return FileSymbols(
        path=path,
        language="python",
        functions=[FunctionInfo(name="ok", start_line=1, end_line=5, branch_count=1)],
        class_names=["Widget"],
    )


def test_clean_repo_scores_100():
    files = [_clean_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.overall_score == 100
    assert report.maintainability_score == 100
    assert report.architecture_score == 100
    assert report.issues == []


def test_circular_import_detected_and_penalized():
    files = [_clean_file("a.py"), _clean_file("b.py")]
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")

    report = analyze_quality(files, graph)

    assert report.architecture_score == 85
    assert report.overall_score == round((100 + 85) / 2)
    kinds = {issue.kind for issue in report.issues}
    assert "circular_import" in kinds


def test_long_function_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="huge", start_line=1, end_line=60, branch_count=0)],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 95
    kinds = {issue.kind for issue in report.issues}
    assert "long_function" in kinds


def test_high_complexity_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="tangled", start_line=1, end_line=5, branch_count=11)],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 95
    kinds = {issue.kind for issue in report.issues}
    assert "high_complexity" in kinds


def test_naming_violations_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="BadName", start_line=1, end_line=2, branch_count=0)],
            class_names=["lowercase_class"],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 96
    kinds = [issue.kind for issue in report.issues]
    assert kinds.count("naming_convention") == 2


def test_scores_never_go_below_zero():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[
                FunctionInfo(name="Bad" * 10, start_line=1, end_line=200, branch_count=50)
                for _ in range(50)
            ],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 0
    assert report.overall_score >= 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_quality_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.quality_engine'`

- [ ] **Step 3: Implement the quality engine**

Create `backend/app/quality_engine.py`:

```python
from __future__ import annotations

import re

import networkx as nx

from .code_parser import FileSymbols
from .models import QualityIssue, QualityReport

_LONG_FUNCTION_LINES = 50
_HIGH_COMPLEXITY_BRANCHES = 10
_CIRCULAR_IMPORT_PENALTY = 15
_LONG_FUNCTION_PENALTY = 5
_HIGH_COMPLEXITY_PENALTY = 5
_NAMING_VIOLATION_PENALTY = 2

_PY_FUNCTION_NAME = re.compile(r"^_{0,2}[a-z][a-z0-9_]*$")
_JS_FUNCTION_NAME = re.compile(r"^_{0,2}[a-z][a-zA-Z0-9]*$")
_CLASS_NAME = re.compile(r"^_?[A-Z][a-zA-Z0-9]*$")


def analyze_quality(files: list[FileSymbols], graph: nx.DiGraph) -> QualityReport:
    issues: list[QualityIssue] = []

    architecture_score = 100
    for cycle in _find_import_cycles(graph):
        architecture_score -= _CIRCULAR_IMPORT_PENALTY
        issues.append(
            QualityIssue(
                file=cycle[0],
                line=0,
                kind="circular_import",
                message=f"Circular import: {' -> '.join(cycle + [cycle[0]])}",
                severity="important",
            )
        )

    maintainability_score = 100
    for f in files:
        function_pattern = _PY_FUNCTION_NAME if f.language == "python" else _JS_FUNCTION_NAME

        for fn in f.functions:
            length = fn.end_line - fn.start_line + 1
            if length > _LONG_FUNCTION_LINES:
                maintainability_score -= _LONG_FUNCTION_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=fn.start_line,
                        kind="long_function",
                        message=f"Function '{fn.name}' is {length} lines (threshold {_LONG_FUNCTION_LINES})",
                        severity="minor",
                    )
                )
            if fn.branch_count > _HIGH_COMPLEXITY_BRANCHES:
                maintainability_score -= _HIGH_COMPLEXITY_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=fn.start_line,
                        kind="high_complexity",
                        message=f"Function '{fn.name}' has branch count {fn.branch_count} (threshold {_HIGH_COMPLEXITY_BRANCHES})",
                        severity="important",
                    )
                )
            if not function_pattern.match(fn.name):
                maintainability_score -= _NAMING_VIOLATION_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=fn.start_line,
                        kind="naming_convention",
                        message=f"Function name '{fn.name}' doesn't follow the expected convention",
                        severity="minor",
                    )
                )

        for class_name in f.class_names:
            if not _CLASS_NAME.match(class_name):
                maintainability_score -= _NAMING_VIOLATION_PENALTY
                issues.append(
                    QualityIssue(
                        file=f.path,
                        line=0,
                        kind="naming_convention",
                        message=f"Class name '{class_name}' doesn't follow PascalCase convention",
                        severity="minor",
                    )
                )

    maintainability_score = max(0, maintainability_score)
    architecture_score = max(0, architecture_score)
    overall_score = round((maintainability_score + architecture_score) / 2)

    return QualityReport(
        overall_score=overall_score,
        maintainability_score=maintainability_score,
        architecture_score=architecture_score,
        issues=issues,
    )


def _find_import_cycles(graph: nx.DiGraph) -> list[list[str]]:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    module_graph = graph.subgraph(module_nodes)
    return [cycle for cycle in nx.simple_cycles(module_graph) if len(cycle) > 1]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_quality_engine.py -v`
Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/quality_engine.py backend/tests/test_quality_engine.py
git commit -m "feat: add quality engine for circular imports, complexity, and naming"
```

---

### Task 4: Wire quality report into `/analyze`

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: `analyze_quality` (Task 3); `QualityReport` (Task 2).
- Produces: `POST /analyze`'s JSON response gains a `quality` field alongside the
  existing `stack` and `graph` fields.

- [ ] **Step 1: Update the failing tests**

In `backend/tests/test_api.py`, add the import and update the two existing tests
that construct a full successful response (`test_analyze_returns_stack_and_graph`
and `test_analyze_skips_unparseable_file_and_continues`) to also assert on
`quality`, and add one new test:

Add near the top imports: `from app.quality_engine import analyze_quality` is NOT
needed in the test file — only add assertions. In the body of
`test_analyze_returns_stack_and_graph`, after the existing assertions, add:

```python
    assert "quality" in body
    assert "overall_score" in body["quality"]
```

In `test_analyze_skips_unparseable_file_and_continues`, after the existing
assertions, add the same two lines.

Add a new test:

```python
def test_analyze_quality_report_has_expected_shape(monkeypatch):
    fixture = FIXTURES / "fastapi_repo"

    @contextmanager
    def fake_clone(url, timeout=60):
        yield fixture

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    quality = resp.json()["quality"]
    assert set(quality.keys()) == {
        "overall_score",
        "maintainability_score",
        "architecture_score",
        "issues",
    }
    assert isinstance(quality["issues"], list)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: the two updated tests FAIL (response has no `quality` key yet — `main.py`
doesn't construct it), and the new test FAILS with the same cause.

- [ ] **Step 3: Wire the quality engine into the endpoint**

In `backend/app/main.py`, add the import:

```python
from .quality_engine import analyze_quality
```

(add it alongside the existing `from .graph_builder import build_graph, to_node_link`
line, keep all other existing imports as-is).

Update the `analyze` function's return statement — find this existing line:

```python
            return AnalyzeResponse(stack=stack, graph=GraphResponse(**to_node_link(graph)))
```

Replace it with:

```python
            quality = analyze_quality(files, graph)
            return AnalyzeResponse(
                stack=stack,
                graph=GraphResponse(**to_node_link(graph)),
                quality=quality,
            )
```

Keep everything else in `main.py` (the exception handling, `_iter_source_files`,
`_EXCLUDED_DIRS`, the file-parsing loop with its try/except guard) exactly as-is.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: all tests pass.

Run the full fast suite: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all tests pass, pristine output.

- [ ] **Step 5: Update backend README with the quality field**

In `backend/README.md`, find the "Try it" section's curl example response
description (if none exists, skip silently — just add a one-line note after the
"Try it" code block). Add this paragraph after the existing curl example:

```markdown
The response now also includes a `quality` field: `overall_score`,
`maintainability_score`, `architecture_score`, and a list of `issues` (circular
imports, long functions, high-complexity functions, naming violations).
```

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/main.py backend/tests/test_api.py backend/README.md
git commit -m "feat: wire quality report into /analyze response"
```

---

## After this plan

Phase 2 delivers deterministic code-quality signals reusing Phase 1's parsing and
graph infrastructure. Explicitly deferred: duplicate-code detection, dead-code
detection, and the Testing/Security/Documentation score categories — each is its own
future phase once the underlying subsystem (test detection, security scanning, doc
coverage) exists to back a real score.
