from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok_when_database_is_reachable():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ok"


def test_health_reports_degraded_when_database_is_unreachable(monkeypatch):
    def failing_count_active_jobs(*args, **kwargs):
        raise RuntimeError("disk full, path=C:\\secret\\install\\location\\atlas_jobs.db")

    monkeypatch.setattr("app.jobs.count_active_jobs", failing_count_active_jobs)

    resp = client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    # Only the exception type reaches the response body -- /health is
    # unauthenticated, so the full message (which can include a
    # filesystem path) must never leak into it.
    assert body["checks"]["database"] == "error: RuntimeError"
    assert "secret" not in body["checks"]["database"]
    assert "path=" not in body["checks"]["database"]
