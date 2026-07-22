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
            files = []
            for path in _iter_source_files(repo_path):
                try:
                    symbols = parse_file(path)
                except Exception:
                    continue
                if symbols is not None:
                    files.append(symbols)
            graph = build_graph(files)
            return AnalyzeResponse(stack=stack, graph=GraphResponse(**to_node_link(graph)))
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
