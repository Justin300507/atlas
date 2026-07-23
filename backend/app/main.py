from __future__ import annotations

import logging
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from . import jobs
from .cloner import (
    CloneError,
    InvalidRepoUrlError,
    clone_with_history,
    shallow_clone,
    validate_github_url,
)
from .config import resolve_cors_origins, resolve_log_level
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
from .rate_limiter import RateLimiter
from .report_pipeline import (
    _GIT_HISTORY_COMMITS,
    analyze_structure,
    run_full_analysis,
)
from .timing import StageTimer

logging.basicConfig(
    level=resolve_log_level(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Atlas Repository Intelligence")

app.add_middleware(
    CORSMiddleware,
    allow_origins=resolve_cors_origins(),
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Tags every request with a correlation ID (reusing an inbound
    X-Request-ID if the caller/a proxy already set one) and logs a basic
    access line -- the first general-purpose log line in the app beyond
    per-job stage timing."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.monotonic()
        try:
            response = await call_next(request)
        except Exception:
            # call_next raises (rather than returning a response) for an
            # unhandled exception in the route -- exactly the case where a
            # correlation ID matters most, so still log it before
            # re-raising. There's no response object at this point to
            # attach X-Request-ID to; the log line is what actually
            # correlates this to whatever error handling produces the
            # eventual client-facing response.
            duration_ms = (time.monotonic() - start) * 1000
            logger.info(
                "%s %s -> 500 (%.1fms) [request_id=%s] (unhandled exception)",
                request.method,
                request.url.path,
                duration_ms,
                request_id,
            )
            raise
        duration_ms = (time.monotonic() - start) * 1000
        response.headers["X-Request-ID"] = request_id
        logger.info(
            "%s %s -> %d (%.1fms) [request_id=%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )
        return response


app.add_middleware(RequestIDMiddleware)

_JOB_EXECUTOR = ThreadPoolExecutor(max_workers=4)

# There's still no auth or per-user quota, and CORS is permissive by default
# in development (see config.py). This cap bounds how much clone/CPU work an
# unbounded burst of job creation (malicious or accidental) can trigger at
# once, independent of where the requests originate from.
_MAX_ACTIVE_JOBS = 8

# Global concurrency cap above bounds total simultaneous work but not how
# often one client can trigger it -- this bounds a single caller's request
# rate on the expensive (clone + analyze) endpoints, independent of that cap.
_RATE_LIMIT_MAX_REQUESTS = 20
_RATE_LIMIT_WINDOW_SECONDS = 60.0
_RATE_LIMITER = RateLimiter(_RATE_LIMIT_MAX_REQUESTS, _RATE_LIMIT_WINDOW_SECONDS)

_JOB_RETENTION_HOURS = 24


def _client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limit(request: Request) -> None:
    if not _RATE_LIMITER.allow(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many requests from this client. Please slow down and try again shortly.",
            headers={"Retry-After": str(int(_RATE_LIMIT_WINDOW_SECONDS))},
        )


@app.get("/health")
def health() -> dict:
    try:
        jobs.count_active_jobs()
        db_check = "ok"
    except Exception as exc:
        # The full exception (which can include the DB's filesystem path)
        # goes to the logs, not the response body -- /health is
        # unauthenticated, so anything more specific than the exception
        # type here would leak server filesystem details to any caller.
        logger.error("health check: database check failed: %s", exc)
        db_check = f"error: {type(exc).__name__}"
    return {
        "status": "ok" if db_check == "ok" else "degraded",
        "checks": {"database": db_check},
    }


@app.post("/analyze", response_model=AnalyzeResponse, dependencies=[Depends(rate_limit)])
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    try:
        with shallow_clone(request.repo_url) as repo_path:
            stack, _files, graph, quality, security, coverage = analyze_structure(repo_path)
            return AnalyzeResponse(
                stack=stack,
                graph=GraphResponse(**to_node_link(graph)),
                quality=quality,
                security=security,
                coverage=coverage,
            )
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/documentation", response_model=DocumentationResponse, dependencies=[Depends(rate_limit)])
def documentation(request: AnalyzeRequest) -> DocumentationResponse:
    try:
        return run_full_analysis(request.repo_url)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/git-intelligence", response_model=GitIntelligenceReport, dependencies=[Depends(rate_limit)])
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
    timer = StageTimer(lambda stage: jobs.update_job(job_id, stage=stage))
    try:
        response = run_full_analysis(repo_url, on_stage=timer)
        jobs.update_job(job_id, status="done", markdown=response.markdown)
    except InvalidRepoUrlError as exc:
        jobs.update_job(job_id, status="error", error=str(exc))
    except subprocess.TimeoutExpired:
        jobs.update_job(job_id, status="error", error="Repository clone timed out")
    except CloneError as exc:
        jobs.update_job(job_id, status="error", error=str(exc))
    except Exception as exc:  # pragma: no cover - safety net for unexpected failures
        jobs.update_job(job_id, status="error", error=f"Unexpected error: {exc}")
    finally:
        durations = timer.finish()
        logger.info("job %s stage timings (seconds): %s", job_id, durations)


@app.post("/jobs", status_code=202, dependencies=[Depends(rate_limit)])
def create_job_endpoint(request: AnalyzeRequest) -> dict:
    try:
        validate_github_url(request.repo_url)
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    jobs.cleanup_stale_jobs(_JOB_RETENTION_HOURS)
    job_id = jobs.try_create_job(request.repo_url, _MAX_ACTIVE_JOBS)
    if job_id is None:
        raise HTTPException(
            status_code=429,
            detail="Too many analyses are already in progress. Try again shortly.",
        )
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
        "created_at": record.created_at,
    }
