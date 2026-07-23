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
    structure_fixture = FIXTURES / "fastapi_repo"

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
    def fake_shallow_clone(url, timeout=60):
        yield structure_fixture

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield history_repo

    monkeypatch.setattr("app.report_pipeline.shallow_clone", fake_shallow_clone)
    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)

    resp = client.post("/documentation", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    markdown = resp.json()["markdown"]
    assert "## Executive Summary" in markdown
    assert "## API Reference" in markdown
    assert "/users" in markdown
    assert "Commits analyzed: 1" in markdown
    assert "a.py" in markdown.split("## Recent High-Churn Components")[1]


def test_documentation_rejects_invalid_url():
    resp = client.post("/documentation", json={"repo_url": "not-a-url"})
    assert resp.status_code == 400


def test_create_job_returns_202_with_job_id(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url: None)

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
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url: None)

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
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url: None)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/example"})
    job_id = create_resp.json()["job_id"]

    resp = client.get(f"/jobs/{job_id}")

    assert resp.status_code == 200
    assert resp.json()["created_at"]


def test_job_runs_synchronously_via_submit_override_and_reaches_done(monkeypatch, tmp_path):
    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    structure_fixture = FIXTURES / "fastapi_repo"
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
    def fake_shallow_clone(url, timeout=60):
        yield structure_fixture

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield history_repo

    monkeypatch.setattr("app.report_pipeline.shallow_clone", fake_shallow_clone)
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


def test_analyze_rejects_oversized_repo_url_payload():
    resp = client.post("/analyze", json={"repo_url": "x" * 301})
    assert resp.status_code == 422


def test_rate_limit_returns_429_with_retry_after_once_exceeded(monkeypatch, tmp_path):
    from app.rate_limiter import RateLimiter

    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url: None)
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
    monkeypatch.setattr("app.main._submit_job", lambda job_id, repo_url: None)
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


def test_job_records_error_on_clone_failure(monkeypatch, tmp_path):
    from app.cloner import CloneError

    monkeypatch.setattr("app.jobs.DEFAULT_DB_PATH", tmp_path / "jobs.db")

    @contextmanager
    def failing_clone(url, timeout=60):
        raise CloneError("repository not found")
        yield  # pragma: no cover

    monkeypatch.setattr("app.report_pipeline.shallow_clone", failing_clone)
    monkeypatch.setattr("app.main._submit_job", app_main._run_job)

    create_resp = client.post("/jobs", json={"repo_url": "https://github.com/example/does-not-exist"})
    job_id = create_resp.json()["job_id"]

    status_resp = client.get(f"/jobs/{job_id}")
    body = status_resp.json()

    assert body["status"] == "error"
    assert body["error"] == "repository not found"
    assert body["markdown"] is None
