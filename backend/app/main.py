from __future__ import annotations

import subprocess
from concurrent.futures import ThreadPoolExecutor

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from . import jobs
from .cloner import (
    CloneError,
    InvalidRepoUrlError,
    clone_with_history,
    shallow_clone,
    validate_github_url,
)
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import to_node_link
from .models import (
    AnalyzeRequest,
    AnalyzeResponse,
    DocumentationResponse,
    GitIntelligenceReport,
    GraphResponse,
)
from .report_pipeline import (
    _GIT_HISTORY_COMMITS,
    analyze_structure,
    run_full_analysis,
)

app = FastAPI(title="Atlas Repository Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# CORS is wide open (no auth, no secrets in responses) so any page can call
# this API cross-origin, including one a user didn't intend to run a clone
# from. This cap bounds how much clone/CPU work an unbounded burst of job
# creation (malicious or accidental) can trigger at once, independent of
# where the requests originate from.
_MAX_ACTIVE_JOBS = 8


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        with shallow_clone(request.repo_url) as repo_path:
            stack, _files, graph, quality = analyze_structure(repo_path)
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


def _submit_job(job_id: str, repo_url: str) -> None:
    _JOB_EXECUTOR.submit(_run_job, job_id, repo_url)


def _run_job(job_id: str, repo_url: str) -> None:
    jobs.update_job(job_id, status="running")
    try:
        response = run_full_analysis(
            repo_url, on_stage=lambda stage: jobs.update_job(job_id, stage=stage)
        )
        jobs.update_job(job_id, status="done", markdown=response.markdown)
    except InvalidRepoUrlError as exc:
        jobs.update_job(job_id, status="error", error=str(exc))
    except subprocess.TimeoutExpired:
        jobs.update_job(job_id, status="error", error="Repository clone timed out")
    except CloneError as exc:
        jobs.update_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # pragma: no cover - safety net for unexpected failures
        jobs.update_job(job_id, status="error", error=f"Unexpected error: {exc}")


@app.post("/jobs", status_code=202)
def create_job_endpoint(request: AnalyzeRequest) -> dict:
    try:
        validate_github_url(request.repo_url)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if jobs.count_active_jobs() >= _MAX_ACTIVE_JOBS:
        raise HTTPException(
            status_code=429,
            detail="Too many analyses are already in progress. Try again shortly.",
        )
    job_id = jobs.create_job(request.repo_url)
    _submit_job(job_id, request.repo_url)
    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
def get_job_endpoint(job_id: str) -> dict:
    record = jobs.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id}")
    return {
        "id": record.id,
        "status": record.status,
        "stage": record.stage,
        "markdown": record.markdown,
        "error": record.error,
    }
