from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import networkx as nx

from .cloner import clone_with_history
from .code_parser import FileSymbols, language_for, parse_file
from .doc_generator import generate_documentation
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import build_graph
from .models import (
    DocumentationResponse,
    FileCoverage,
    QualityReport,
    SecurityReport,
    StackReport,
)
from .quality_engine import analyze_quality
from .security_scanner import scan_files
from .semantic_analysis import analyze_semantics
from .stack_detector import detect

# Bounds on parsing arbitrary cloned repos: this pipeline clones and parses
# arbitrary public repo URLs with no auth, so a pathological repo (one huge
# file, or hundreds of thousands of files) must not be able to exhaust
# memory/CPU.
_EXCLUDED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}
_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # skip individual files larger than this

# _MAX_FILES_PER_REPO counts only source-file *candidates* (language_for
# matches), not every file the walk touches -- found via real-world
# validation (2026-07-24): counting every file let non-source clutter (docs,
# translation files, fixtures, static assets) exhaust the budget before
# reaching real source. Django alone lost 1,416 of its 2,927 real .py files
# this way. _MAX_TOTAL_ENTRIES_WALKED is a separate, much higher ceiling on
# raw filesystem entries examined regardless of type -- the original cap's
# actual job (bounding walk cost against a truly pathological repo, e.g. a
# huge vendored/binary tree) still needs *some* limit once the source-file
# count alone no longer provides one. Hitting either cap means the analysis
# is incomplete; both set files_capped.
_MAX_FILES_PER_REPO = 5000
_MAX_TOTAL_ENTRIES_WALKED = 50_000

# The commit window analyzed for git intelligence. The clone depth is set one
# commit deeper than what's analyzed so a truncated repo always has a spare
# commit locally for parse_git_log's truncation check to find — cloning and
# analyzing the exact same depth would make history_truncated always False,
# since a --depth-N clone physically cannot contain an (N+1)th commit.
_GIT_HISTORY_COMMITS = 500


@dataclass
class _FileWalkStats:
    """Tracks what the file walk actually did, so a truncated or partial
    analysis can be surfaced honestly instead of silently discarded -- found
    missing during real-world validation (2026-07-24): the file-count cap
    below has existed since Phase 2 with no way for a caller to tell whether
    it was ever hit."""

    files_walked: int = 0
    files_capped: bool = False
    files_skipped_oversized: int = 0
    files_parse_failed: int = 0


def _iter_source_files(repo_path: Path, stats: _FileWalkStats):
    entries_seen = 0
    for path in repo_path.rglob("*"):
        # Exclusion check comes before the entries_seen budget: excluded
        # dirs (.git, node_modules, ...) are exactly the "huge vendored
        # tree" case _MAX_TOTAL_ENTRIES_WALKED exists to guard against, so
        # letting their contents consume that budget before it's even
        # checked would make a large .git history or vendored tree trip the
        # ceiling for the wrong reason (found in review, 2026-07-24).
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        entries_seen += 1
        if entries_seen > _MAX_TOTAL_ENTRIES_WALKED:
            stats.files_capped = True
            return
        if not path.is_file():
            continue
        if language_for(path) is None:
            continue
        if stats.files_walked >= _MAX_FILES_PER_REPO:
            stats.files_capped = True
            return
        try:
            if path.stat().st_size > _MAX_FILE_SIZE_BYTES:
                stats.files_skipped_oversized += 1
                continue
        except OSError:
            continue
        stats.files_walked += 1
        yield path


def _noop_stage(_stage: str) -> None:
    pass


def analyze_structure(
    repo_path: Path, on_stage: Callable[[str], None] | None = None
) -> tuple[StackReport, list[FileSymbols], nx.DiGraph, QualityReport, SecurityReport, FileCoverage]:
    """Clone-independent structural analysis: stack detection, parsing, the
    import graph, quality scoring, and security scanning. Shared by /analyze
    and run_full_analysis so the two don't maintain separate copies of the
    same parse-and-score loop."""
    notify = on_stage or _noop_stage

    stack = detect(repo_path)

    notify("parsing")
    stats = _FileWalkStats()
    files: list[FileSymbols] = []
    for path in _iter_source_files(repo_path, stats):
        try:
            symbols = parse_file(path)
        except Exception:
            stats.files_parse_failed += 1
            continue
        if symbols is not None:
            files.append(symbols)

    notify("building_graph")
    graph = build_graph(files, repo_root=repo_path)

    notify("analyzing_quality")
    quality = analyze_quality(files, graph, repo_root=repo_path)

    notify("scanning_security")
    security = scan_files(files)

    coverage = FileCoverage(
        files_analyzed=len(files),
        files_capped=stats.files_capped,
        files_skipped_oversized=stats.files_skipped_oversized,
        files_parse_failed=stats.files_parse_failed,
    )

    return stack, files, graph, quality, security, coverage


def run_full_analysis(
    repo_url: str, on_stage: Callable[[str], None] | None = None
) -> DocumentationResponse:
    notify = on_stage or _noop_stage

    # A single depth-(N+1) clone checks out the exact same working tree a
    # depth-1 shallow_clone would (extra depth only adds history behind HEAD,
    # not different files), so structure analysis and git-history analysis
    # can share one clone instead of fetching the same repo twice. Stage
    # names/order are unchanged so job-progress polling sees no difference.
    notify("cloning_structure")
    with clone_with_history(repo_url, depth=_GIT_HISTORY_COMMITS + 1) as repo_path:
        repo_root = repo_path
        stack, files, graph, quality, security, coverage = analyze_structure(repo_path, on_stage)

        # No separate "cloning_history" stage anymore -- the single clone
        # above already fetched everything git-history analysis needs, so
        # there's no distinct clone step left here to report a duration for.
        notify("analyzing_git_history")
        commits, history_truncated = parse_git_log(repo_path, max_commits=_GIT_HISTORY_COMMITS)
        git_report = analyze_git_history(commits, history_truncated)

        notify("analyzing_semantics")
        semantic = analyze_semantics(files, graph, quality, commits, repo_root=repo_path)

    notify("generating_documentation")
    markdown = generate_documentation(
        repo_root, stack, files, graph, quality, security, git_report, coverage, semantic
    )
    return DocumentationResponse(markdown=markdown)
