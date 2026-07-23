# Atlas Phase 3: Git Intelligence (v1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /git-intelligence`, a new endpoint that clones a repo with bounded
commit history and reports file churn, bug-fix hotspots, ownership, and co-change
pairs — deterministic Git-history analysis, no LLM calls.

**Architecture:** `cloner.clone_with_history` (new, sibling to `shallow_clone`) clones
with `--depth <N>` instead of `--depth 1`. `git_log_parser.parse_git_log` shells out to
`git log --numstat` and returns `(list[Commit], history_truncated)`.
`git_intelligence.analyze_git_history` is a pure function turning that commit list into
a `GitIntelligenceReport`. `main.py` wires the three together behind the new endpoint.

**Tech Stack:** No new dependencies — `git` CLI via `subprocess`, already used in
`cloner.py`.

## Global Constraints

- Python 3.11+, all code under `backend/`. Stateless: no database.
- No live-network calls in the default (`not slow`) test run.
- `cloner.shallow_clone`'s behavior (`--depth 1`) must not change — Phase 1/2 depend
  on it staying fast and shallow. Add `clone_with_history` alongside it.
- `models.py`'s existing classes (`StackReport`, `GraphNode`, `GraphEdge`,
  `GraphResponse`, `QualityIssue`, `QualityReport`, `AnalyzeRequest`,
  `AnalyzeResponse`) are untouched — this phase only adds new classes.
- Result lists (`churn`, `ownership`, `co_changes`) are capped at top 20 after sorting.
  Implement exactly as specified — v1 heuristic, not tuned.

---

### Task 1: `cloner.clone_with_history`

**Files:**
- Modify: `backend/app/cloner.py`
- Modify: `backend/tests/test_cloner.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `clone_with_history(url: str, depth: int = 500, timeout: int = 120)`,
  a context manager yielding a `Path` to the cloned repo (same shape as
  `shallow_clone`). Used by Task 4 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_cloner.py`:

```python
from app.cloner import clone_with_history


def test_clone_with_history_preserves_multiple_commits(tmp_path):
    source = tmp_path / "source_repo"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    for i in range(3):
        (source / "file.txt").write_text(f"version {i}")
        subprocess.run(["git", "add", "file.txt"], cwd=source, check=True, capture_output=True)
        subprocess.run(
            ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", f"commit {i}"],
            cwd=source,
            check=True,
            capture_output=True,
        )

    with clone_with_history(str(source), depth=10) as repo_path:
        log = subprocess.run(
            ["git", "log", "--oneline"], cwd=repo_path, capture_output=True, text=True, check=True
        )
        assert len(log.stdout.strip().splitlines()) == 3


def test_clone_with_history_cleans_up_temp_dir(monkeypatch, tmp_path):
    captured = {}

    def fake_clone_history_to(source, dest, depth, timeout):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "marker.txt").write_text("ok")
        captured["dest"] = dest

    monkeypatch.setattr("app.cloner._clone_history_to", fake_clone_history_to)

    with clone_with_history("https://github.com/octocat/Hello-World") as repo_path:
        assert (repo_path / "marker.txt").exists()

    assert not Path(captured["dest"]).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_cloner.py -v`
Expected: FAIL — `ImportError: cannot import name 'clone_with_history'`.

- [ ] **Step 3: Implement**

In `backend/app/cloner.py`, factor the tempdir/cleanup pattern shared by both clone
functions into a helper, then add the history variant. Keep `shallow_clone` and
`_clone_to` exactly as they are; add this alongside them:

