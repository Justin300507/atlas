from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException

from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone
from .code_parser import parse_file
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import build_graph, to_node_link
from .models import AnalyzeRequest, AnalyzeResponse, GitIntelligenceReport, GraphResponse
from .quality_engine import analyze_quality
from .stack_detector import detect

app = FastAPI(title="Atlas Repository Intelligence")

_EXCLUDED_DIRS = {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"}

# Bounds on parsing arbitrary cloned repos: this endpoint clones and parses
# arbitrary public repo URLs with no auth, so a pathological repo (one huge
# file, or hundreds of thousands of files) must not be able to exhaust
# memory/CPU.
_MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024  # skip individual files larger than this
_MAX_FILES_PER_REPO = 5000  # stop walking a repo after yielding this many files

# The commit window analyzed by /git-intelligence. The clone depth is set one
# commit deeper than what's analyzed so a truncated repo always has a spare
# commit locally for parse_git_log's truncation check to find — cloning and
# analyzing the exact same depth would make history_truncated always False,
# since a --depth-N clone physically cannot contain an (N+1)th commit.
_GIT_HISTORY_COMMITS = 500


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        with shallow_clone(request.repo_url) as repo_path:
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
            return AnalyzeResponse(
                stack=stack,
                graph=GraphResponse(**to_node_link(graph)),
                quality=quality,
            )
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/git-intelligence", response_model=GitIntelligenceReport)
def git_intelligence(request: AnalyzeRequest) -> GitIntelligenceReport:
    try:
        with clone_with_history(request.repo_url, depth=_GIT_HISTORY_COMMITS + 1) as repo_path:
            commits, history_truncated = parse_git_log(repo_path, max_commits=_GIT_HISTORY_COMMITS)
            return analyze_git_history(commits, history_truncated)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
