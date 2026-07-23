import subprocess
from contextlib import contextmanager
from pathlib import Path

from app.report_pipeline import analyze_structure, run_full_analysis

FIXTURES = Path(__file__).parent / "fixtures"


def test_analyze_structure_returns_stack_files_graph_and_quality():
    fixture = FIXTURES / "fastapi_repo"

    stack, files, graph, quality, security = analyze_structure(fixture)

    assert stack.backend == "FastAPI"
    assert len(files) > 0
    assert graph.number_of_nodes() > 0
    assert quality.overall_score == 100
    assert security.issues == []


def test_on_stage_called_with_every_stage_in_order(monkeypatch, tmp_path):
    # run_full_analysis clones once (via clone_with_history) and reuses that
    # single checkout for both structure and git-history analysis -- there's
    # no separate shallow_clone call to fake here anymore.
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

    stages_seen: list[str] = []
    response = run_full_analysis(
        "https://github.com/example/example", on_stage=stages_seen.append
    )

    assert stages_seen == [
        "cloning_structure",
        "parsing",
        "building_graph",
        "analyzing_quality",
        "scanning_security",
        "analyzing_git_history",
        "generating_documentation",
    ]
    assert "## Executive Summary" in response.markdown


def test_on_stage_is_optional(monkeypatch):
    fixture = FIXTURES / "fastapi_repo"

    @contextmanager
    def fake_clone_with_history(url, depth=500, timeout=120):
        yield fixture

    monkeypatch.setattr("app.report_pipeline.clone_with_history", fake_clone_with_history)

    response = run_full_analysis("https://github.com/example/example")

    assert "## Executive Summary" in response.markdown