```python
def _clone_history_to(source: str, dest: str, depth: int, timeout: int) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", str(depth), source, dest],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise CloneError(result.stderr.strip() or "git clone failed")


@contextmanager
def clone_with_history(url: str, depth: int = 500, timeout: int = 120):
    validate_github_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="atlas-clone-history-")
    try:
        _clone_history_to(url, tmp_dir, depth, timeout)
        yield Path(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

(A shared tempdir/cleanup helper was considered but two nearly-identical 6-line
context managers is clearer than a helper with a callback parameter — don't add one
unless a third clone variant shows up.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_cloner.py -v`
Expected: all pass (pre-existing + 2 new).

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/cloner.py backend/tests/test_cloner.py
git commit -m "feat: add clone_with_history for bounded commit-history clones"
```

---

### Task 2: `git_log_parser` — parse `git log --numstat` into `Commit`/`FileChange`

**Files:**
- Create: `backend/app/git_log_parser.py`
- Create: `backend/tests/test_git_log_parser.py`

**Interfaces:**
- Consumes: nothing new (subprocess + a repo path).
- Produces:
  - `@dataclass FileChange(path: str, additions: int, deletions: int)`
  - `@dataclass Commit(hash: str, author_email: str, message: str, files: list[FileChange])`
  - `parse_git_log(repo_path: Path, max_commits: int = 500) -> tuple[list[Commit], bool]`
    (second element is `history_truncated`). Used by Task 4 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_git_log_parser.py`:

```python
import subprocess

import pytest

from app.git_log_parser import parse_git_log


def _init_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def _commit(path, message, author_email, files: dict[str, str]):
    for name, content in files.items():
        (path / name).write_text(content)
        subprocess.run(["git", "add", name], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", f"user.email={author_email}", "-c", "user.name=test", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    _init_repo(tmp_path)
    _commit(tmp_path, "add a and b", "alice@example.com", {"a.py": "1\n2\n", "b.py": "1\n"})
    _commit(tmp_path, "fix bug in a", "bob@example.com", {"a.py": "1\n2\n3\n"})
    _commit(tmp_path, "update b", "alice@example.com", {"b.py": "1\n2\n"})
    return tmp_path


def test_parse_git_log_returns_commits_in_order(repo):
    commits, truncated = parse_git_log(repo, max_commits=500)

    assert not truncated
    assert len(commits) == 3
    # git log defaults to newest-first
    assert commits[0].message == "update b"
    assert commits[1].message == "fix bug in a"
    assert commits[2].message == "add a and b"


def test_parse_git_log_extracts_author_and_files(repo):
    commits, _ = parse_git_log(repo, max_commits=500)

    first_commit = commits[-1]
    assert first_commit.author_email == "alice@example.com"
    paths = {f.path for f in first_commit.files}
    assert paths == {"a.py", "b.py"}
    a_change = next(f for f in first_commit.files if f.path == "a.py")
    assert a_change.additions == 2
    assert a_change.deletions == 0


def test_parse_git_log_reports_truncation(repo):
    commits, truncated = parse_git_log(repo, max_commits=2)

    assert len(commits) == 2
    assert truncated is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_git_log_parser.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.git_log_parser'`.

- [ ] **Step 3: Implement**

Create `backend/app/git_log_parser.py`:

```python
from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_COMMIT_MARKER = "@@ATLAS-COMMIT@@"
_FIELD_SEP = "@@ATLAS-FIELD@@"


@dataclass
class FileChange:
    path: str
    additions: int
    deletions: int


@dataclass
class Commit:
    hash: str
    author_email: str
    message: str
    files: list[FileChange] = field(default_factory=list)


def parse_git_log(repo_path: Path, max_commits: int = 500) -> tuple[list[Commit], bool]:
    result = subprocess.run(
        [
            "git",
            "log",
            f"-n{max_commits + 1}",
            "--numstat",
            f"--pretty=format:{_COMMIT_MARKER}%H{_FIELD_SEP}%ae{_FIELD_SEP}%s",
        ],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )

    commits = _parse_log_output(result.stdout)
    truncated = len(commits) > max_commits
    return commits[:max_commits], truncated


def _parse_log_output(output: str) -> list[Commit]:
    commits: list[Commit] = []
    current: Commit | None = None

    for line in output.splitlines():
        if line.startswith(_COMMIT_MARKER):
            commit_hash, author_email, message = line[len(_COMMIT_MARKER):].split(_FIELD_SEP, 2)
            current = Commit(hash=commit_hash, author_email=author_email, message=message)
            commits.append(current)
        elif line.strip() and current is not None:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added_raw, removed_raw, path = parts
            if added_raw == "-" or removed_raw == "-":
                continue  # binary file, numstat has no line counts
            try:
                current.files.append(
                    FileChange(path=path, additions=int(added_raw), deletions=int(removed_raw))
                )
            except ValueError:
                continue

    return commits
```

