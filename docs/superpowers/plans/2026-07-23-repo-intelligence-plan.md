# Atlas Phase 1: Repository Intelligence + Architecture Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a stateless FastAPI service that, given a public GitHub repo URL, clones it, detects its tech stack, and builds a module/import/route architecture graph, returning both as JSON from `POST /analyze`.

**Architecture:** A pipeline of independently-testable pure-ish components — `cloner` (shallow git clone into temp dir) → `stack_detector` (heuristic manifest scanning) → `code_parser` (Tree-sitter symbol extraction per file) → `graph_builder` (NetworkX graph from parsed symbols) — orchestrated by a single FastAPI endpoint in `main.py`. No database; every request re-clones and re-analyzes.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, Pydantic v2, `tree-sitter` + `tree-sitter-languages` (Python/JS/TS/TSX grammars), NetworkX, pytest, httpx (for FastAPI TestClient).

## Global Constraints

- Python 3.11+ only; all code lives under `backend/`.
- Stateless: no database, no persistence layer. Every `/analyze` call clones and discards.
- Deep parsing (imports/defs/routes) only for `.py`, `.js`, `.jsx`, `.ts`, `.tsx`. Other files get no symbol extraction.
- Only public GitHub URLs are supported; clone via `git clone --depth 1`, no auth.
- No UI/frontend in this phase.
- No live-network calls in the default test run — any test that hits real GitHub must be marked `@pytest.mark.slow` and the fast suite must pass without network access.
- Exclude `.git`, `node_modules`, `venv`, `.venv`, `__pycache__`, `dist`, `build` directories from all file walks.

---

### Task 1: Backend scaffolding + health endpoint

**Files:**
- Create: `backend/requirements.txt`
- Create: `backend/pytest.ini`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/tests/test_health.py`
- Create: `atlas/.gitignore` (repo root, i.e. `C:\Users\jerry\atlas\.gitignore`)

**Interfaces:**
- Produces: `app.main.app` — the FastAPI application instance, importable as `from app.main import app`. Later tasks modify this same file to add `/analyze`.

- [ ] **Step 1: Create the backend directory structure and dependency list**

Create `backend/requirements.txt`:

```
fastapi>=0.110,<1.0
uvicorn[standard]>=0.29,<1.0
pydantic>=2.5,<3.0
tree-sitter==0.21.3
tree-sitter-languages>=1.10.2,<2.0
networkx>=3.1,<4.0
pytest>=8.0,<9.0
httpx>=0.27,<1.0
```

- [ ] **Step 2: Create pytest config**

Create `backend/pytest.ini`:

```ini
[pytest]
pythonpath = .
markers =
    slow: marks tests that hit the real network (deselect with '-m "not slow"')
```

- [ ] **Step 3: Create `.gitignore` at the repo root**

Create `atlas/.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
node_modules/
dist/
build/
```

- [ ] **Step 4: Create the venv and install dependencies**

Run from `backend/`:

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip
.venv/Scripts/python -m pip install -r requirements.txt
```

Expected: all packages install without error. If `tree-sitter-languages` fails to find a
wheel for the local Python version, note the exact error — this is the one dependency
most likely to need a version adjustment, and later tasks depend on it working.

- [ ] **Step 5: Write the app package init and a minimal FastAPI app**

Create `backend/app/__init__.py` (empty file).

Create `backend/app/main.py`:

```python
from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="Atlas Repository Intelligence")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 6: Write the failing test**

Create `backend/tests/test_health.py`:

```python
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_health.py -v`
Expected: `test_health_returns_ok PASSED`

- [ ] **Step 8: Commit**

```bash
cd ~/atlas
git add backend/requirements.txt backend/pytest.ini backend/app/__init__.py backend/app/main.py backend/tests/test_health.py .gitignore
git commit -m "feat: scaffold FastAPI backend with health endpoint"
```

---

### Task 2: Pydantic response/request models

**Files:**
- Create: `backend/app/models.py`
- Create: `backend/tests/test_models.py`

**Interfaces:**
- Produces:
  - `StackReport(backend: str|None, frontend: str|None, database: str|None, auth: str|None, deployment: str|None, architecture: str|None)`
  - `GraphNode(id: str, type: str)`
  - `GraphEdge(source: str, target: str, type: str)`
  - `GraphResponse(nodes: list[GraphNode], edges: list[GraphEdge])`
  - `AnalyzeRequest(repo_url: str)`
  - `AnalyzeResponse(stack: StackReport, graph: GraphResponse)`
- Consumes: nothing (pure Pydantic models, no dependency on other app modules).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_models.py`:

```python
from app.models import AnalyzeRequest, GraphEdge, GraphNode, GraphResponse, StackReport


def test_stack_report_defaults_to_none():
    report = StackReport()
    assert report.backend is None
    assert report.database is None


def test_analyze_request_requires_repo_url():
    request = AnalyzeRequest(repo_url="https://github.com/example/example")
    assert request.repo_url == "https://github.com/example/example"


def test_graph_response_serializes_nodes_and_edges():
    graph = GraphResponse(
        nodes=[GraphNode(id="a.py", type="module")],
        edges=[GraphEdge(source="a.py", target="b.py", type="import")],
    )
    data = graph.model_dump()
    assert data["nodes"][0]["id"] == "a.py"
    assert data["edges"][0]["type"] == "import"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.models'`

- [ ] **Step 3: Implement the models**

Create `backend/app/models.py`:

```python
from __future__ import annotations

from pydantic import BaseModel


class StackReport(BaseModel):
    backend: str | None = None
    frontend: str | None = None
    database: str | None = None
    auth: str | None = None
    deployment: str | None = None
    architecture: str | None = None


class GraphNode(BaseModel):
    id: str
    type: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class AnalyzeRequest(BaseModel):
    repo_url: str


class AnalyzeResponse(BaseModel):
    stack: StackReport
    graph: GraphResponse
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add Pydantic models for stack report and graph response"
```

---

### Task 3: Stack detector

**Files:**
- Create: `backend/app/stack_detector.py`
- Create: `backend/tests/fixtures/fastapi_repo/requirements.txt`
- Create: `backend/tests/fixtures/fastapi_repo/Dockerfile`
- Create: `backend/tests/fixtures/fastapi_repo/app/main.py`
- Create: `backend/tests/fixtures/react_vite_repo/package.json`
- Create: `backend/tests/fixtures/react_vite_repo/src/App.jsx`
- Create: `backend/tests/fixtures/empty_repo/README.md`
- Create: `backend/tests/test_stack_detector.py`

**Interfaces:**
- Consumes: `app.models.StackReport` (Task 2).
- Produces: `detect(repo_path: Path) -> StackReport`, importable as `from app.stack_detector import detect`.

- [ ] **Step 1: Create fixture repos**

Create `backend/tests/fixtures/fastapi_repo/requirements.txt`:

```
fastapi
uvicorn
```

Create `backend/tests/fixtures/fastapi_repo/Dockerfile`:

```
FROM python:3.11-slim
```

Create `backend/tests/fixtures/fastapi_repo/app/main.py`:

```python
from fastapi import FastAPI

app = FastAPI()


@app.get("/users")
def list_users():
    return []


@app.post("/users")
def create_user():
    return {}
```

Create `backend/tests/fixtures/react_vite_repo/package.json`:

```json
{
  "name": "example",
  "dependencies": {
    "react": "^18.2.0"
  },
  "devDependencies": {
    "vite": "^5.0.0"
  }
}
```

Create `backend/tests/fixtures/react_vite_repo/src/App.jsx`:

```jsx
import React from "react";

function App() {
  return <div>Hello</div>;
}

export default App;
```

Create `backend/tests/fixtures/empty_repo/README.md`:

```
# empty
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_stack_detector.py`:

```python
from pathlib import Path

from app.stack_detector import detect

FIXTURES = Path(__file__).parent / "fixtures"


def test_detects_fastapi_backend_and_docker_deployment():
    report = detect(FIXTURES / "fastapi_repo")
    assert report.backend == "FastAPI"
    assert report.deployment == "Docker"


def test_detects_react_vite_frontend():
    report = detect(FIXTURES / "react_vite_repo")
    assert report.frontend == "React + Vite"


def test_empty_repo_returns_unknown_stack():
    report = detect(FIXTURES / "empty_repo")
    assert report.backend is None
    assert report.frontend is None
    assert report.deployment is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_stack_detector.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.stack_detector'`

- [ ] **Step 4: Implement the detector**

Create `backend/app/stack_detector.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from .models import StackReport

_BACKEND_MARKERS = {
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "express": "Express",
}

_FRONTEND_MARKERS = {
    "next": "Next.js",
    "vue": "Vue",
    "svelte": "Svelte",
}

_DB_MARKERS = {
    "psycopg2": "PostgreSQL",
    "asyncpg": "PostgreSQL",
    "postgres": "PostgreSQL",
    "pymongo": "MongoDB",
    "mongoose": "MongoDB",
    "sqlite3": "SQLite",
}

_AUTH_MARKERS = {
    "pyjwt": "JWT",
    "jsonwebtoken": "JWT",
    "python-jose": "JWT",
}


def _read_text_files(repo_path: Path, names: list[str]) -> str:
    combined = ""
    for name in names:
        f = repo_path / name
        if f.exists():
            combined += f.read_text(errors="ignore").lower() + "\n"
    return combined


def _package_json(repo_path: Path) -> dict:
    f = repo_path / "package.json"
    if not f.exists():
        return {}
    try:
        return json.loads(f.read_text(errors="ignore"))
    except json.JSONDecodeError:
        return {}


def detect(repo_path: Path) -> StackReport:
    py_manifest = _read_text_files(repo_path, ["requirements.txt", "pyproject.toml"])
    pkg = _package_json(repo_path)
    pkg_deps = " ".join(
        list(pkg.get("dependencies", {}).keys()) + list(pkg.get("devDependencies", {}).keys())
    ).lower()

    backend = None
    for marker, name in _BACKEND_MARKERS.items():
        if marker in py_manifest or marker in pkg_deps:
            backend = name
            break

    frontend = None
    if "react" in pkg_deps:
        frontend = "React + Vite" if "vite" in pkg_deps else "React"
    else:
        for marker, name in _FRONTEND_MARKERS.items():
            if marker in pkg_deps:
                frontend = name
                break

    combined = py_manifest + " " + pkg_deps
    database = next((name for marker, name in _DB_MARKERS.items() if marker in combined), None)
    auth = next((name for marker, name in _AUTH_MARKERS.items() if marker in combined), None)

    deployment = None
    if (repo_path / "Dockerfile").exists():
        deployment = "Docker"
    if (repo_path / "docker-compose.yml").exists() or (repo_path / "docker-compose.yaml").exists():
        deployment = "Docker Compose"

    architecture = None
    known_dirs = {p.name for p in repo_path.iterdir() if p.is_dir()}
    if {"routers", "services", "models"} & known_dirs:
        architecture = "Layered MVC"

    return StackReport(
        backend=backend,
        frontend=frontend,
        database=database,
        auth=auth,
        deployment=deployment,
        architecture=architecture,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_stack_detector.py -v`
Expected: 3 passed

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/stack_detector.py backend/tests/fixtures backend/tests/test_stack_detector.py
git commit -m "feat: add heuristic stack detector"
```

---

### Task 4: Cloner

**Files:**
- Create: `backend/app/cloner.py`
- Create: `backend/tests/test_cloner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `class CloneError(Exception)`, `class InvalidRepoUrlError(CloneError)`
  - `validate_github_url(url: str) -> None` (raises `InvalidRepoUrlError` if invalid)
  - `_clone_to(source: str, dest: str, timeout: int) -> None` (raises `CloneError` on failure) — internal, used directly by tests to avoid network
  - `shallow_clone(url: str, timeout: int = 60)` — context manager yielding a `pathlib.Path` to the cloned repo, cleans up on exit. Used by Task 7's `/analyze` endpoint.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_cloner.py`:

```python
import subprocess
from pathlib import Path

import pytest

from app.cloner import CloneError, InvalidRepoUrlError, _clone_to, shallow_clone, validate_github_url


def test_validate_github_url_accepts_valid_url():
    validate_github_url("https://github.com/octocat/Hello-World")


def test_validate_github_url_rejects_invalid():
    with pytest.raises(InvalidRepoUrlError):
        validate_github_url("not-a-url")


def test_clone_to_local_repo(tmp_path):
    source = tmp_path / "source_repo"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    (source / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=source,
        check=True,
        capture_output=True,
    )

    dest = tmp_path / "dest_repo"
    _clone_to(str(source), str(dest), timeout=30)

    assert (dest / "file.txt").exists()


def test_clone_to_raises_on_missing_source(tmp_path):
    dest = tmp_path / "dest_repo"
    with pytest.raises(CloneError):
        _clone_to(str(tmp_path / "does_not_exist"), str(dest), timeout=30)


def test_shallow_clone_cleans_up_temp_dir(monkeypatch, tmp_path):
    captured = {}

    def fake_clone_to(source, dest, timeout):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "marker.txt").write_text("ok")
        captured["dest"] = dest

    monkeypatch.setattr("app.cloner._clone_to", fake_clone_to)

    with shallow_clone("https://github.com/octocat/Hello-World") as repo_path:
        assert (repo_path / "marker.txt").exists()

    assert not Path(captured["dest"]).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_cloner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cloner'`

- [ ] **Step 3: Implement the cloner**

Create `backend/app/cloner.py`:

```python
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

_GITHUB_URL_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?$")


class CloneError(Exception):
    pass


class InvalidRepoUrlError(CloneError):
    pass


def validate_github_url(url: str) -> None:
    if not _GITHUB_URL_RE.match(url.strip()):
        raise InvalidRepoUrlError(f"Not a valid GitHub repository URL: {url}")


def _clone_to(source: str, dest: str, timeout: int) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", source, dest],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise CloneError(result.stderr.strip() or "git clone failed")


@contextmanager
def shallow_clone(url: str, timeout: int = 60):
    validate_github_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="atlas-clone-")
    try:
        _clone_to(url, tmp_dir, timeout)
        yield Path(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_cloner.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/cloner.py backend/tests/test_cloner.py
git commit -m "feat: add shallow git clone helper with URL validation and cleanup"
```

---

### Task 5: Code parser (Tree-sitter)

**Files:**
- Create: `backend/app/code_parser.py`
- Create: `backend/tests/fixtures/python_symbols/sample.py`
- Create: `backend/tests/fixtures/js_symbols/sample.js`
- Create: `backend/tests/test_code_parser.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces:
  - `@dataclass FileSymbols(path: str, language: str, imports: list[str], defined: list[str], routes: list[tuple[str, str]])`
  - `language_for(path: Path) -> str | None`
  - `parse_file(path: Path) -> FileSymbols | None` (returns `None` for unsupported extensions)
  - Used by Task 6 (`graph_builder`) and Task 7 (`/analyze` endpoint).

- [ ] **Step 1: Create fixture source files**

Create `backend/tests/fixtures/python_symbols/sample.py`:

```python
import os
from fastapi import FastAPI

app = FastAPI()


@app.get("/items")
def list_items():
    return []


class ItemService:
    def get(self):
        return None
```

Create `backend/tests/fixtures/js_symbols/sample.js`:

```javascript
import express from "express";

const router = express.Router();

router.get("/items", (req, res) => {
  res.json([]);
});

