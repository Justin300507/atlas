# Atlas Phase 4: Documentation Generator (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /documentation`, returning a Markdown report assembled purely
from data Phases 1-3 already compute (stack, module/import/route graph, quality,
git intelligence) — no new parsing, no LLM call.

**Architecture:** `doc_generator.generate_documentation(repo_root, stack, files,
graph, quality, git_report) -> str` is a pure function producing seven Markdown
sections. `main.py`'s new endpoint runs the existing `/analyze` pipeline (via
`shallow_clone`) and the existing `/git-intelligence` pipeline (via
`clone_with_history`) back to back, then feeds both results into
`generate_documentation`.

**Tech Stack:** No new dependencies.

## Global Constraints

- Python 3.11+, all code under `backend/`. Stateless: no database.
- No live-network calls in the default (`not slow`) test run.
- Reuse `shallow_clone`, `clone_with_history`, `detect`, `parse_file`, `build_graph`,
  `analyze_quality`, `parse_git_log`, `analyze_git_history`, and the existing
  `_iter_source_files`/`_GIT_HISTORY_COMMITS` from `main.py` exactly as they are —
  this phase adds a consumer, it does not modify any of Phases 1-3's engines.
- `FileSymbols.path` stays an absolute path everywhere it already is (Phase 1
  behavior, unchanged) — `doc_generator.py` is the only place that relativizes paths,
  and only for display, using a `repo_root: Path` parameter passed in for that
  purpose.
- Markdown only. No new dependency for templating or diagram rendering.

---

### Task 1: `doc_generator.py` — pure Markdown report generator

**Files:**
- Create: `backend/app/doc_generator.py`
- Create: `backend/tests/test_doc_generator.py`

**Interfaces:**
- Consumes: `app.models.StackReport`, `QualityReport`, `GitIntelligenceReport`;
  `app.code_parser.FileSymbols`; `networkx.DiGraph` (as produced by
  `graph_builder.build_graph`).
- Produces: `generate_documentation(repo_root: Path, stack: StackReport,
  files: list[FileSymbols], graph: nx.DiGraph, quality: QualityReport,
  git_report: GitIntelligenceReport) -> str`. Used by Task 3 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_doc_generator.py`:

```python
from pathlib import Path

import networkx as nx

from app.code_parser import FileSymbols
from app.doc_generator import generate_documentation
from app.models import (
    FileChurn,
    GitIntelligenceReport,
    QualityIssue,
    QualityReport,
    StackReport,
)

REPO_ROOT = Path("/repo")


def _file(rel_path: str, **kwargs) -> FileSymbols:
    return FileSymbols(path=str(REPO_ROOT / rel_path), language="python", **kwargs)


def _empty_quality() -> QualityReport:
    return QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[])


def _empty_git() -> GitIntelligenceReport:
    return GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )


def test_executive_summary_reports_stack_and_scores():
    stack = StackReport(backend="FastAPI", database="PostgreSQL")
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, stack, files, graph, _empty_quality(), _empty_git())

    assert "## Executive Summary" in doc
    assert "FastAPI" in doc
    assert "PostgreSQL" in doc
    assert "Files analyzed: 1" in doc
    assert "100" in doc


def test_api_reference_lists_routes_with_relative_paths():
    files = [_file("app/main.py", routes=[("GET", "/users"), ("POST", "/users")])]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_git())

    assert "## API Reference" in doc
    assert "GET" in doc and "/users" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_directory_guide_groups_by_top_level_directory():
    files = [_file("app/main.py"), _file("app/utils.py"), _file("scripts/run.py")]
    graph = nx.DiGraph()

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_git())

    assert "## Directory Guide" in doc
    assert "app" in doc
    assert "scripts" in doc


def test_architecture_overview_ranks_most_depended_upon_module():
    a = str(REPO_ROOT / "a.py")
    b = str(REPO_ROOT / "b.py")
    c = str(REPO_ROOT / "c.py")
    graph = nx.DiGraph()
    for n in (a, b, c):
        graph.add_node(n, type="module")
    graph.add_edge(a, c, type="import")
    graph.add_edge(b, c, type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_git())

    assert "## Architecture Overview" in doc
    assert "c.py" in doc