**Why `-n{max_commits + 1}` and the length comparison:** asking `git log` for one more
commit than the cap lets truncation be detected without a second `git rev-list --count`
subprocess call — if more than `max_commits` came back, there was at least one more
commit beyond the window.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_git_log_parser.py -v`
Expected: all 3 pass.

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/git_log_parser.py backend/tests/test_git_log_parser.py
git commit -m "feat: add git log parser for commit/file-change history"
```

---

### Task 3: `models.py` — add Git Intelligence response models

**Files:**
- Modify: `backend/app/models.py`
- Modify: `backend/tests/test_models.py`

**Interfaces:**
- Produces: `FileChurn`, `FileOwnership`, `CoChangePair`, `GitIntelligenceReport`
  (fields as specified in the design doc). Used by Task 4 (`git_intelligence.py`) and
  Task 5 (`main.py`).

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_models.py` (add `FileChurn, FileOwnership, CoChangePair,
GitIntelligenceReport` to the existing `from app.models import ...` line):

```python
def test_git_intelligence_report_serializes():
    report = GitIntelligenceReport(
        commits_analyzed=3,
        history_truncated=False,
        churn=[FileChurn(file="a.py", commit_count=2, bug_fix_count=1)],
        ownership=[
            FileOwnership(
                file="a.py",
                top_author="alice@example.com",
                top_author_commits=1,
                total_commits=2,
                ownership_ratio=0.5,
            )
        ],
        co_changes=[CoChangePair(file_a="a.py", file_b="b.py", co_change_count=1)],
    )
    data = report.model_dump()
    assert data["commits_analyzed"] == 3
    assert data["churn"][0]["bug_fix_count"] == 1
    assert data["co_changes"][0]["co_change_count"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 3: Implement the models**

In `backend/app/models.py`, add (keep every existing class exactly as-is; this task
does not touch `AnalyzeResponse` or any existing class):

```python
class FileChurn(BaseModel):
    file: str
    commit_count: int
    bug_fix_count: int


class FileOwnership(BaseModel):
    file: str
    top_author: str
    top_author_commits: int
    total_commits: int
    ownership_ratio: float


class CoChangePair(BaseModel):
    file_a: str
    file_b: str
    co_change_count: int


class GitIntelligenceReport(BaseModel):
    commits_analyzed: int
    history_truncated: bool
    churn: list[FileChurn]
    ownership: list[FileOwnership]
    co_changes: list[CoChangePair]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_models.py -v`
Expected: all pass (pre-existing + 1 new).

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/models.py backend/tests/test_models.py
git commit -m "feat: add git intelligence response models"
```

---

### Task 4: `git_intelligence.py` — churn, bug hotspots, ownership, co-change

**Files:**
- Create: `backend/app/git_intelligence.py`
- Create: `backend/tests/test_git_intelligence.py`

**Interfaces:**
- Consumes: `app.git_log_parser.Commit`/`FileChange` (Task 2);
  `app.models.FileChurn`, `FileOwnership`, `CoChangePair`, `GitIntelligenceReport`
  (Task 3).
- Produces: `analyze_git_history(commits: list[Commit], history_truncated: bool) -> GitIntelligenceReport`,
  importable as `from app.git_intelligence import analyze_git_history`. Used by
  Task 5 (`main.py`).

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_git_intelligence.py`:

```python
from app.git_intelligence import analyze_git_history
from app.git_log_parser import Commit, FileChange


def test_empty_history_produces_empty_report():
    report = analyze_git_history([], history_truncated=False)

    assert report.commits_analyzed == 0
    assert report.churn == []
    assert report.ownership == []
    assert report.co_changes == []


def test_churn_counts_commits_per_file_descending():
    commits = [
        Commit("h1", "a@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h2", "a@x.com", "msg", [FileChange("a.py", 1, 0), FileChange("b.py", 1, 0)]),
        Commit("h3", "a@x.com", "msg", [FileChange("b.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    by_file = {c.file: c for c in report.churn}
    assert by_file["a.py"].commit_count == 2
    assert by_file["b.py"].commit_count == 2
    assert report.churn[0].commit_count >= report.churn[1].commit_count


def test_bug_fix_commits_counted_per_file():
    commits = [
        Commit("h1", "a@x.com", "fix bug in parser", [FileChange("a.py", 1, 0)]),
        Commit("h2", "a@x.com", "add feature", [FileChange("a.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    assert report.churn[0].commit_count == 2
    assert report.churn[0].bug_fix_count == 1


def test_ownership_picks_majority_author():
    commits = [
        Commit("h1", "alice@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h2", "alice@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h3", "bob@x.com", "msg", [FileChange("a.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    owner = report.ownership[0]
    assert owner.file == "a.py"
    assert owner.top_author == "alice@x.com"
    assert owner.top_author_commits == 2
    assert owner.total_commits == 3
    assert owner.ownership_ratio == pytest.approx(2 / 3)


def test_co_change_counts_all_pairs_in_multi_file_commit():
    commits = [
        Commit(
            "h1",
            "a@x.com",
            "msg",
            [FileChange("a.py", 1, 0), FileChange("b.py", 1, 0), FileChange("c.py", 1, 0)],
        )
    ]

    report = analyze_git_history(commits, history_truncated=False)

    pairs = {(p.file_a, p.file_b) for p in report.co_changes}
    assert len(report.co_changes) == 3
    assert ("a.py", "b.py") in pairs or ("b.py", "a.py") in pairs


def test_history_truncated_flag_passed_through():
    report = analyze_git_history([], history_truncated=True)
    assert report.history_truncated is True


def test_results_capped_at_20():
    commits = [
        Commit(f"h{i}", "a@x.com", "msg", [FileChange(f"file{i}.py", 1, 0)]) for i in range(30)
    ]

    report = analyze_git_history(commits, history_truncated=False)

    assert len(report.churn) == 20
    assert len(report.ownership) == 20
```

(Add `import pytest` at the top of the test file for `pytest.approx`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_git_intelligence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.git_intelligence'`.

- [ ] **Step 3: Implement**

Create `backend/app/git_intelligence.py`:

```python
from __future__ import annotations

import re
from collections import defaultdict
from itertools import combinations

from .git_log_parser import Commit
from .models import CoChangePair, FileChurn, FileOwnership, GitIntelligenceReport

_TOP_N = 20
_BUG_FIX_PATTERN = re.compile(r"\b(fix|fixes|fixed|bug|hotfix|patch|bugfix)\b", re.IGNORECASE)


def analyze_git_history(commits: list[Commit], history_truncated: bool) -> GitIntelligenceReport:
    commit_counts: dict[str, int] = defaultdict(int)
    bug_fix_counts: dict[str, int] = defaultdict(int)
    author_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    co_change_counts: dict[tuple[str, str], int] = defaultdict(int)

    for commit in commits:
        is_bug_fix = bool(_BUG_FIX_PATTERN.search(commit.message))
        paths = [f.path for f in commit.files]

        for path in paths:
            commit_counts[path] += 1
            if is_bug_fix:
                bug_fix_counts[path] += 1
            author_counts[path][commit.author_email] += 1

        for path_a, path_b in combinations(sorted(set(paths)), 2):
            co_change_counts[(path_a, path_b)] += 1

    churn = sorted(
        (
            FileChurn(file=path, commit_count=count, bug_fix_count=bug_fix_counts.get(path, 0))
            for path, count in commit_counts.items()
        ),
        key=lambda c: c.commit_count,
        reverse=True,
    )[:_TOP_N]

    ownership = sorted(
        (
            FileOwnership(
                file=path,
                top_author=max(authors.items(), key=lambda kv: kv[1])[0],
                top_author_commits=max(authors.values()),
                total_commits=sum(authors.values()),
                ownership_ratio=max(authors.values()) / sum(authors.values()),
            )
            for path, authors in author_counts.items()
        ),
        key=lambda o: o.total_commits,
        reverse=True,
    )[:_TOP_N]

    co_changes = sorted(
        (
            CoChangePair(file_a=a, file_b=b, co_change_count=count)
            for (a, b), count in co_change_counts.items()
        ),
        key=lambda p: p.co_change_count,
        reverse=True,
    )[:_TOP_N]

    return GitIntelligenceReport(
        commits_analyzed=len(commits),
        history_truncated=history_truncated,
        churn=churn,
        ownership=ownership,
        co_changes=co_changes,
    )
```

**Note on ownership tie-breaking:** `max(authors.items(), key=lambda kv: kv[1])`
returns the first item with the max value in Python's stable dict-iteration order
(insertion order), so a tie goes to whichever qualifying author committed first — this
matches the design doc's "first author encountered" tie-break without extra code.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_git_intelligence.py -v`
Expected: all 7 pass.

Run the full fast suite to confirm no regression: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`

- [ ] **Step 5: Commit**

```bash
cd ~/atlas
git add backend/app/git_intelligence.py backend/tests/test_git_intelligence.py
git commit -m "feat: add git intelligence engine for churn, ownership, and co-change"
```

---

### Task 5: Wire `POST /git-intelligence` into `main.py`

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_api.py`
- Modify: `backend/README.md`

**Interfaces:**
- Consumes: `clone_with_history` (Task 1), `parse_git_log` (Task 2),
  `analyze_git_history` (Task 4), `GitIntelligenceReport` (Task 3),
  `AnalyzeRequest` (existing — reused as-is since both endpoints take just
  `{repo_url}`).
- Produces: `POST /git-intelligence` returning a `GitIntelligenceReport` JSON body.

- [ ] **Step 1: Write the failing tests**

Add to `backend/tests/test_api.py` (reuse the file's existing `FIXTURES`,
`contextmanager`, and `client` — check the top of the file for what's already
imported and add only what's missing, e.g. `from pathlib import Path` if not already
present):

```python
def test_git_intelligence_returns_expected_shape(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    (repo / "a.py").write_text("1\n")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post("/git-intelligence", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {
        "commits_analyzed",
        "history_truncated",
        "churn",
        "ownership",
        "co_changes",
    }
    assert body["commits_analyzed"] == 1
    assert body["churn"][0]["file"] == "a.py"


def test_git_intelligence_rejects_invalid_url():
    resp = client.post("/git-intelligence", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400
```

Add `import subprocess` at the top of `test_api.py` if it isn't already imported.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: FAIL — `404` (no `/git-intelligence` route yet).

- [ ] **Step 3: Wire the endpoint**

In `backend/app/main.py`, add imports (alongside the existing ones, keep all existing
imports exactly as-is):

```python
from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .models import AnalyzeRequest, AnalyzeResponse, GitIntelligenceReport, GraphResponse
```

(This changes the existing `from .cloner import ...` and `from .models import ...`
lines to add the new names — do not duplicate import lines, extend the existing
ones.)

Add the new endpoint after the existing `/analyze` endpoint:

```python
@app.post("/git-intelligence", response_model=GitIntelligenceReport)
def git_intelligence(request: AnalyzeRequest) -> GitIntelligenceReport:
    try:
        with clone_with_history(request.repo_url) as repo_path:
            commits, history_truncated = parse_git_log(repo_path)
            return analyze_git_history(commits, history_truncated)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

Keep the existing `/analyze` endpoint and everything else in `main.py` unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && .venv/Scripts/python -m pytest tests/test_api.py -v`
Expected: all pass (pre-existing + 2 new).

Run the full fast suite: `cd backend && .venv/Scripts/python -m pytest tests/ -v -m "not slow"`
Expected: all pass, pristine output, no regressions in Phase 1/2 tests.

- [ ] **Step 5: Update backend README**

In `backend/README.md`, add a new section describing `POST /git-intelligence`
alongside the existing `/analyze` documentation — same `repo_url` request body,
response is churn/ownership/co-change data, note that it clones a bounded window of
commit history (last 500 by default) rather than full history.

- [ ] **Step 6: Commit**

```bash
cd ~/atlas
git add backend/app/main.py backend/tests/test_api.py backend/README.md
git commit -m "feat: add POST /git-intelligence endpoint"
```

---

## After this plan

Phase 3 delivers deterministic Git-history intelligence (churn, bug hotspots,
ownership, co-change) as a new, independently-cloning endpoint. Explicitly deferred:
directory-level rollups, per-author leaderboards, time-windowed queries, and any
UI — plus the previously-deferred items from Phases 1-2 (persistence, Testing/
Security/Documentation scores, duplicate/dead-code detection). Documentation
Generator is the recommended next phase per the 2026-07-23 roadmap discussion.
