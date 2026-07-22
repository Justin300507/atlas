from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient

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


def test_analyze_returns_422_on_clone_failure(monkeypatch):
    from app.cloner import CloneError

    @contextmanager
    def failing_clone(url, timeout=60):
        raise CloneError("repository not found")
        yield  # pragma: no cover

    monkeypatch.setattr("app.main.shallow_clone", failing_clone)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/does-not-exist"})
    assert resp.status_code == 422