def test_risk_areas_lists_quality_issues_with_relative_paths():
    quality = QualityReport(
        overall_score=90,
        maintainability_score=85,
        architecture_score=95,
        issues=[
            QualityIssue(
                file=str(REPO_ROOT / "app/main.py"),
                line=10,
                kind="long_function",
                message="Function 'run' is 60 lines",
                severity="minor",
            )
        ],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_git())

    assert "## Risk Areas" in doc
    assert "long_function" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_high_churn_section_lists_top_files_and_truncation_state():
    git_report = GitIntelligenceReport(
        commits_analyzed=500,
        history_truncated=True,
        churn=[FileChurn(file="app/main.py", commit_count=12, bug_fix_count=3)],
        ownership=[],
        co_changes=[],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), git_report)

    assert "## Recent High-Churn Components" in doc
    assert "app/main.py" in doc
    assert "12" in doc
    assert "truncated" in doc.lower()


def test_dependency_diagram_caps_at_40_nodes_with_note():
    graph = nx.DiGraph()
    for i in range(45):
        graph.add_node(str(REPO_ROOT / f"mod_{i}.py"), type="module")
    for i in range(44):
        graph.add_edge(str(REPO_ROOT / f"mod_{i}.py"), str(REPO_ROOT / f"mod_{i + 1}.py"), type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_git())

    assert "## Dependency Diagram" in doc
    assert "```mermaid" in doc
    assert "capped for readability" in doc


def test_empty_repo_renders_without_crashing():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_git()
    )

    for header in (
        "## Executive Summary",
        "## Architecture Overview",
        "## Directory Guide",
        "## API Reference",
        "## Dependency Diagram",
        "## Risk Areas",
        "## Recent High-Churn Components",
    ):
        assert header in doc
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_doc_generator.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.doc_generator'`.

- [ ] **Step 3: Implement**

Create `backend/app/doc_generator.py`:

```python
from __future__ import annotations

from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols
from .models import GitIntelligenceReport, QualityReport, StackReport

_DIAGRAM_NODE_CAP = 40
_HIGH_CHURN_LIMIT = 10
_SEVERITY_ORDER = {"critical": 0, "important": 1, "minor": 2}


def generate_documentation(
    repo_root: Path,
    stack: StackReport,
    files: list[FileSymbols],
    graph: nx.DiGraph,
    quality: QualityReport,
    git_report: GitIntelligenceReport,
) -> str:
    sections = [
        _executive_summary(stack, files, quality, git_report),
        _architecture_overview(graph),
        _directory_guide(repo_root, files),
        _api_reference(repo_root, files),
        _dependency_diagram(graph),
        _risk_areas(repo_root, quality),
        _high_churn_components(git_report),
    ]
    return "\n\n".join(sections) + "\n"


def _relative(repo_root: Path, path: str) -> str:
    try:
        return PurePath(Path(path).relative_to(repo_root)).as_posix()
    except ValueError:
        return PurePath(path).as_posix()


def _executive_summary(
    stack: StackReport, files: list[FileSymbols], quality: QualityReport, git_report: GitIntelligenceReport
) -> str:
    lines = ["## Executive Summary", ""]
    for label, value in [
        ("Backend", stack.backend),
        ("Frontend", stack.frontend),
        ("Database", stack.database),
        ("Auth", stack.auth),
        ("Deployment", stack.deployment),
        ("Architecture", stack.architecture),
    ]:
        lines.append(f"- {label}: {value or 'Not detected'}")
    lines.append(f"- Files analyzed: {len(files)}")
    lines.append(
        f"- Overall quality score: {quality.overall_score}/100 "
        f"(maintainability {quality.maintainability_score}, architecture {quality.architecture_score})"
    )
    truncation_note = " (history truncated)" if git_report.history_truncated else ""
    lines.append(f"- Commits analyzed: {git_report.commits_analyzed}{truncation_note}")
    return "\n".join(lines)


def _architecture_overview(graph: nx.DiGraph) -> str:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    route_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "route"]
    import_edges = [1 for _, _, d in graph.edges(data=True) if d.get("type") == "import"]

    lines = [
        "## Architecture Overview",
        "",
        f"- Modules: {len(module_nodes)}",
        f"- Import edges: {len(import_edges)}",
        f"- Routes: {len(route_nodes)}",
    ]

    if module_nodes:
        by_in_degree = sorted(
            module_nodes, key=lambda n: (-graph.in_degree(n), n)
        )[:10]
        top = [(n, graph.in_degree(n)) for n in by_in_degree if graph.in_degree(n) > 0]
        if top:
            lines.append("")
            lines.append("Most depended-upon modules:")
            for path, count in top:
                lines.append(f"- {PurePath(path).name} ({count} importers)")

    return "\n".join(lines)


def _directory_guide(repo_root: Path, files: list[FileSymbols]) -> str:
    counts: dict[str, int] = {}
    for f in files:
        rel = _relative(repo_root, f.path)
        parts = rel.split("/")
        top_dir = parts[0] if len(parts) > 1 else "."
        counts[top_dir] = counts.get(top_dir, 0) + 1

    lines = ["## Directory Guide", ""]
    if not counts:
        lines.append("No files detected.")
        return "\n".join(lines)

    lines.append("| Directory | Files |")
    lines.append("|---|---|")
    for directory, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {directory} | {count} |")
    return "\n".join(lines)


def _api_reference(repo_root: Path, files: list[FileSymbols]) -> str:
    lines = ["## API Reference", ""]
    rows = [
        (method, path, _relative(repo_root, f.path))
        for f in files
        for method, path in f.routes
    ]
    if not rows:
        lines.append("No routes detected.")
        return "\n".join(lines)

    lines.append("| Method | Path | File |")
    lines.append("|---|---|---|")
    for method, path, file in sorted(rows, key=lambda r: (r[2], r[1])):
        lines.append(f"| {method} | {path} | {file} |")
    return "\n".join(lines)


def _dependency_diagram(graph: nx.DiGraph) -> str:
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    lines = ["## Dependency Diagram", ""]
    if not module_nodes:
        lines.append("No modules detected.")
        return "\n".join(lines)

    selected = sorted(module_nodes, key=lambda n: (-graph.degree(n), n))[:_DIAGRAM_NODE_CAP]
    selected_set = set(selected)
    node_ids = {n: f"n{i}" for i, n in enumerate(selected)}

    lines.append("```mermaid")
    lines.append("graph TD")
    for u, v, d in graph.edges(data=True):
        if d.get("type") == "import" and u in selected_set and v in selected_set:
            lines.append(
                f'    {node_ids[u]}["{PurePath(u).name}"] --> {node_ids[v]}["{PurePath(v).name}"]'
            )
    lines.append("```")

    if len(module_nodes) > _DIAGRAM_NODE_CAP:
        lines.append("")
        lines.append(
            f"_({len(selected)} of {len(module_nodes)} modules shown, capped for readability)_"
        )
    return "\n".join(lines)


def _risk_areas(repo_root: Path, quality: QualityReport) -> str:
    lines = ["## Risk Areas", ""]
    if not quality.issues:
        lines.append("No issues detected.")
        return "\n".join(lines)

    ordered = sorted(quality.issues, key=lambda i: _SEVERITY_ORDER.get(i.severity, 99))
    for issue in ordered:
        rel = _relative(repo_root, issue.file)
        lines.append(f"- **{issue.severity}** `{rel}:{issue.line}` {issue.kind}: {issue.message}")
    return "\n".join(lines)


def _high_churn_components(git_report: GitIntelligenceReport) -> str:
    lines = ["## Recent High-Churn Components", ""]
    top = git_report.churn[:_HIGH_CHURN_LIMIT]
    if not top:
        lines.append("No git history detected.")
        return "\n".join(lines)

    truncation_note = " (history truncated — repo has more commits than analyzed)" if git_report.history_truncated else ""
    lines.append(f"Analyzed {git_report.commits_analyzed} commits{truncation_note}.")
    lines.append("")
    lines.append("| File | Commits | Bug fixes |")
    lines.append("|---|---|---|")
    for churn in top:
        lines.append(f"| {churn.file} | {churn.commit_count} | {churn.bug_fix_count} |")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_doc_generator.py -v`
Expected: all 8 tests pass.

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/doc_generator.py backend/tests/test_doc_generator.py
git commit -m "feat: add deterministic Markdown documentation generator"
```

---

### Task 2: `DocumentationResponse` model

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add `DocumentationResponse` to the existing `from app.models import ...` line in
`test_models.py`, and add:

```python
def test_documentation_response_serializes_markdown():
    response = DocumentationResponse(markdown="## Executive Summary\n\nhello")
    assert "Executive Summary" in response.model_dump()["markdown"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement**

In `backend/app/models.py`, add (after `GitIntelligenceReport`, keep every existing
class as-is):

```python
class DocumentationResponse(BaseModel):
    markdown: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: all pass (pre-existing + 1 new).

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add DocumentationResponse model"
```

---

### Task 3: Wire `POST /documentation` into `main.py`

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/README.md`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_api.py`:

```python
def test_documentation_returns_markdown_report(tmp_path, monkeypatch):
    structure_fixture = FIXTURES / "fastapi_repo"

    history_repo = tmp_path / "history_repo"
    history_repo.mkdir()
    subprocess.run(["git", "init"], cwd=history_repo, check=True, capture_output=True)
    (history_repo / "a.py").write_text("1\n")
    subprocess.run(["git", "add", "a.py"], cwd=history_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=history_repo,
        check=True,
        capture_output=True,
    )

    @contextmanager
    def fake_shallow_clone(url, timeout=60):
        yield structure_fixture

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield history_repo

    monkeypatch.setattr("app.main.shallow_clone", fake_shallow_clone)
    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post("/documentation", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    markdown = resp.json()["markdown"]
    assert "## Executive Summary" in markdown
    assert "## API Reference" in markdown
    assert "/users" in markdown


def test_documentation_rejects_invalid_url():
    resp = client.post("/documentation", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v -k documentation`
Expected: FAIL — 404 (no route yet).

- [ ] **Step 3: Wire the endpoint**

In `backend/app/main.py`, add the import (extend the existing `.models` import line
and add a new one):

```python
from .doc_generator import generate_documentation
```

Add `DocumentationResponse` to the existing `from .models import ...` line.

Add the endpoint after `/git-intelligence`:

```python
@app.post("/documentation", response_model=DocumentationResponse)
def documentation(request: AnalyzeRequest) -> DocumentationResponse:
    try:
        with shallow_clone(request.repo_url) as repo_path:
            repo_root = repo_path
            stack = detect(repo_path)
            files = []
            for path in _iter_source_files(repo_path):
                try:
                    symbols = parse_file(path)
                except Exception:
                    continue
                if symbols is not None:
                    files.append(symbols)
            graph = build_graph(files)
            quality = analyze_quality(files, graph)

        with clone_with_history(request.repo_url, depth=_GIT_HISTORY_COMMITS + 1) as history_path:
            commits, history_truncated = parse_git_log(history_path, max_commits=_GIT_HISTORY_COMMITS)
            git_report = analyze_git_history(commits, history_truncated)

        markdown = generate_documentation(repo_root, stack, files, graph, quality, git_report)
        return DocumentationResponse(markdown=markdown)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

**Note:** `repo_root` is captured as a `Path` value before its `with` block exits;
`generate_documentation` only uses it for `Path.relative_to()` string arithmetic, not
filesystem access, so it stays valid after the temp directory backing it is cleaned
up — no different from any other Path object used after the file it pointed to is
gone.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: all pass (pre-existing + 2 new).

Run the full fast suite: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all pass, no regressions.

- [ ] **Step 5: Update backend README**

Add a `## Documentation Generator` section next to the existing endpoint docs,
describing `POST /documentation`, its Markdown response, and that it performs two
clones internally (structure + history) the same way `/analyze` and
`/git-intelligence` do independently.

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/main.py backend/tests/test_api.py backend/README.md
git commit -m "feat: add POST /documentation endpoint"
```

---

## After this plan

Phase 4 delivers a deterministic Markdown report consuming Phases 1-3's outputs with
no new parsing and no LLM call, completing the "cohesive v1" scope (Repository
Intelligence, Architecture Graph, Code Quality, Git Intelligence, Documentation
Generator) discussed on 2026-07-23. Explicitly deferred: Data Model section,
narrative Onboarding Guide (needs an AI Engine), HTML/PDF rendering, persistence, and
a frontend — plus everything already deferred from Phases 1-3 (Security Scanner, AI
Architect, Performance Analyzer, AI Mentor, duplicate/dead-code detection).
