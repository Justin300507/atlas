from pathlib import Path

import networkx as nx

from app.code_parser import FileSymbols, FunctionInfo
from app.quality_engine import analyze_quality


def _clean_file(path: str) -> FileSymbols:
    return FileSymbols(
        path=path,
        language="python",
        functions=[FunctionInfo(name="ok", start_line=1, end_line=5, branch_count=1)],
        class_names=["Widget"],
    )


def test_clean_repo_scores_100():
    files = [_clean_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.overall_score == 100
    assert report.maintainability_score == 100
    assert report.architecture_score == 100
    assert report.issues == []


def test_small_circular_dependency_cluster_penalized_and_classified_minor():
    files = [_clean_file("a.py"), _clean_file("b.py")]
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")

    report = analyze_quality(files, graph)

    # 1 cluster (-10) + largest-cluster-size penalty (2 modules * 2 = 4) +
    # participation penalty (100% of modules entangled * 30) = 100 - 44 = 56.
    assert report.architecture_score == 56
    assert report.overall_score == round((100 + 56) / 2)
    circular_issues = [i for i in report.issues if i.kind == "circular_import"]
    assert len(circular_issues) == 1
    assert circular_issues[0].severity == "minor"


def test_densely_connected_cluster_reported_as_one_cluster_not_many_cycles():
    # Regression test: a real-repo validation run against pallets/flask and
    # tiangolo/typer found that enumerating simple cycles (nx.simple_cycles)
    # turns one real "these modules are mutually entangled" fact into tens of
    # thousands of individual cycle enumerations once a strongly connected
    # component exists — a fully-connected 4-node cluster alone produces many
    # distinct simple cycles, but it is still exactly one entangled cluster.
    nodes = ["a.py", "b.py", "c.py", "d.py"]
    files = [_clean_file(n) for n in nodes]
    graph = nx.DiGraph()
    for n in nodes:
        graph.add_node(n, type="module")
    for u in nodes:
        for v in nodes:
            if u != v:
                graph.add_edge(u, v, type="import")

    report = analyze_quality(files, graph)

    circular_issues = [i for i in report.issues if i.kind == "circular_import"]
    assert len(circular_issues) == 1
    assert report.architecture_score == 52


def test_large_circular_dependency_cluster_classified_critical_and_message_capped():
    nodes = [f"mod_{i:02d}.py" for i in range(25)]
    files = [_clean_file(n) for n in nodes]
    graph = nx.DiGraph()
    for n in nodes:
        graph.add_node(n, type="module")
    for i in range(25):
        graph.add_edge(nodes[i], nodes[(i + 1) % 25], type="import")

    report = analyze_quality(files, graph)

    circular_issues = [i for i in report.issues if i.kind == "circular_import"]
    assert len(circular_issues) == 1
    issue = circular_issues[0]
    assert issue.severity == "critical"
    assert "Circular dependency cluster of 25 modules" in issue.message
    assert "and 5 more" in issue.message
    assert report.architecture_score == 20


def test_circular_dependency_message_relativizes_paths_given_repo_root():
    # Regression test: a real browser-driven validation run against
    # tiangolo/typer found the cluster message embedding full absolute local
    # temp-clone paths (e.g. "C:\Users\...\atlas-clone-xyz\typer\core.py")
    # straight into the user-facing report, since analyze_quality had no
    # repo_root to relativize with — unlike graph_builder/doc_generator, which
    # already relativize everywhere they can.
    repo_root = Path("/repo")
    a = str(repo_root / "a.py")
    b = str(repo_root / "b.py")
    files = [_clean_file(a), _clean_file(b)]
    graph = nx.DiGraph()
    graph.add_node(a, type="module")
    graph.add_node(b, type="module")
    graph.add_edge(a, b, type="import")
    graph.add_edge(b, a, type="import")

    report = analyze_quality(files, graph, repo_root=repo_root)

    circular_issue = next(i for i in report.issues if i.kind == "circular_import")
    assert str(repo_root) not in circular_issue.message
    assert "a.py" in circular_issue.message
    assert "b.py" in circular_issue.message


def test_long_function_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="huge", start_line=1, end_line=60, branch_count=0)],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 95
    kinds = {issue.kind for issue in report.issues}
    assert "long_function" in kinds


def test_high_complexity_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="tangled", start_line=1, end_line=5, branch_count=11)],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 95
    kinds = {issue.kind for issue in report.issues}
    assert "high_complexity" in kinds


def test_naming_violations_detected_and_penalized():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[FunctionInfo(name="BadName", start_line=1, end_line=2, branch_count=0)],
            class_names=["lowercase_class"],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    # 2 naming violations (1 function, 1 class) out of 2 naming candidates:
    # rate = 2 / (2 + 20 smoothing) = 0.0909, * 60 weight = 5.45 -> rounds to
    # 5 -> 100 - 5 = 95. See the quality-score-normalization design doc.
    assert report.maintainability_score == 95
    kinds = [issue.kind for issue in report.issues]
    assert kinds.count("naming_convention") == 2


