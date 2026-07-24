import subprocess
from contextlib import contextmanager
from pathlib import Path

from app import report_pipeline
from app.report_pipeline import analyze_structure, run_full_analysis

FIXTURES = Path(__file__).parent / "fixtures"


def test_analyze_structure_returns_stack_files_graph_and_quality():
    fixture = FIXTURES / "fastapi_repo"

    stack, files, graph, quality, security, coverage = analyze_structure(fixture)

    assert stack.backend == "FastAPI"
    assert len(files) > 0
    assert graph.number_of_nodes() > 0
    assert quality.overall_score == 100
    assert security.issues == []
    assert coverage.files_analyzed == len(files)
    assert coverage.files_capped is False
    assert coverage.files_skipped_oversized == 0
    assert coverage.files_parse_failed == 0


def test_analyze_structure_reports_unrecognized_framework_when_routes_are_found(tmp_path):
    # Regression test: a backend with real extracted routes but no
    # recognized manifest marker (unusual framework, or the manifest lives
    # somewhere stack_detector doesn't look) reported "Backend: Not
    # detected" despite Atlas having direct evidence of an HTTP backend.
    # Reported against a real repo (2026-07-24).
    (tmp_path / "app.py").write_text('@router.get("/items")\ndef items():\n    return []\n')

    stack, files, _graph, _quality, _security, _coverage = analyze_structure(tmp_path)

    assert files[0].routes == [("GET", "/items")]
    assert stack.backend == "Unrecognized framework (python HTTP routes detected, lower confidence -- no manifest match)"


def test_analyze_structure_reports_file_cap_hit(monkeypatch, tmp_path):
    # Regression test for the silent-truncation gap found during real-world
    # validation (2026-07-24): the file-count cap has existed since Phase 2
    # with no way to tell it was ever hit. Patch the cap down to something a
    # tiny fixture can actually exceed.
    monkeypatch.setattr(report_pipeline, "_MAX_FILES_PER_REPO", 3)
    for i in range(5):
        (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")

    _stack, files, _graph, _quality, _security, coverage = analyze_structure(tmp_path)

    assert coverage.files_capped is True
    assert coverage.files_analyzed == len(files) == 3


def test_non_source_files_do_not_count_toward_the_source_file_cap(monkeypatch, tmp_path):
    # Regression test for the real-world validation finding (2026-07-24):
    # Django's walk hit the cap at 5,000 total files with only 1,511 of its
    # 2,927 real .py files ever examined, because non-source files (docs,
    # translations, fixtures) were consuming the same budget as real source.
    monkeypatch.setattr(report_pipeline, "_MAX_FILES_PER_REPO", 3)
    for i in range(3):
        (tmp_path / f"mod_{i}.py").write_text(f"x = {i}\n")
    for i in range(20):
        (tmp_path / f"doc_{i}.md").write_text("# not source\n")
        (tmp_path / f"data_{i}.json").write_text("{}\n")

    _stack, files, _graph, _quality, _security, coverage = analyze_structure(tmp_path)

    assert coverage.files_capped is False
    assert coverage.files_analyzed == len(files) == 3


def test_total_entries_walked_ceiling_still_caps_a_pathological_non_source_tree(monkeypatch, tmp_path):
    # The source-only cap above removes the old blanket protection against a
    # repo with a huge non-source tree (e.g. committed binary assets) -- this
    # is the replacement circuit-breaker, independent of file type.
    monkeypatch.setattr(report_pipeline, "_MAX_TOTAL_ENTRIES_WALKED", 5)
    for i in range(20):
        (tmp_path / f"asset_{i}.bin").write_bytes(b"\x00")

    _stack, files, _graph, _quality, _security, coverage = analyze_structure(tmp_path)

    assert coverage.files_capped is True
    assert files == []


def test_excluded_directory_contents_do_not_count_toward_entries_walked_ceiling(monkeypatch, tmp_path):
    # Regression test caught in review (2026-07-24): the entries-walked
    # ceiling exists specifically to guard against a huge vendored/binary
    # tree, but node_modules is exactly such a tree and is also always
    # excluded -- if its contents still consumed the budget before the
    # exclusion check ran, a large committed node_modules or .git history
    # could trip the ceiling for the wrong reason, on a repo whose real
    # source tree is tiny and fully walkable.
    monkeypatch.setattr(report_pipeline, "_MAX_TOTAL_ENTRIES_WALKED", 5)
    node_modules = tmp_path / "node_modules"
    node_modules.mkdir()
    for i in range(20):
        (node_modules / f"pkg_{i}.js").write_text("module.exports = {};\n")
    (tmp_path / "app.py").write_text("x = 1\n")

    _stack, files, _graph, _quality, _security, coverage = analyze_structure(tmp_path)

    assert coverage.files_capped is False
    assert len(files) == 1


def test_analyze_structure_reports_oversized_files_skipped(monkeypatch, tmp_path):
    monkeypatch.setattr(report_pipeline, "_MAX_FILE_SIZE_BYTES", 10)
    (tmp_path / "small.py").write_text("x = 1\n")
    (tmp_path / "big.py").write_text("x = 1\n" * 100)

    _stack, files, _graph, _quality, _security, coverage = analyze_structure(tmp_path)

    assert coverage.files_skipped_oversized == 1
    assert coverage.files_capped is False
    assert len(files) == 1


def test_analyze_structure_reports_parse_failures_without_dropping_silently(monkeypatch, tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")

    def _boom(_path):
        raise ValueError("simulated parser crash")

    monkeypatch.setattr(report_pipeline, "parse_file", _boom)

    _stack, files, _graph, _quality, _security, coverage = analyze_structure(tmp_path)

    assert files == []
    assert coverage.files_parse_failed == 1


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
        "analyzing_semantics",
        "analyzing_technical_debt",
        "analyzing_performance",
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