function helper() {
  return true;
}

class ItemService {
  get() {
    return null;
  }
}

export default router;
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_code_parser.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_code_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.code_parser'`

- [ ] **Step 4: Implement the parser**

Create `backend/app/code_parser.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_code_parser.py -v`
Expected: 3 passed

If `tree_sitter_languages.get_parser` raises an error for a language, check the
installed `tree-sitter-languages` version against `tree-sitter` — they must be a
compatible pair (see Task 1 Step 4 note).

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/code_parser.py backend/tests/fixtures/python_symbols backend/tests/fixtures/js_symbols backend/tests/test_code_parser.py
git commit -m "feat: add Tree-sitter based code parser for Python and JS/TS"
```

---

### Task 6: Graph builder

**Files:**
- Create: `backend/app/graph_builder.py`
- Create: `backend/tests/test_graph_builder.py`

**Interfaces:**
- Consumes: `app.code_parser.FileSymbols` (Task 5).
- Produces:
  - `build_graph(files: list[FileSymbols]) -> networkx.DiGraph`
  - `to_node_link(graph: networkx.DiGraph) -> dict` with shape `{"nodes": [{"id": str, "type": str}], "edges": [{"source": str, "target": str, "type": str}]}`
  - Used by Task 7's `/analyze` endpoint.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_graph_builder.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_graph_builder.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.graph_builder'`

- [ ] **Step 3: Implement the graph builder**

Create `backend/app/graph_builder.py`:

```python
from __future__ import annotations

import re

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
        if f.path.endswith(module_as_path + ".py"):
            return f.path
        if f.path.endswith(module_as_path + ".js") or f.path.endswith(module_as_path + ".ts"):
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_graph_builder.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/graph_builder.py backend/tests/test_graph_builder.py
git commit -m "feat: add NetworkX graph builder for modules, imports, and routes"
```

---

### Task 7: Wire up `/analyze` endpoint

**Files:**
- Modify: `backend/app/main.py`
- Create: `backend/tests/test_api.py`

**Interfaces:**
- Consumes: `shallow_clone`, `CloneError`, `InvalidRepoUrlError` (Task 4); `parse_file` (Task 5); `build_graph`, `to_node_link` (Task 6); `AnalyzeRequest`, `AnalyzeResponse`, `GraphResponse` (Task 2); `detect` (Task 3).
- Produces: `POST /analyze` endpoint on the existing `app.main.app` FastAPI instance.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_api.py`:

```python
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures"


