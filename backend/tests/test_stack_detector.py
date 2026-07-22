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
