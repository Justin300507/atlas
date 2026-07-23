# Atlas Phase 3: Git Intelligence (v1)

## Purpose

Phases 1-2 analyze a repo's *current state* (structure, imports, quality). Git
Intelligence analyzes its *history*: which files change most, which commits look like
bug fixes, who owns which files, and which files tend to change together. This is
one of Atlas's biggest differentiators because it's entirely deterministic — no LLM
call needed — and cheap to compute from data every repo already has.

## Scope decisions for this phase

- **New endpoint, not an extension of `POST /analyze`.** Phase 2 extended `/analyze`
  because quality analysis reused the exact same clone/parse pipeline already running
  for that request. Git Intelligence can't do that: `cloner.shallow_clone` does
  `git clone --depth 1`, which discards commit history by design (that's what makes it
  fast for Phase 1/2's structural analysis). Getting history back requires a
  differently-shaped clone. Since the two endpoints clone independently anyway,
  there's no shared work to preserve by cramming this into `/analyze` — a new
  `POST /git-intelligence` endpoint keeps each endpoint's clone strategy honest about
  what it actually needs.
- **New `clone_with_history` alongside the existing `shallow_clone`, not a modification
  to it.** `shallow_clone`'s `--depth 1` behavior is load-bearing for Phase 1/2 (fast,
  bounded, all that's needed for structure/quality) — it must not change. Add a
  sibling function in `cloner.py` that clones with a bounded commit depth instead of a
  full clone, for the same reason `main.py` already caps file count/size: an
  unauthenticated public endpoint that clones arbitrary repos must not be able to pull
  an unbounded amount of history from a 15-year-old repo.
- **`git log` via subprocess, not a new dependency.** `cloner.py` already shells out to
  `git` directly (see `_clone_to`). `git log --numstat --pretty=format:...` gives
  commit hash, author email, message, and per-file added/removed line counts in one
  call — everything this phase needs, with no GitPython or pygit2 dependency to add.
- **Four analyses, chosen because they directly answer the four questions from the
  roadmap discussion and are all cheap rollups over the same commit list:**
  1. **File churn** — commit count per file, descending. Answers "which files change
     the most."
  2. **Bug-fix hotspots** — commits whose subject line matches a fix/bug/hotfix/patch
     pattern, counted per file. Answers "which modules are bug hotspots," reported as
     a `bug_fix_count` alongside each file's churn rather than a separate list, since
     it's the same per-file rollup with a filtered commit set.
  3. **Ownership** — per file, the author with the most commits touching it, and what
     fraction of that file's commits they account for. Answers "which developer owns
     this feature."
  4. **Co-change** — pairs of files that appear together in the same commit, counted
     across all commits, descending. Answers "which files frequently change together."
- **Explicitly deferred:** directory-level churn rollups (derivable client-side from
  file-level churn paths — adding a second aggregation axis this phase is scope creep
  the same way Phase 2 deferred duplicate/dead-code detection), per-author overall
  stats (a leaderboard view, not a file-intelligence view — different feature),
  and any time-windowing (e.g. "churn in the last 30 days") — v1 reports over
  whatever bounded commit window it clones, nothing fancier.
- **Truncation honesty, applying the design note from Phase 2's review.** Because the
  clone is bounded to the last N commits (not full history), the response reports
  `commits_analyzed` and a `history_truncated` flag so a caller can tell "this repo
  has more history than we looked at" rather than silently treating a partial picture
  as complete — the same principle Phase 2's review flagged for file-count truncation.

## Architecture

```
POST /git-intelligence  { repo_url }
        │
        ▼
cloner.clone_with_history(url, depth=500)   <- NEW: bounded-history clone
        │  (reuses the existing tempdir/cleanup/validate-url machinery in
        │   cloner.py via a shared helper; only the git invocation differs)
        ▼
git_log_parser.parse_git_log(repo_path, max_commits=500) -> list[Commit]
        │  Commit(hash, author_email, message,
        │          files: list[FileChange(path, additions, deletions)])
        │  (subprocess: `git log --numstat --pretty=format:"COMMIT|%H|%ae|%s"`)
        ▼
git_intelligence.analyze_git_history(commits, history_truncated) -> GitIntelligenceReport
        │
        ├─ churn + bug_fix_count  <- count commits per file; count per file where
        │                            commit.message matches bug-fix regex
        ├─ ownership              <- count commits per (file, author); pick top author
        └─ co_changes             <- for each multi-file commit, count file pairs
        │
        ▼
GitIntelligenceReport(commits_analyzed, history_truncated,
                       churn[], ownership[], co_changes[])
```

### Components

- **`cloner.py` (modified)** — extract the shared tempdir/validate/cleanup logic from
  `shallow_clone` into a small private helper, then add
  `clone_with_history(url: str, depth: int = 500, timeout: int = 120)` as a second
  context manager that clones with `git clone --shallow-since` is not needed — use
  `git clone --depth <depth> --no-single-branch` is unnecessary too; plain
  `git clone --depth <depth> <url> <dest>` already retains `<depth>` commits of
  history on the default branch, which is all this phase reads. `shallow_clone`
  itself is untouched in behavior (still `--depth 1`).
- **`git_log_parser.py` (new)** — `Commit` and `FileChange` dataclasses;
  `parse_git_log(repo_path: Path, max_commits: int) -> tuple[list[Commit], bool]`
  (the `bool` is `history_truncated`: true if the repo has strictly more commits than
  `max_commits` reached, detected via `git rev-list --count HEAD` vs. commits parsed).
  Pure subprocess wrapper + text parsing, no network.
- **`git_intelligence.py` (new)** — pure function
  `analyze_git_history(commits: list[Commit], history_truncated: bool) -> GitIntelligenceReport`,
  no I/O, fully unit-testable against constructed `Commit` lists (same pattern as
  Phase 2's `quality_engine.py` against constructed `FileSymbols`).
- **`models.py` (modified)** — add `FileChurn`, `FileOwnership`, `CoChangePair`,
  `GitIntelligenceReport` Pydantic models (details below). Does **not** touch
  `AnalyzeResponse` — this is a new, independent response shape for a new endpoint.
- **`main.py` (modified)** — add `POST /git-intelligence`, structured the same way as
  `/analyze`: clone (via the new `clone_with_history`) inside a `try/except` mapping
  `InvalidRepoUrlError`/`CloneError`/`TimeoutExpired` to the same HTTP status codes
  already used by `/analyze`, then parse + analyze.

## Data model

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
    ownership_ratio: float  # top_author_commits / total_commits, 0.0-1.0

class CoChangePair(BaseModel):
    file_a: str
    file_b: str
    co_change_count: int

class GitIntelligenceReport(BaseModel):
    commits_analyzed: int
    history_truncated: bool
    churn: list[FileChurn]           # top 20 by commit_count desc
    ownership: list[FileOwnership]   # top 20 by total_commits desc
    co_changes: list[CoChangePair]   # top 20 by co_change_count desc
```

Capping each list to the top 20 keeps the response signal-dense on large repos
(mirrors Phase 2's discipline of reporting real issues, not padding); the cap is a
simple slice after sorting, not a scoring decision, so it's cheap to change later if
usage shows 20 is wrong.

## Bug-fix commit detection

A commit is a bug-fix commit if its subject line (first line of the message) matches,
case-insensitively: `\b(fix|fixes|fixed|bug|hotfix|patch|bugfix)\b`. This is a v1
heuristic against conventional-commit-style and plain-English messages alike — it
will have false positives/negatives on unconventional histories, same honesty as
Phase 2's naming-convention regexes; not tuned against real-world repos yet.

## Error handling

`analyze_git_history` never raises for a commit with zero files changed (an empty
merge commit, say) — it just contributes nothing to churn/ownership/co-change, the
same "degrade gracefully" posture as `quality_engine.analyze_quality`.
`parse_git_log` skips a `numstat` line it can't parse (e.g. a binary file shows `-`
for added/removed) rather than crashing the whole request.

## Testing

- Unit tests for `git_log_parser.parse_git_log` against a real local git repo built in
  the test via `tempfile`/`subprocess` (same pattern as `test_cloner.py`'s
  `test_clone_to_local_repo`: `git init`, write files, commit, repeat) with known
  commits/authors/files, asserting the parsed `Commit` list matches, plus a
  `history_truncated` test using `max_commits` smaller than the repo's real commit
  count.
- Unit tests for `git_intelligence.analyze_git_history` against hand-constructed
  `Commit` lists covering: churn ordering, bug-fix detection, ownership with a clear
  majority author, ownership with a tie (deterministic tie-break: first author
  encountered, i.e. stable sort), and co-change counting across a 3-file commit
  (must count all 3 pairs).
- One API-level test for `POST /git-intelligence` using a real local git repo fixture
  (built the same way as the parser tests) with `clone_with_history` monkeypatched to
  yield that local path directly — no live network, same approach as `test_api.py`'s
  `monkeypatch.setattr("app.main.shallow_clone", fake_clone)`.
- No live-network dependency added.

## Tech stack (this phase)

No new dependencies — `git` CLI (already a hard requirement via `cloner.py`) is the
only tool used, invoked via `subprocess` (already imported in `cloner.py`).

## Out of scope for this phase (explicitly deferred)

Directory-level churn rollups, per-author leaderboards, time-windowed churn (e.g.
"last 30 days"), a UI/visualization of any of this, and persistence of git-intelligence
history over time (would need the still-deferred database, same as every other
phase's deferred persistence).
