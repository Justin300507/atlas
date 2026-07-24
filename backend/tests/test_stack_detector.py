from pathlib import Path

from app.stack_detector import detect

FIXTURES = Path(__file__).parent / "fixtures"


def test_detects_fastapi_backend_and_docker_deployment():
    report = detect(FIXTURES / "fastapi_repo")
    assert report.backend == "FastAPI"
    assert report.deployment == "Docker"


def test_detects_react_vite_frontend():
    report = detect(FIXTURES / "react_vite_repo")
    assert report.frontend == "React + Vite"


def test_empty_repo_returns_unknown_stack():
    report = detect(FIXTURES / "empty_repo")
    assert report.backend is None
    assert report.frontend is None
    assert report.deployment is None


def test_detects_backend_manifest_one_level_into_a_subdirectory(tmp_path):
    # Regression test: a repo laid out as backend/ + frontend/ (Atlas's own
    # layout, and a common monorepo split) had its backend/requirements.txt
    # invisible to a root-only manifest check -- a real FastAPI backend
    # with 107 routes reported "Backend: Not detected" (2026-07-24).
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "requirements.txt").write_text("fastapi>=0.100\n")

    report = detect(tmp_path)

    assert report.backend == "FastAPI"


def test_merges_package_json_dependencies_from_a_subdirectory(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text('{"dependencies": {"react": "^18", "vite": "^5"}}')

    report = detect(tmp_path)

    assert report.frontend == "React + Vite"


def test_manifest_search_skips_excluded_directories(tmp_path):
    (tmp_path / "node_modules" / "some_pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "requirements.txt").write_text("fastapi\n")

    report = detect(tmp_path)

    assert report.backend is None
