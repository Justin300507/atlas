import pytest

from app.git_intelligence import analyze_git_history
from app.git_log_parser import Commit, FileChange


def test_empty_history_produces_empty_report():
    report = analyze_git_history([], history_truncated=False)

    assert report.commits_analyzed == 0
    assert report.churn == []
    assert report.ownership == []
    assert report.co_changes == []


def test_churn_counts_commits_per_file_descending():
    commits = [
        Commit("h1", "a@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h2", "a@x.com", "msg", [FileChange("a.py", 1, 0), FileChange("b.py", 1, 0)]),
        Commit("h3", "a@x.com", "msg", [FileChange("b.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    by_file = {c.file: c for c in report.churn}
    assert by_file["a.py"].commit_count == 2
    assert by_file["b.py"].commit_count == 2
    assert report.churn[0].commit_count >= report.churn[1].commit_count


def test_bug_fix_commits_counted_per_file():
    commits = [
        Commit("h1", "a@x.com", "fix bug in parser", [FileChange("a.py", 1, 0)]),
        Commit("h2", "a@x.com", "add feature", [FileChange("a.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    assert report.churn[0].commit_count == 2
    assert report.churn[0].bug_fix_count == 1


def test_ownership_picks_majority_author():
    commits = [
        Commit("h1", "alice@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h2", "alice@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h3", "bob@x.com", "msg", [FileChange("a.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    owner = report.ownership[0]
    assert owner.file == "a.py"
    assert owner.top_author == "alice@x.com"
    assert owner.top_author_commits == 2
    assert owner.total_commits == 3
    assert owner.ownership_ratio == pytest.approx(2 / 3)


def test_co_change_counts_all_pairs_in_multi_file_commit():
    commits = [
        Commit(
            "h1",
            "a@x.com",
            "msg",
            [FileChange("a.py", 1, 0), FileChange("b.py", 1, 0), FileChange("c.py", 1, 0)],
        )
    ]

    report = analyze_git_history(commits, history_truncated=False)

    pairs = {(p.file_a, p.file_b) for p in report.co_changes}
    assert len(report.co_changes) == 3
    assert ("a.py", "b.py") in pairs or ("b.py", "a.py") in pairs


def test_history_truncated_flag_passed_through():
    report = analyze_git_history([], history_truncated=True)
    assert report.history_truncated is True


def test_results_capped_at_20():
    commits = [
        Commit(f"h{i}", "a@x.com", "msg", [FileChange(f"file{i}.py", 1, 0)]) for i in range(30)
    ]

    report = analyze_git_history(commits, history_truncated=False)

    assert len(report.churn) == 20
    assert len(report.ownership) == 20
