from __future__ import annotations

from pathlib import Path
from typing import Callable

from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone
from .code_parser import parse_file
from .doc_generator import generate_documentation
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import build_graph
from .models import DocumentationResponse
from .quality_engine import analyze_quality
from .stack_detector import detect

# Bounds on parsing arbitrary cloned repos: this pipeline clones and parses
# arbitrary public repo URLs with no auth, so a pathological repo (one huge
# file, or hundreds of thousands of files) must not be able to exhaust
# memory/CPU.
_EXCLUDED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # skip individual files larger than this
_MAX_FILES_PER_REPO = 5000  # stop walking a repo after yielding this many files

# The commit window analyzed for git intelligence. The clone depth is set one
# commit deeper than what's analyzed so a truncated repo always has a spare
# commit locally for parse_git_log's truncation check to find — cloning and
# analyzing the exact same depth would make history_truncated always False,
# since a --depth-N clone physically cannot contain an (N+1)th commit.
_GIT_HISTORY_COMMITS = 500


def _iter_source_files(repo_path: Path):
    count = 0
    for path in repo_path.rglob("*"):
        if count >= _MAX_FILES_PER_REPO:
            return
        if not path.is_file():
            continue
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                continue
        except OSError:
            continue
        count += 1
        yield path


def _noop_stage(_stage: str) -> None:
    pass


def run_full_analysis(
    repo_url: str, on_stage: Callable[[str], None] | None = None
) -> DocumentationResponse:
    notify = on_stage or _noop_stage

    notify("cloning_structure")
    with shallow_clone(repo_url) as repo_path:
        repo_root = repo_path
        stack = detect(repo_path)

        notify("parsing")
        files = []
        for path in _iter_source_files(repo_path):
            try:
                symbols = parse_file(path)
            except Exception:
                continue
            if symbols is not None:
                files.append(symbols)

        notify("building_graph")
        graph = build_graph(files, repo_root=repo_path)

        notify("analyzing_quality")
        quality = analyze_quality(files, graph, repo_root=repo_path)

    notify("cloning_history")
    with clone_with_history(repo_url, depth=_GIT_HISTORY_COMMITS + 1) as history_path:
        notify("analyzing_git_history")
        commits, history_truncated = parse_git_log(history_path, max_commits=_GIT_HISTORY_COMMITS)
        git_report = analyze_git_history(commits, history_truncated)

    notify("generating_documentation")
    markdown = generate_documentation(repo_root, stack, files, graph, quality, git_report)
    return DocumentationResponse(markdown=markdown)
