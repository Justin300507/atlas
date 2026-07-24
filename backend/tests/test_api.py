import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

from app import jobs as app_jobs
from app import main as app_main
from app.main import app

client = TestClient(app)
FIXTURES = Path(__file__).parent / "fixtures"


def test_analyze_rejects_invalid_url():
    resp = client.post("/analyze", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400


def test_analyze_returns_stack_and_graph(monkeypatch):
    fixture = FIXTURES / "fastapi_repo"

    @contextmanager
    def fake_clone(url, timeout=60):
        yield fixture

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["stack"]["backend"] == "FastAPI"
    assert body["stack"]["deployment"] == "Docker"
    assert len(body["graph"]["nodes"]) > 0
    assert "quality" in body
    assert "overall_score" in body["quality"]
    assert "security" in body
    assert "issues" in body["security"]


def test_analyze_returns_422_on_clone_failure(monkeypatch):
    from app.cloner import CloneError

    @contextmanager
    def failing_clone(url, timeout=60):
        raise CloneError("repository not found")
        yield  # pragma: no cover

    monkeypatch.setattr("app.main.shallow_clone", failing_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/does-not-exist"})
    assert resp.status_code == 422


def test_analyze_skips_unparseable_file_and_continues(monkeypatch, tmp_path):
    good_file = tmp_path / "good.py"
    good_file.write_text("import os\n\n\ndef ok():\n    pass\n")
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def broken():\n    pass\n")

    from app.code_parser import parse_file as real_parse_file

    @contextmanager
    def fake_clone(url, timeout=60):
        yield tmp_path

    def flaky_parse_file(path):
        if path.name == "bad.py":
            raise RuntimeError("simulated parse failure")
        return real_parse_file(path)

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)
    monkeypatch.setattr("app.report_pipeline.parse_file", flaky_parse_file)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["graph"]["nodes"]}
    assert str(good_file) in node_ids
    assert str(bad_file) not in node_ids
    assert "quality" in body
    assert "overall_score" in body["quality"]
    assert "security" in body
    assert "issues" in body["security"]


def test_analyze_skips_oversized_file_and_keeps_others(monkeypatch, tmp_path):
    from app.report_pipeline import _MAX_FILE_SIZE_BYTES

    good_file = tmp_path / "good.py"
    good_file.write_text("import os\n\n\ndef ok():\n    pass\n")
    big_file = tmp_path / "big.py"
    big_file.write_bytes(b"x" * (_MAX_FILE_SIZE_BYTES + 1))

    @contextmanager
    def fake_clone(url, timeout=60):
        yield tmp_path

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["graph"]["nodes"]}
    assert str(good_file) in node_ids
    assert str(big_file) not in node_ids
    assert "quality" in body
    assert "overall_score" in body["quality"]
    assert "security" in body
    assert "issues" in body["security"]


