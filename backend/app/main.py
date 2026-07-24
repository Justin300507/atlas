from __future__ import annotations

import logging
import os
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from . import jobs
from .ai_explain import (
    AnthropicExplainer,
    architecture_summary_evidence,
    critical_module_explanation_evidence,
    dependency_explanation_evidence,
    finding_evidence,
    hotspot_explanation_evidence,
    insufficient_evidence,
    layer_explanation_evidence,
    repository_overview_evidence,
    subsystem_summary_evidence,
)
from .cloner import (
    CloneError,
    InvalidRepoUrlError,
    clone_with_history,
    shallow_clone,
    validate_github_url,
)
from .comparison_engine import compare_snapshots
from .config import resolve_cors_origins, resolve_log_level
from .doc_generator import generate_comparison_report
from .git_intelligence import analyze_git_history
from .git_log_parser import parse_git_log
from .graph_builder import to_node_link
from .models import (
    AnalysisSnapshot,
    AnalyzeRequest,
    AnalyzeResponse,
    CompareRequest,
    CompareResponse,
    DocumentationResponse,
    ExplanationRequest,
    ExplanationResponse,
    GitIntelligenceReport,
    GraphResponse,
    MentorRequest,
    PerformanceReport,
    TechnicalDebtReport,
)
from .performance_analyzer import analyze_performance
from .rate_limiter import RateLimiter
from .report_pipeline import (
    _GIT_HISTORY_COMMITS,
    analyze_structure,
    run_full_analysis,
)
from .semantic_analysis import analyze_semantics
from .technical_debt import analyze_technical_debt
from .timing import StageTimer