def test_analyze_rejects_invalid_url():
    resp = client.post("/analyze", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400


def test_analyze_returns_stack_and_graph(monkeypatch):
    fixture = FIXTURES / "fastapi_repo"

    @contextmanager
    def fake_clone(url, timeout=60):
        yield fixture

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stack"]["backend"] == "FastAPI"
    assert body["stack"]["deployment"] == "Docker"
    assert len(body["graph"]["nodes"]) > 0


def test_analyze_returns_422_on_clone_failure(monkeypatch):
    from app.cloner import CloneError

    @contextmanager
    def failing_clone(url, timeout=60):
        raise CloneError("repository not found")
        yield  # pragma: no cover

    monkeypatch.setattr("app.main.shallow_clone", failing_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/does-not-exist"})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: FAIL — `/analyze` returns 404 (route doesn't exist yet)

- [ ] **Step 3: Implement the endpoint**

Replace the contents of `backend/app/main.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .cloner import CloneError, InvalidRepoUrlError, shallow_clone
from .code_parser import parse_file
from .graph_builder import build_graph, to_node_link
from .models import AnalyzeRequest, AnalyzeResponse, GraphResponse
from .stack_detector import detect

app = FastAPI(title="Atlas Repository Intelligence")

_EXCLUDED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _iter_source_files(repo_path: Path):
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        yield path


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        with shallow_clone(request.repo_url) as repo_path:
            stack = detect(repo_path)
            files = [
                symbols
                for path in _iter_source_files(repo_path)
                if (symbols := parse_file(path)) is not None
            ]
            graph = build_graph(files)
            return AnalyzeResponse(stack=stack, graph=GraphResponse(**to_node_link(graph)))
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all tests pass (health, models, stack_detector, cloner, code_parser, graph_builder, api)

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/main.py backend/tests/test_api.py
git commit -m "feat: wire up POST /analyze endpoint with clone/detect/parse/graph pipeline"
```

---

### Task 8: Real-network integration test

**Files:**
- Create: `backend/tests/test_api_integration.py`

**Interfaces:**
- Consumes: `app.main.app` (Task 7). No new interfaces produced — this task only adds test coverage.

- [ ] **Step 1: Write the integration test**

Create `backend/tests/test_api_integration.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.slow
def test_analyze_real_public_repo_end_to_end():
    resp = client.post(
        "/analyze",
        json={"repo_url": "https://github.com/octocat/Hello-World"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "stack" in body
    assert "graph" in body
    assert isinstance(body["graph"]["nodes"], list)
```

- [ ] **Step 2: Run it to verify it passes (requires network)**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api_integration.py -v -m slow`
Expected: `test_analyze_real_public_repo_end_to_end PASSED`

- [ ] **Step 3: Run the full fast suite to confirm the slow test is excluded by default**

Run: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all non-slow tests pass, `test_api_integration.py` shows as deselected

- [ ] **Step 4: Commit**

```bash
cd ~/atlas
git add backend/tests/test_api_integration.py
git commit -m "test: add real-network integration test for /analyze, marked slow"
```

---

### Task 9: README and quickstart docs

**Files:**
- Create: `README.md` (repo root, i.e. `C:\Users\jerry\atlas\README.md`)
- Create: `backend/README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Write the repo root README**

Create `README.md`:

```markdown
# Atlas

AI Engineering Intelligence Platform — paste a GitHub repo, get a full engineering
review instead of a chatbot.

Atlas is being built in phases. Phase 1 (this repo's current state) is **Repository
Intelligence + Architecture Graph**: given a public GitHub URL, Atlas clones it,
detects its tech stack, and builds a module/import/route dependency graph, served as
JSON from a FastAPI backend.

See `docs/superpowers/specs/` for design docs and `docs/superpowers/plans/` for
implementation plans.

## Phase 1: Repository Intelligence

See [`backend/README.md`](backend/README.md) to run it locally.

## Roadmap

Later phases (not yet built): Code Quality Engine, AI Architect, Security Scanner,
Technical Debt Analyzer, Documentation Generator, Git Intelligence, Performance
Analyzer, AI Mentor, and a frontend UI.
```

- [ ] **Step 2: Write the backend quickstart README**

Create `backend/README.md`:

```markdown
# Atlas Backend (Phase 1: Repository Intelligence)

## Setup

\`\`\`bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
\`\`\`

## Run

\`\`\`bash
.venv/Scripts/python -m uvicorn app.main:app --reload
\`\`\`

## Try it

\`\`\`bash
curl -X POST http://127.0.0.1:8000/analyze \\
  -H "Content-Type: application/json" \\
  -d "{\"repo_url\": \"https://github.com/octocat/Hello-World\"}"
\`\`\`

## Test

\`\`\`bash
# fast suite (no network)
.venv/Scripts/python -m pytest tests/ -m "not slow"

# full suite including real-network integration test
.venv/Scripts/python -m pytest tests/
\`\`\`
```

- [ ] **Step 3: Commit**

```bash
cd ~/atlas
git add README.md backend/README.md
git commit -m "docs: add root and backend README with quickstart instructions"
```

---

## After this plan

Phase 1 delivers a working, testable `/analyze` API. The next phase (not part of this
plan) is expected to be either a minimal frontend viewer for the stack report + graph,
or the Code Quality Engine consuming this phase's parsed symbols — to be brainstormed
separately once this phase is merged.