def test_analyze_stops_walking_after_max_file_count(monkeypatch, tmp_path):
    for i in range(5):
        (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")

    monkeypatch.setattr("app.report_pipeline._MAX_FILES_PER_REPO", 2)

    @contextmanager
    def fake_clone(url, timeout=60):
        yield tmp_path

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    module_nodes = [n for n in body["graph"]["nodes"] if n["type"] == "module"]
    assert len(module_nodes) == 2
    assert "quality" in body
    assert "overall_score" in body["quality"]
    assert "security" in body
    assert "issues" in body["security"]


def test_analyze_quality_report_has_expected_shape(monkeypatch):
    fixture = FIXTURES / "fastapi_repo"

    @contextmanager
    def fake_clone(url, timeout=60):
        yield fixture

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    quality = resp.json()["quality"]
    assert set(quality.keys()) == {
        "overall_score",
        "maintainability_score",
        "architecture_score",
        "issues",
    }
    assert isinstance(quality["issues"], list)


def test_analyze_security_report_has_expected_shape(monkeypatch):
    fixture = FIXTURES / "fastapi_repo"

    @contextmanager
    def fake_clone(url, timeout=60):
        yield fixture

    monkeypatch.setattr("app.main.shallow_clone", fake_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    security = resp.json()["security"]
    assert set(security.keys()) == {"issues"}
    assert isinstance(security["issues"], list)


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


def test_documentation_returns_markdown_report(tmp_path, monkeypatch):
    # run_full_analysis now clones once (via clone_with_history) and reuses
    # that checkout for both structure and git-history analysis, so the
    # fake needs a single directory that's both the real fixture's file tree
    # and a real git repo.
    combined_repo = tmp_path / "combined_repo"
    shutil.copytree(FIXTURES / "fastapi_repo", combined_repo)
    subprocess.run(["git", "init"], cwd=combined_repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=combined_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=combined_repo,
        check=True,
        capture_output=True,
    )

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield combined_repo

    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)

    resp = client.post("/documentation", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    markdown = resp.json()["markdown"]
    assert "## Executive Summary" in markdown
    assert "## API Reference" in markdown
    assert "/users" in markdown
    assert "Commits analyzed: 1" in markdown
    assert "main.py" in markdown.split("## Recent High-Churn Components")[1]


def test_documentation_rejects_invalid_url():
    resp = client.post("/documentation", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400


def test_create_job_returns_202_with_job_id(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url, request_id=None: None)

    resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})

    assert resp.status_code == 202
    body = resp.json()
    assert "job_id" in body
    assert app_jobs.get_job(body["job_id"]) is not None


def test_create_job_rejects_invalid_url(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    resp = client.post("/jobs", json={"repo_url": "not-a-url"})

    assert resp.status_code == 400


def test_create_job_rejects_when_too_many_jobs_are_active(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._MAX_ACTIVE_JOBS", 2)
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url, request_id=None: None)

    for _ in range(2):
        resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
        assert resp.status_code == 202

    resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 429


def test_get_job_returns_404_for_unknown_id(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    resp = client.get("/jobs/does-not-exist")

    assert resp.status_code == 404


def test_get_job_includes_created_at_for_refresh_recovery(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url, request_id=None: None)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    job_id = create_resp.json()["job_id"]

    resp = client.get(f"/jobs/{job_id}")

    assert resp.status_code == 200
    assert resp.json()["created_at"]


def test_job_runs_synchronously_via_submit_override_and_reaches_done(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    history_repo = tmp_path / "history_repo"
    history_repo.mkdir()
    subprocess.run(["git", "init"], cwd=history_repo, check=True, capture_output=True)
    (history_repo / "a.py").write_text("1\n")
    subprocess.run(["git", "add", "a.py"], cwd=history_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=history_repo,
        check=True,
        capture_output=True,
    )

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield history_repo

    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)
    # Run the job inline instead of on a background thread, so the test is
    # deterministic — _submit_job and _run_job share the same (job_id,
    # repo_url) signature, so this substitution is exact.
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    job_id = create_resp.json()["job_id"]

    status_resp = client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "done"
    assert body["error"] is None
    assert "## Executive Summary" in body["markdown"]


def _run_synchronous_job(monkeypatch, repo_path, repo_url="https://github.com/example/example") -> str:
    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo_path

    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    create_resp = client.post("/jobs", json={"repo_url": repo_url})
    return create_resp.json()["job_id"]


def _init_git_repo(path: Path, filename: str = "a.py", content: str = "1\n") -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / filename).write_text(content)
    subprocess.run(["git", "add", filename], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=path,
        check=True,
        capture_output=True,
    )


def test_compare_two_completed_jobs_returns_markdown_and_comparison(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    repo = tmp_path / "repo"
    _init_git_repo(repo)

    job_id_a = _run_synchronous_job(monkeypatch, repo)
    job_id_b = _run_synchronous_job(monkeypatch, repo)

    resp = client.post("/compare", json={"job_id_a": job_id_a, "job_id_b": job_id_b})

    assert resp.status_code == 200
    body = resp.json()
    assert "## Executive Summary" in body["markdown"]
    assert body["comparison"]["repo_url_a"] == "https://github.com/example/example"
    assert isinstance(body["comparison"]["metric_changes"], list)


def test_compare_returns_404_for_unknown_job(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    job_id = _run_synchronous_job(monkeypatch, repo)

    resp = client.post("/compare", json={"job_id_a": job_id, "job_id_b": "does-not-exist"})

    assert resp.status_code == 404


def test_compare_returns_409_for_a_job_that_is_not_done(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    done_job_id = _run_synchronous_job(monkeypatch, repo)

    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url, request_id=None: None)
    pending_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    pending_job_id = pending_resp.json()["job_id"]

    resp = client.post("/compare", json={"job_id_a": done_job_id, "job_id_b": pending_job_id})

    assert resp.status_code == 409


def test_compare_returns_409_for_a_job_that_predates_the_snapshot_column(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    done_job_id = _run_synchronous_job(monkeypatch, repo)

    old_job_id = app_jobs.create_job("https://github.com/example/old", db_path=tmp_path / "jobs.db")
    app_jobs.update_job(old_job_id, status="done", markdown="# old report", db_path=tmp_path / "jobs.db")

    resp = client.post("/compare", json={"job_id_a": done_job_id, "job_id_b": old_job_id})

    assert resp.status_code == 409


def test_analyze_rejects_oversized_repo_url_payload():
    resp = client.post("/analyze", json={"repo_url": "x" * 301})
    assert resp.status_code == 422


def test_rate_limit_returns_429_with_retry_after_once_exceeded(monkeypatch, tmp_path):
    from app.rate_limiter import RateLimiter

    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url, request_id=None: None)
    monkeypatch.setattr("app.main._RATE_LIMITER", RateLimiter(max_requests=2, window_seconds=60))

    for _ in range(2):
        resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
        assert resp.status_code == 202

    resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 429
    assert resp.headers["retry-after"] == "60"


def test_rate_limit_key_ignores_x_forwarded_for_header(monkeypatch, tmp_path):
    from app.rate_limiter import RateLimiter

    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url, request_id=None: None)
    monkeypatch.setattr("app.main._RATE_LIMITER", RateLimiter(max_requests=1, window_seconds=60))

    resp_a = client.post(
        "/jobs",
        json={"repo_url": "https://github.com/example/example"},
        headers={"X-Forwarded-For": "203.0.113.5"},
    )
    assert resp_a.status_code == 202

    # A spoofed X-Forwarded-For must not grant a second client identity --
    # the key is the actual transport-level client, which is unchanged.
    resp_b = client.post(
        "/jobs",
        json={"repo_url": "https://github.com/example/example"},
        headers={"X-Forwarded-For": "203.0.113.6"},
    )
    assert resp_b.status_code == 429


def test_job_logs_stage_timings_on_completion(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    history_repo = tmp_path / "history_repo"
    history_repo.mkdir()
    subprocess.run(["git", "init"], cwd=history_repo, check=True, capture_output=True)
    (history_repo / "a.py").write_text("1\n")
    subprocess.run(["git", "add", "a.py"], cwd=history_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=history_repo,
        check=True,
        capture_output=True,
    )

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield history_repo

    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    with caplog.at_level("INFO", logger="app.main"):
        create_resp = client.post(
            "/jobs",
            json={"repo_url": "https://github.com/example/example"},
            headers={"X-Request-ID": "caller-supplied-id-456"},
        )
    job_id = create_resp.json()["job_id"]

    timing_records = [r for r in caplog.records if "stage timings" in r.getMessage()]
    assert len(timing_records) == 1
    assert job_id in timing_records[0].getMessage()
    assert "total" in timing_records[0].getMessage()
    # The job runs on a background thread, decoupled from the Request that
    # queued it -- this is the regression check that request_id still
    # threads through so a job's completion log correlates back to the
    # POST /jobs request that started it (see FAQ.md's observability
    # limitations, which previously listed this as a known gap).
    assert "request_id=caller-supplied-id-456" in timing_records[0].getMessage()


def test_job_records_error_on_clone_failure(monkeypatch, tmp_path):
    from app.cloner import CloneError

    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    @contextmanager
    def failing_clone(url, depth=500, timeout=120):
        raise CloneError("repository not found")
        yield  # pragma: no cover

    monkeypatch.setattr("app.report_pipeline.clone_with_history", failing_clone)
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/does-not-exist"})
    job_id = create_resp.json()["job_id"]

    status_resp = client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "error"
    assert body["error"] == "repository not found"
    assert body["markdown"] is None


# --- v1.3 Engineering Advisor Suite endpoints -------------------------------


def _fastapi_fixture_repo(tmp_path):
    combined_repo = tmp_path / "combined_repo"
    shutil.copytree(FIXTURES / "fastapi_repo", combined_repo)
    subprocess.run(["git", "init"], cwd=combined_repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=combined_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=combined_repo,
        check=True,
        capture_output=True,
    )
    return combined_repo


def test_technical_debt_endpoint_returns_expected_shape(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post("/technical-debt", json={"repo_url": "https://github.com/example/example"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"average_debt_score", "top_debt_modules", "recommended_refactoring_order"}


def test_technical_debt_endpoint_rejects_invalid_url():
    resp = client.post("/technical-debt", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400


def test_performance_analysis_endpoint_returns_expected_shape(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post("/performance-analysis", json={"repo_url": "https://github.com/example/example"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"findings", "bottleneck_modules"}


def test_performance_analysis_endpoint_rejects_invalid_url():
    resp = client.post("/performance-analysis", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400


def test_ai_architect_repository_overview_returns_deterministic_explanation(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)
    monkeypatch.delenv("ATLAS_ANTHROPIC_API_KEY", raising=False)

    resp = client.post(
        "/ai-architect",
        json={"repo_url": "https://github.com/example/example", "prompt_kind": "repository_overview"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "deterministic"
    assert "Overall score" in body["text"]
    assert body["grounded_in"]


def test_ai_architect_rejects_unknown_prompt_kind(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post(
        "/ai-architect",
        json={"repo_url": "https://github.com/example/example", "prompt_kind": "not_a_real_kind"},
    )

    assert resp.status_code == 400


def test_ai_architect_file_scoped_kind_requires_file(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post(
        "/ai-architect",
        json={"repo_url": "https://github.com/example/example", "prompt_kind": "hotspot_explanation"},
    )

    assert resp.status_code == 400


def test_ai_architect_file_scoped_kind_refuses_when_module_not_flagged(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post(
        "/ai-architect",
        json={
            "repo_url": "https://github.com/example/example",
            "prompt_kind": "hotspot_explanation",
            "file": "definitely_not_a_real_file.py",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "deterministic"
    assert "Insufficient evidence" in body["text"]
    assert body["grounded_in"] == []


def test_ai_mentor_refuses_finding_atlas_did_not_flag(tmp_path, monkeypatch):
    repo = _fastapi_fixture_repo(tmp_path)

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield repo

    monkeypatch.setattr("app.main.clone_with_history", fake_clone_with_history)

    resp = client.post(
        "/ai-mentor",
        json={
            "repo_url": "https://github.com/example/example",
            "finding_file": "definitely_not_a_real_file.py",
            "finding_kind": "not_a_real_kind",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "deterministic"
    assert "Insufficient evidence" in body["text"]
    assert "did not flag" in body["text"]


def test_ai_mentor_explains_a_finding_atlas_actually_flagged(tmp_path, monkeypatch):
    repo = tmp_path / "repo_with_issue"
    repo.mkdir()
    (repo / "danger.py").write_text("import os\n\ndef run(cmd):\n    os.system(cmd)\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
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
    monkeypatch.delenv("ATLAS_ANTHROPIC_API_KEY", raising=False)

    resp = client.post(
        "/ai-mentor",
        json={
            "repo_url": "https://github.com/example/example",
            "finding_file": "danger.py",
            "finding_kind": "dangerous_execution",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "deterministic"
    assert "dangerous_execution" in body["text"]
    assert "danger.py" in body["text"]
