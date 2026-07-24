import networkx as nx

from app.code_parser import FileSymbols, FunctionInfo
from app.git_log_parser import Commit, FileChange
from app.models import QualityIssue, QualityReport
from app.semantic_analysis import _MAX_MODULES_FOR_BETWEENNESS, analyze_semantics


def _file(path: str, functions: int = 0) -> FileSymbols:
    return FileSymbols(
        path=path,
        language="python",
        functions=[
            FunctionInfo(name=f"fn{i}", start_line=i, end_line=i + 1, branch_count=1)
            for i in range(functions)
        ],
    )


def _empty_quality() -> QualityReport:
    return QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[])


def test_fan_in_and_fan_out_computed_from_import_edges_only():
    graph = nx.DiGraph()
    for n in ("a.py", "b.py", "c.py", "d.py"):
        graph.add_node(n, type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("c.py", "b.py", type="import")
    # a.py needs its own fan-in too, or it has zero criticality score (no
    # fan-in) and won't appear in critical_modules at all -- ranking is
    # fan-in-weighted by design (see design spec: "which modules would
    # have highest impact if changed" is about who depends on you, not
    # who you depend on).
    graph.add_edge("d.py", "a.py", type="import")

    files = [_file(n) for n in ("a.py", "b.py", "c.py", "d.py")]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    critical = {m.file: m for m in report.critical_modules}
    assert critical["b.py"].fan_in == 2
    assert critical["a.py"].fan_out == 1


def test_route_edges_excluded_from_module_metrics():
    graph = nx.DiGraph()
    graph.add_node("app.py", type="module")
    graph.add_node("route:GET /x", type="route")
    graph.add_edge("app.py", "route:GET /x", type="route")

    files = [_file("app.py")]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.architecture_health.module_count == 1
    assert report.architecture_health.import_edge_count == 0
    assert report.critical_modules == []


def test_articulation_point_and_bridge_detected_on_a_connector_module():
    # a-b-c-d chain: b and c are cut vertices, every edge is a bridge.
    graph = nx.DiGraph()
    for n in ("a.py", "b.py", "c.py", "d.py"):
        graph.add_node(n, type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "c.py", type="import")
    graph.add_edge("c.py", "d.py", type="import")

    files = [_file(n) for n in ("a.py", "b.py", "c.py", "d.py")]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.architecture_health.articulation_point_count == 2
    assert report.architecture_health.bridge_count == 3


def test_betweenness_skipped_above_module_count_ceiling(monkeypatch):
    import app.semantic_analysis as sa

    monkeypatch.setattr(sa, "_MAX_MODULES_FOR_BETWEENNESS", 1)

    graph = nx.DiGraph()
    for n in ("a.py", "b.py", "c.py"):
        graph.add_node(n, type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "c.py", type="import")

    files = [_file(n) for n in ("a.py", "b.py", "c.py")]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.architecture_health.betweenness_computed is False
    assert all(m.betweenness == 0.0 for m in report.critical_modules)


def test_real_ceiling_constant_is_unchanged_by_default():
    # Guards against silently loosening/tightening the measured constant
    # without updating the design spec's rationale alongside it.
    assert _MAX_MODULES_FOR_BETWEENNESS == 3000


def test_critical_modules_ranks_fan_in_weighted_betweenness_above_plain_fan_in():
    # star: hub has fan_in 3 from leaves, chain: mid has fan_in 1 but sits
    # on the only path between two other modules (higher betweenness).
    graph = nx.DiGraph()
    for n in ("l1.py", "l2.py", "l3.py", "hub.py", "x.py", "mid.py", "y.py"):
        graph.add_node(n, type="module")
    graph.add_edge("l1.py", "hub.py", type="import")
    graph.add_edge("l2.py", "hub.py", type="import")
    graph.add_edge("l3.py", "hub.py", type="import")
    graph.add_edge("x.py", "mid.py", type="import")
    graph.add_edge("mid.py", "y.py", type="import")

    files = [_file(n) for n in graph.nodes]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    top_file = report.critical_modules[0].file
    assert top_file == "hub.py"


def test_layer_detection_matches_directory_vocabulary_with_confidence():
    graph = nx.DiGraph()
    paths = ["api/routes.py", "services/handler.py", "domain/models.py"]
    for p in paths:
        graph.add_node(p, type="module")

    files = [_file(p) for p in paths]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.subsystem_overview.confident is True
    assert report.subsystem_overview.layer_counts == {"api": 1, "service": 1, "domain": 1}


def test_layer_detection_does_not_guess_below_confidence_threshold():
    graph = nx.DiGraph()
    paths = ["core/engine.py", "lib/helpers.py", "misc/thing.py"]
    for p in paths:
        graph.add_node(p, type="module")

    files = [_file(p) for p in paths]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.subsystem_overview.confident is False
    assert report.subsystem_overview.coverage_ratio == 0.0
    assert report.subsystem_overview.layer_counts == {}


def test_layering_violation_reported_only_when_layer_detection_is_confident():
    graph = nx.DiGraph()
    paths = [
        "presentation/view.py",
        "api/routes.py",
        "services/logic.py",
        "domain/model.py",
        "infrastructure/adapter.py",
        "persistence/repo.py",
    ]
    for p in paths:
        graph.add_node(p, type="module")
    # persistence importing presentation -- backwards per the canonical order.
    graph.add_edge("persistence/repo.py", "presentation/view.py", type="import")

    files = [_file(p) for p in paths]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.subsystem_overview.confident is True
    violations = [s for s in report.architectural_smells if s.kind == "layering_violation"]
    assert len(violations) == 1
    assert violations[0].file == "persistence/repo.py"


def test_no_layering_violations_reported_when_confidence_is_insufficient():
    graph = nx.DiGraph()
    paths = ["a/one.py", "b/two.py"]
    for p in paths:
        graph.add_node(p, type="module")
    graph.add_edge("a/one.py", "b/two.py", type="import")

    files = [_file(p) for p in paths]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert not any(s.kind == "layering_violation" for s in report.architectural_smells)


def test_hotspot_requires_churn_centrality_and_complexity_all_present():
    graph = nx.DiGraph()
    for n in ("hot.py", "cold.py", "central_only.py"):
        graph.add_node(n, type="module")
    graph.add_edge("cold.py", "hot.py", type="import")
    graph.add_edge("cold.py", "central_only.py", type="import")

    files = [_file("hot.py"), _file("cold.py"), _file("central_only.py")]
    quality = QualityReport(
        overall_score=90,
        maintainability_score=90,
        architecture_score=100,
        issues=[
            QualityIssue(file="hot.py", line=1, kind="high_complexity", message="x", severity="important"),
            QualityIssue(file="central_only.py", line=1, kind="high_complexity", message="x", severity="important"),
        ],
    )
    commits = [Commit(hash="h1", author_email="a@x.com", message="fix", files=[FileChange(path="hot.py", additions=1, deletions=1)])]

    report = analyze_semantics(files, graph, quality, commits)

    hotspot_files = {h.file for h in report.hotspots}
    assert "hot.py" in hotspot_files
    # central_only.py has centrality + complexity but zero churn -- must not
    # appear, per the "hotspot means actively risky" rule.
    assert "central_only.py" not in hotspot_files


def test_god_module_requires_both_high_fan_out_and_size():
    graph = nx.DiGraph()
    targets = [f"t{i}.py" for i in range(20)]
    sink = "sink.py"
    graph.add_node("big.py", type="module")
    graph.add_node(sink, type="module")
    for i, t in enumerate(targets):
        graph.add_node(t, type="module")
        graph.add_edge("big.py", t, type="import")
        # Half the targets import a shared sink -- realistic background
        # variance in fan-out, without which every non-"big" node has
        # fan_out exactly 0 and the 95th percentile degenerates to 0 too
        # (see test_sparse_repo_with_no_variance_reports_no_coupling_findings
        # for that scenario tested as its own, intentional behavior).
        if i % 2 == 0:
            graph.add_edge(t, sink, type="import")

    files = [_file("big.py", functions=20)] + [_file(t) for t in targets] + [_file(sink)]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    god_modules = [c for c in report.coupling_issues if c.kind == "god_module"]
    assert any(c.file == "big.py" for c in god_modules)


def test_sparse_repo_with_no_variance_reports_no_coupling_findings():
    # 10 modules with fan_out=0, one with fan_out=20 -- 91% of the data
    # sits at the floor, so every percentile up to roughly the 90th is
    # itself 0. Deliberately not flagging anything here rather than
    # treating "fan_out >= 0" as a threshold: a repo this sparse has no
    # real variance to rank against, and the "never guess" principle
    # applies to coupling analysis as much as layer detection.
    graph = nx.DiGraph()
    targets = [f"t{i}.py" for i in range(20)]
    graph.add_node("big.py", type="module")
    for t in targets:
        graph.add_node(t, type="module")
        graph.add_edge("big.py", t, type="import")

    files = [_file("big.py", functions=20)] + [_file(t) for t in targets]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.coupling_issues == []


def test_isolated_component_has_zero_fan_in_and_fan_out():
    graph = nx.DiGraph()
    graph.add_node("connected.py", type="module")
    graph.add_node("orphan.py", type="module")
    graph.add_node("other.py", type="module")
    graph.add_edge("connected.py", "other.py", type="import")

    files = [_file("connected.py"), _file("orphan.py"), _file("other.py")]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    isolated = [s for s in report.architectural_smells if s.kind == "isolated_component"]
    assert any(s.file == "orphan.py" for s in isolated)


def test_facade_pattern_detected_for_init_file_with_high_fan_in_low_fan_out():
    graph = nx.DiGraph()
    importers = [f"caller{i}.py" for i in range(8)]
    graph.add_node("pkg/__init__.py", type="module")
    for c in importers:
        graph.add_node(c, type="module")
        graph.add_edge(c, "pkg/__init__.py", type="import")
    # Unrelated chain purely to give fan_in/fan_out some background
    # variance -- without it, everything but __init__.py sits at exactly
    # 0/1 and the percentile thresholds degenerate (see
    # test_sparse_repo_with_no_variance_reports_no_coupling_findings for
    # that scenario as its own intentional, tested behavior).
    for a, b in [("x1.py", "x2.py"), ("x1.py", "x3.py"), ("x2.py", "x3.py"), ("x3.py", "x4.py")]:
        graph.add_node(a, type="module")
        graph.add_node(b, type="module")
        graph.add_edge(a, b, type="import")

    files = (
        [_file("pkg/__init__.py")]
        + [_file(c) for c in importers]
        + [_file(n) for n in ("x1.py", "x2.py", "x3.py", "x4.py")]
    )
    report = analyze_semantics(files, graph, _empty_quality(), [])

    facades = [s for s in report.architectural_smells if s.kind == "facade_pattern"]
    assert any(s.file == "pkg/__init__.py" for s in facades)


def test_dependency_concentration_is_repo_level_not_a_finding():
    graph = nx.DiGraph()
    graph.add_node("hub.py", type="module")
    graph.add_node("leaf.py", type="module")
    graph.add_edge("leaf.py", "hub.py", type="import")

    files = [_file("hub.py"), _file("leaf.py")]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    assert report.architecture_health.dependency_concentration_top5_ratio == 1.0


def test_circular_cluster_count_reused_from_quality_report_not_recomputed():
    graph = nx.DiGraph()
    graph.add_node("a.py", type="module")
    graph.add_node("b.py", type="module")
    graph.add_edge("a.py", "b.py", type="import")
    graph.add_edge("b.py", "a.py", type="import")

    quality = QualityReport(
        overall_score=50,
        maintainability_score=100,
        architecture_score=0,
        issues=[
            QualityIssue(file="a.py", line=0, kind="circular_import", message="cycle", severity="minor")
        ],
    )
    files = [_file("a.py"), _file("b.py")]
    report = analyze_semantics(files, graph, quality, [])

    assert report.architecture_health.circular_cluster_count == 1


def test_layer_edges_aggregate_import_counts_between_layers():
    graph = nx.DiGraph()
    paths = ["api/routes.py", "api/other.py", "services/logic.py", "domain/model.py"]
    for p in paths:
        graph.add_node(p, type="module")
    graph.add_edge("api/routes.py", "services/logic.py", type="import")
    graph.add_edge("api/other.py", "services/logic.py", type="import")
    graph.add_edge("services/logic.py", "domain/model.py", type="import")

    files = [_file(p) for p in paths]
    report = analyze_semantics(files, graph, _empty_quality(), [])

    edges = {(e.from_layer, e.to_layer): e.edge_count for e in report.subsystem_overview.layer_edges}
    assert edges == {("api", "service"): 2, ("service", "domain"): 1}


def test_empty_repo_produces_an_empty_report_not_a_crash():
    graph = nx.DiGraph()
    report = analyze_semantics([], graph, _empty_quality(), [])

    assert report.architecture_health.module_count == 0
    assert report.critical_modules == []
    assert report.hotspots == []
    assert report.coupling_issues == []
    assert report.architectural_smells == []
