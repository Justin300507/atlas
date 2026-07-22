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
    assert "quality" in body
    assert "overall_score" in body["quality"]


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
    monkeypatch.setattr("app.main.parse_file", flaky_parse_file)

    resp = client.post("/analyze", json={"repo_url": "https://github.com/example/example"})
    assert resp.status_code == 200
    body = resp.json()
    node_ids = {n["id"] for n in body["graph"]["nodes"]}
    assert str(good_file) in node_ids
    assert str(bad_file) not in node_ids
    assert "quality" in body
    assert "overall_score" in body["quality"]


def test_analyze_skips_oversized_file_and_keeps_others(monkeypatch, tmp_path):
    from app.main import _MAX_FILE_SIZE_BYTES

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


def test_analyze_stops_walking_after_max_file_count(monkeypatch, tmp_path):
    for i in range(5):
        (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")

    monkeypatch.setattr("app.main._MAX_FILES_PER_REPO", 2)

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