logging.basicConfig(
    level=resolve_log_level(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(title="Atlas Repository Intelligence")

_resolved_cors_origins = resolve_cors_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_resolved_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

# One-line confirmation of what actually took effect -- resolve_cors_origins
# either raises (refuses to start) or silently returns a list, so without
# this, an operator setting ATLAS_ALLOWED_ORIGINS in production has no way
# to confirm the value was read correctly short of triggering an actual
# cross-origin request and inspecting the response.
logger.info(
    "startup config: env=%s allowed_origins=%s log_level=%s",
    os.environ.get("ATLAS_ENV", "development"),
    _resolved_cors_origins,
    logging.getLevelName(resolve_log_level()),
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


# v1.3 Engineering Advisor Suite -- see
# docs/superpowers/specs/2026-07-24-engineering-advisor-suite-design.md.
# Debt/performance/architect/mentor clone and analyze a fresh repo per
# request (like /git-intelligence) rather than requiring a prior /jobs
# run, since they're meant to be usable standalone.

_explainer = AnthropicExplainer()

_ARCHITECT_EVIDENCE_NO_FILE = {
    "architecture_summary": architecture_summary_evidence,
    "subsystem_summary": subsystem_summary_evidence,
    "dependency_explanation": dependency_explanation_evidence,
    "layer_explanation": layer_explanation_evidence,
}
_ARCHITECT_EVIDENCE_WITH_FILE = {
    "critical_module_explanation": critical_module_explanation_evidence,
    "hotspot_explanation": hotspot_explanation_evidence,
}


@contextmanager
def _cloned_repo_with_history(repo_url: str):
    """Shared clone + error-translation for the four advisor endpoints below
    -- the same three exceptions /analyze, /documentation, and
    /git-intelligence each translate to an HTTPException individually."""
    try:
        with clone_with_history(repo_url, depth=_GIT_HISTORY_COMMITS + 1) as repo_path:
            yield repo_path
    except InvalidRepoUrlError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="Repository clone timed out") from exc
    except CloneError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _semantic_context(repo_path: Path):
    """Structural + git + semantic analysis, shared by all four advisor
    endpoints -- each needs a different subset of it but all start here."""
    stack, files, graph, quality, security, coverage = analyze_structure(repo_path)
    commits, history_truncated = parse_git_log(repo_path, max_commits=_GIT_HISTORY_COMMITS)
    semantic = analyze_semantics(files, graph, quality, commits, repo_root=repo_path)
    return files, graph, quality, security, semantic, commits


@app.post("/technical-debt", response_model=TechnicalDebtReport, dependencies=[Depends(rate_limit)])
def technical_debt(request: AnalyzeRequest) -> TechnicalDebtReport:
    with _cloned_repo_with_history(request.repo_url) as repo_path:
        files, graph, quality, _security, semantic, commits = _semantic_context(repo_path)
        return analyze_technical_debt(files, graph, quality, semantic, commits, repo_root=repo_path)


@app.post("/performance-analysis", response_model=PerformanceReport, dependencies=[Depends(rate_limit)])
def performance_analysis(request: AnalyzeRequest) -> PerformanceReport:
    with _cloned_repo_with_history(request.repo_url) as repo_path:
        files, _graph, _quality, _security, semantic, _commits = _semantic_context(repo_path)
        return analyze_performance(files, semantic, repo_root=repo_path)


@app.post("/ai-architect", response_model=ExplanationResponse, dependencies=[Depends(rate_limit)])
def ai_architect(request: ExplanationRequest) -> ExplanationResponse:
    with _cloned_repo_with_history(request.repo_url) as repo_path:
        _files, _graph, quality, _security, semantic, _commits = _semantic_context(repo_path)

    if request.prompt_kind == "repository_overview":
        evidence = repository_overview_evidence(
            quality.overall_score, quality.maintainability_score, quality.architecture_score, semantic
        )
        return _explainer.explain(request.prompt_kind, evidence)

    if request.prompt_kind in _ARCHITECT_EVIDENCE_NO_FILE:
        evidence = _ARCHITECT_EVIDENCE_NO_FILE[request.prompt_kind](semantic)
        return _explainer.explain(request.prompt_kind, evidence)

    if request.prompt_kind in _ARCHITECT_EVIDENCE_WITH_FILE:
        if not request.file:
            raise HTTPException(
                status_code=400, detail=f"prompt_kind '{request.prompt_kind}' requires a 'file'."
            )
        evidence = _ARCHITECT_EVIDENCE_WITH_FILE[request.prompt_kind](semantic, request.file)
        if evidence is None:
            return insufficient_evidence(
                f"{request.file} was not flagged by Atlas for '{request.prompt_kind}' in this repository."
            )
        return _explainer.explain(request.prompt_kind, evidence)

    raise HTTPException(status_code=400, detail=f"Unknown prompt_kind '{request.prompt_kind}'.")


@app.post("/ai-mentor", response_model=ExplanationResponse, dependencies=[Depends(rate_limit)])
def ai_mentor(request: MentorRequest) -> ExplanationResponse:
    with _cloned_repo_with_history(request.repo_url) as repo_path:
        _files, _graph, quality, security, semantic, _commits = _semantic_context(repo_path)

    # AI Mentor only ever explains a finding Atlas itself already flagged --
    # refuse (don't guess, don't ask the model) if the (file, kind) pair
    # named in the request isn't actually present in this repository's
    # analysis.
    candidates = (
        list(quality.issues)
        + list(security.issues)
        + list(semantic.coupling_issues)
        + list(semantic.architectural_smells)
    )
    match = next(
        (f for f in candidates if f.file == request.finding_file and f.kind == request.finding_kind), None
    )
    if match is None:
        return insufficient_evidence(
            f"Atlas did not flag '{request.finding_kind}' in {request.finding_file} for this repository."
        )
    evidence = finding_evidence(match)
    return _explainer.explain("finding_explanation", evidence)


def _submit_job(job_id: str, repo_url: str, request_id: str | None = None) -> None:
    _JOB_EXECUTOR.submit(_run_job, job_id, repo_url, request_id)


def _run_job(job_id: str, repo_url: str, request_id: str | None = None) -> None:
    # _run_job executes on a ThreadPoolExecutor thread, decoupled from the
    # Request that queued it -- request_id is passed explicitly (not read
    # from request.state) so the job's completion log line still
    # correlates back to the POST /jobs request that started it.
    jobs.update_job(job_id, status="running")
    timer = StageTimer(lambda stage: jobs.update_job(job_id, stage=stage))
    try:
        response = run_full_analysis(repo_url, on_stage=timer)
        snapshot_json = response.snapshot.model_dump_json() if response.snapshot else None
        jobs.update_job(job_id, status="done", markdown=response.markdown, snapshot=snapshot_json)
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
        logger.info(
            "job %s stage timings (seconds): %s [request_id=%s]",
            job_id,
            durations,
            request_id,
        )


@app.post("/jobs", status_code=202, dependencies=[Depends(rate_limit)])
def create_job_endpoint(request: AnalyzeRequest, http_request: Request) -> dict:
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
    _submit_job(job_id, request.repo_url, getattr(http_request.state, "request_id", None))
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


def _resolve_snapshot_for_comparison(job_id: str) -> AnalysisSnapshot:
    record = jobs.get_job(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No job found with id {job_id}")
    if record.status != "done":
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} is not done yet (status: {record.status}) -- no snapshot available.",
        )
    if record.snapshot is None:
        raise HTTPException(
            status_code=409,
            detail=f"Job {job_id} has no snapshot -- it predates the comparison feature.",
        )
    return AnalysisSnapshot.model_validate_json(record.snapshot)


@app.post("/compare", response_model=CompareResponse, dependencies=[Depends(rate_limit)])
def compare(request: CompareRequest) -> CompareResponse:
    snapshot_a = _resolve_snapshot_for_comparison(request.job_id_a)
    snapshot_b = _resolve_snapshot_for_comparison(request.job_id_b)
    comparison = compare_snapshots(snapshot_a, snapshot_b)
    markdown = generate_comparison_report(comparison)
    return CompareResponse(markdown=markdown, comparison=comparison)
