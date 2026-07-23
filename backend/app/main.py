from __future__ import annotations

import subprocess

from fastapi import FastAPI, HTTPException

from .cloner import CloneError, InvalidRepoUrlError, clone_with_history, shallow_clone
from .code_parser import parse_file
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import build_graph, to_node_link
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    DocumentationResponse,
    GitIntelligenceReport,
    GraphResponse,
)
from .quality_engine import analyze_quality
from .report_pipeline import (
    _GIT_HISTORY_COMMITS,
    _iter_source_files,
    run_full_analysis,
)
from .stack_detector import detect

app = FastAPI(title="Atlas Repository Intelligence")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


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
            graph = build_graph(files, repo_root=repo_path)
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


@app.post("/documentation", response_model=DocumentationResponse)
def documentation(request: AnalyzeRequest) -> DocumentationResponse:
    try:
        return run_full_analysis(request.repo_url)
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
