import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.mark.slow
def test_analyze_real_public_repo_end_to_end():
    resp = client.post(
        "/analyze",
        json={"repo_url": "https://github.com/octocat/Hello-World"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "stack" in body
    assert "graph" in body
    assert isinstance(body["graph"]["nodes"], list)
