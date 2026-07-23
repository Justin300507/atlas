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


def test_ownership_tie_breaks_to_first_author_encountered():
    commits = [
        Commit("h1", "alice@x.com", "msg", [FileChange("a.py", 1, 0)]),
        Commit("h2", "bob@x.com", "msg", [FileChange("a.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    owner = report.ownership[0]
    assert owner.top_author == "alice@x.com"
    assert owner.top_author_commits == 1
    assert owner.total_commits == 2
    assert owner.ownership_ratio == pytest.approx(0.5)


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


def test_bulk_commit_is_excluded_from_co_change_but_still_counts_churn_and_ownership():
    # A commit touching many files (an initial import, a mass rename) is a
    # one-time bulk event, not a "these files change together" signal --
    # and combinations(k, 2) on it is a real combinatorial-explosion risk
    # (verified: ~3,000 files in one commit produced ~4.9M pairs and a
    # multi-second, multi-GB-transient-memory spike in this project's own
    # load-testing benchmark).
    bulk_files = [FileChange(f"file{i}.py", 1, 0) for i in range(150)]
    commits = [
        Commit("h1", "a@x.com", "initial import", bulk_files),
        Commit("h2", "a@x.com", "small change", [FileChange("file0.py", 1, 0)]),
    ]

    report = analyze_git_history(commits, history_truncated=False)

    assert report.co_changes == []
    by_file = {c.file: c for c in report.churn}
    assert by_file["file0.py"].commit_count == 2
    assert by_file["file1.py"].commit_count == 1


def test_bulk_commit_co_change_skip_completes_quickly():
    # Regression test for the actual bug: this must not take anywhere near
    # as long as combinations(3000, 2) (~4.5M pairs) would.
    import time

    bulk_files = [FileChange(f"file{i}.py", 1, 0) for i in range(3000)]
    commits = [Commit("h1", "a@x.com", "initial import", bulk_files)]

    start = time.monotonic()
    report = analyze_git_history(commits, history_truncated=False)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0, f"took {elapsed:.2f}s -- co-change explosion likely regressed"
    assert report.co_changes == []


def test_co_change_still_computed_for_a_commit_at_exactly_the_threshold():
    files = [FileChange(f"file{i}.py", 1, 0) for i in range(100)]
    commits = [Commit("h1", "a@x.com", "msg", files)]

    report = analyze_git_history(commits, history_truncated=False)

    assert len(report.co_changes) > 0


def test_results_capped_at_20():
    commits = [
        Commit(f"h{i}", "a@x.com", "msg", [FileChange(f"file{i}.py", 1, 0)]) for i in range(30)
    ]

    report = analyze_git_history(commits, history_truncated=False)

    assert len(report.churn) == 20
    assert len(report.ownership) == 20