def test_architecture_score_heavily_penalized_but_not_floored_with_many_small_clusters():
    # Regression test for the 2026-07-24 real-world validation finding: the
    # old formula used an uncapped `len(clusters) * 10` term, which alone put
    # Django (17 clusters in a 1511-module repo) at architecture_score == 0,
    # indistinguishable from a repo that's actually maximally bad. This
    # fixture (20 tiny 2-module clusters, 100% of a 40-module repo entangled)
    # is genuinely bad and should score low -- but the cluster *count* term is
    # now capped at 40, so it no longer single-handedly floors the score; the
    # already-correct largest-cluster-size and participation-ratio terms
    # still apply on top. 40 (count, capped) + 4 (largest cluster: 2*2) + 30
    # (100% participation) = 74 -> score 26.
    files = []
    graph = nx.DiGraph()
    for i in range(20):
        a, b = f"c{i}_a.py", f"c{i}_b.py"
        files.append(_clean_file(a))
        files.append(_clean_file(b))
        graph.add_node(a, type="module")
        graph.add_node(b, type="module")
        graph.add_edge(a, b, type="import")
        graph.add_edge(b, a, type="import")

    report = analyze_quality(files, graph)

    assert report.architecture_score == 26


def test_architecture_score_not_floored_by_cluster_count_alone_in_large_repo():
    # The actual bug found in production: a large repo (here, 1000 modules)
    # with a modest number of small, unrelated circular-import clusters (15,
    # roughly Django's real proportion) must not floor at 0 just because
    # cluster *count* exceeds ~10 -- that was true regardless of how tiny a
    # fraction of the repo those clusters actually touched.
    files = []
    graph = nx.DiGraph()
    for i in range(1000):
        node = f"mod_{i:04d}.py"
        files.append(_clean_file(node))
        graph.add_node(node, type="module")
    for i in range(15):
        a, b = f"mod_{i * 2:04d}.py", f"mod_{i * 2 + 1:04d}.py"
        graph.add_edge(a, b, type="import")
        graph.add_edge(b, a, type="import")

    report = analyze_quality(files, graph)

    # 40 (cluster count, capped) + 4 (largest cluster: 2*2) + 1 (participation
    # ratio: 30/1000 = 3% * 30) = 45 -> score 55. Meaningfully differentiated
    # from 0 (the old, wrong result), even though the count-cap alone still
    # costs 40 points -- that's a separate, real limitation noted as a known
    # follow-up rather than fixed here (see commit/PR notes).
    assert report.architecture_score == 55


def test_architecture_score_still_floors_at_zero_when_genuinely_maximally_bad():
    # A repo that's bad on all three dimensions at once (many clusters, a
    # large largest-cluster, near-total participation) should still be able
    # to floor at 0 -- capping the cluster-count term doesn't mean 0 is
    # unreachable, only that cluster count alone can't reach it.
    files = []
    graph = nx.DiGraph()
    for c in range(5):
        nodes = [f"c{c}_{i:02d}.py" for i in range(20)]
        for n in nodes:
            files.append(_clean_file(n))
            graph.add_node(n, type="module")
        for i in range(20):
            graph.add_edge(nodes[i], nodes[(i + 1) % 20], type="import")

    report = analyze_quality(files, graph)

    assert report.architecture_score == 0


def test_scores_never_go_below_zero():
    files = [
        FileSymbols(
            path="app/main.py",
            language="python",
            functions=[
                FunctionInfo(name="Bad" * 10, start_line=1, end_line=200, branch_count=50)
                for _ in range(50)
            ],
        )
    ]
    graph = nx.DiGraph()
    graph.add_node("app/main.py", type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score == 0
    assert report.overall_score >= 0


def test_maintainability_score_not_floored_by_issue_count_alone_in_large_repo():
    # Regression test for the 2026-07-24 real-world validation finding:
    # maintainability_score was 0/100 for Django, FastAPI, React, and Flask
    # -- every real repo tested except the smallest -- because flat per-issue
    # points with no cap or size-normalization guarantee any repo with a
    # couple hundred functions floors at 0. Here, 1000 functions with a
    # modest 5% long-function rate and 5% high-complexity rate (50 issues
    # each) must not zero out a codebase that's 95% clean.
    files = []
    for i in range(1000):
        is_long = i % 20 == 0  # 5%
        is_complex = i % 20 == 1  # another 5%
        files.append(
            FileSymbols(
                path=f"app/mod_{i:04d}.py",
                language="python",
                functions=[
                    FunctionInfo(
                        name="ok",
                        start_line=1,
                        end_line=60 if is_long else 5,
                        branch_count=11 if is_complex else 1,
                    )
                ],
            )
        )
    graph = nx.DiGraph()
    for f in files:
        graph.add_node(f.path, type="module")

    report = analyze_quality(files, graph)

    assert report.maintainability_score > 85
