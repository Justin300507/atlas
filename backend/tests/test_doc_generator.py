from pathlib import Path

import networkx as nx

from app.code_parser import FileSymbols
from app.doc_generator import generate_documentation
from app.models import (
    ArchitectureHealth,
    CouplingIssue,
    DebtModule,
    FileChurn,
    FileCoverage,
    GitIntelligenceReport,
    PerformanceFinding,
    PerformanceReport,
    QualityIssue,
    QualityReport,
    SecurityIssue,
    SecurityReport,
    SemanticReport,
    StackReport,
    SubsystemOverview,
    TechnicalDebtReport,
)

REPO_ROOT = Path("/repo")


def _file(rel_path: str, **kwargs) -> FileSymbols:
    return FileSymbols(path=str(REPO_ROOT / rel_path), language="python", **kwargs)


def _empty_quality() -> QualityReport:
    return QualityReport(overall_score=100, maintainability_score=100, architecture_score=100, issues=[])


def _empty_security() -> SecurityReport:
    return SecurityReport(issues=[])


def _empty_git() -> GitIntelligenceReport:
    return GitIntelligenceReport(
        commits_analyzed=0, history_truncated=False, churn=[], ownership=[], co_changes=[]
    )


def test_executive_summary_reports_stack_and_scores():
    stack = StackReport(backend="FastAPI", database="PostgreSQL")
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, stack, files, graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## Executive Summary" in doc
    assert "FastAPI" in doc
    assert "PostgreSQL" in doc
    assert "Files analyzed: 1" in doc
    assert "100" in doc


def test_executive_summary_discloses_security_findings_separately_from_quality_score():
    # Regression test: "Overall quality: 100/100" immediately followed by a
    # critical security finding read as contradictory to a real reader --
    # the score never included security, but nothing said so. Reported
    # against a real one-file repo (2026-07-24).
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")
    security = SecurityReport(
        issues=[
            SecurityIssue(file="app/main.py", line=1, kind="dangerous_execution", message="x", severity="critical")
        ]
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), security, _empty_git())

    assert "Overall quality score: 100/100" in doc
    assert "Security findings: 1 critical, 0 important, 0 minor -- not reflected in the score above" in doc


def test_executive_summary_reports_no_security_findings_when_clean():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [_file("app/main.py")], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    assert "Security findings: none detected -- not reflected in the score above" in doc


def test_executive_summary_health_line_has_no_qualifiers_when_clean():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [_file("app/main.py")], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        semantic=_single_module_semantic(),
    )

    assert "Repository health: Strong overall quality." in doc


def test_executive_summary_health_line_qualifies_good_score_with_real_risks():
    # Regression test: "Good overall quality" next to 3 circular-dependency
    # clusters and a god module read as contradictory -- the numeric-score
    # bucket alone doesn't reflect evidence shown elsewhere in the same
    # report. Reported (2026-07-24).
    quality = QualityReport(overall_score=72, maintainability_score=80, architecture_score=64, issues=[])
    semantic = SemanticReport(
        architecture_health=ArchitectureHealth(
            module_count=5, import_edge_count=8, circular_cluster_count=3,
            articulation_point_count=0, bridge_count=0, betweenness_computed=True,
            dependency_concentration_top5_ratio=0.5,
        ),
        critical_modules=[],
        subsystem_overview=SubsystemOverview(confident=False, coverage_ratio=0.0, layer_counts={}, layer_edges=[]),
        hotspots=[],
        coupling_issues=[
            CouplingIssue(file="main.py", kind="god_module", message="fan-out 39", severity="important"),
        ],
        architectural_smells=[],
    )
    debt = TechnicalDebtReport(
        average_debt_score=20.0,
        top_debt_modules=[
            DebtModule(file=f"m{i}.py", debt_score=score, category="coupling_smell", confidence="high", evidence=["x"])
            for i, score in enumerate([50.0, 30.0, 20.0, 5.0, 5.0])
        ],
        recommended_refactoring_order=[],
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git(),
        semantic=semantic, debt=debt,
    )

    assert (
        "Repository health: Good overall quality, with circular-dependency clusters, "
        "god-module coupling, concentrated technical debt." in doc
    )


def test_executive_summary_explains_architecture_score_scope_precisely():
    # Regression test: asked whether bridges/articulation points/coupling/
    # concentration/criticality feed into architecture_score -- verified
    # against quality_engine.py rather than guessed, and made explicit that
    # they don't (2026-07-24).
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    assert "circular-dependency clusters only" in doc
    assert "don't feed into this score" in doc


def test_executive_summary_omits_coverage_note_when_not_capped():
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")
    coverage = FileCoverage(
        files_analyzed=1, files_capped=False, files_skipped_oversized=0, files_parse_failed=0
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git(), coverage
    )

    assert "Files analyzed: 1\n" in doc


def test_executive_summary_surfaces_truncation_when_file_cap_hit():
    # Regression test for the silent-truncation gap found during real-world
    # validation (2026-07-24): a capped analysis must say so in the report
    # itself, not just in an internal field nobody reads.
    files = [_file("app/main.py")]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")
    coverage = FileCoverage(
        files_analyzed=5000, files_capped=True, files_skipped_oversized=12, files_parse_failed=3
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git(), coverage
    )

    assert "repository truncated at the file-count cap" in doc
    assert "12 skipped for exceeding the size limit" in doc
    assert "3 failed to parse" in doc


def test_api_reference_lists_routes_with_relative_paths():
    files = [_file("app/main.py", routes=[("GET", "/users"), ("POST", "/users")])]
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "app/main.py"), type="module")

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## API Reference" in doc
    assert "GET" in doc and "/users" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_api_reference_excludes_routes_from_test_and_fixture_paths():
    # Regression test: routes defined in test/fixture files (mock servers,
    # reliability harnesses) aren't part of the production API. Reported
    # against a real 440-file repo whose API Reference included
    # backend/tests/reliability/... routes (2026-07-24).
    files = [
        _file("app/main.py", routes=[("GET", "/users")]),
        _file("tests/reliability/mock_server.py", routes=[("GET", "/fake")]),
        _file("app/test_helpers.py", routes=[("POST", "/also-fake")]),
    ]
    graph = nx.DiGraph()

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git())

    section = doc.split("## API Reference")[1].split("## ")[0]
    assert "/users" in section
    assert "/fake" not in section
    assert "/also-fake" not in section
    assert "2 additional route(s) found only in test/fixture paths" in section


def test_api_reference_reports_no_production_routes_when_only_test_routes_exist():
    files = [_file("tests/mock_server.py", routes=[("GET", "/fake")])]
    graph = nx.DiGraph()

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git())

    section = doc.split("## API Reference")[1].split("## ")[0]
    assert "No production routes detected." in section
    assert "1 additional route(s)" in section


def test_directory_guide_groups_by_top_level_directory():
    files = [_file("app/main.py"), _file("app/utils.py"), _file("scripts/run.py")]
    graph = nx.DiGraph()

    doc = generate_documentation(REPO_ROOT, StackReport(), files, graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## Directory Guide" in doc
    assert "app" in doc
    assert "scripts" in doc


def test_architecture_overview_shows_size_note_for_single_module_repo():
    # Regression test: "Modules: 1 / Import edges: 0 / Routes: 0" isn't a
    # finding for a one-file repo, it's a guaranteed consequence of size.
    # Reported against a real one-file repo (2026-07-24).
    graph = nx.DiGraph()
    graph.add_node(str(REPO_ROOT / "only.py"), type="module")

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [_file("only.py")], graph, _empty_quality(), _empty_security(), _empty_git()
    )

    assert "## Architecture Overview" in doc
    assert "too small for meaningful architecture" in doc
    assert "Modules: 1" not in doc


def test_directory_guide_shows_sentence_not_table_for_single_directory():
    # Regression test: a one-row table ("." | 1) is the same fact as
    # "Files analyzed: 1" restated as a table -- not a breakdown. Reported
    # against a real one-file repo (2026-07-24).
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [_file("only.py")], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    assert "## Directory Guide" in doc
    assert "| Directory | Files |" not in doc
    assert "not enough directory structure for a breakdown" in doc


def test_architecture_overview_ranks_most_depended_upon_module():
    a = str(REPO_ROOT / "a.py")
    b = str(REPO_ROOT / "b.py")
    c = str(REPO_ROOT / "c.py")
    graph = nx.DiGraph()
    for n in (a, b, c):
        graph.add_node(n, type="module")
    graph.add_edge(a, c, type="import")
    graph.add_edge(b, c, type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## Architecture Overview" in doc
    assert "c.py" in doc


def test_risk_areas_lists_quality_issues_with_relative_paths():
    quality = QualityReport(
        overall_score=90,
        maintainability_score=85,
        architecture_score=95,
        issues=[
            QualityIssue(
                file=str(REPO_ROOT / "app/main.py"),
                line=10,
                kind="long_function",
                message="Function 'run' is 60 lines",
                severity="minor",
            )
        ],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git())

    assert "## Risk Areas" in doc
    assert "long_function" in doc
    assert "app/main.py" in doc
    assert str(REPO_ROOT) not in doc


def test_risk_areas_caps_at_20_with_overflow_note():
    # Regression test: a real-repo validation run produced tens of thousands
    # of quality issues before the circular-import scoring redesign, and
    # dumping all of them into the report produced tens of megabytes of
    # Markdown. Risk Areas must never render more than a bounded number of
    # findings inline.
    issues = [
        QualityIssue(file=f"app/mod_{i}.py", line=1, kind="long_function", message="x", severity="minor")
        for i in range(25)
    ]
    quality = QualityReport(overall_score=0, maintainability_score=0, architecture_score=100, issues=issues)

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git())

    section = doc.split("## Risk Areas")[1].split("## ")[0]
    assert section.count("mod_") == 20
    assert "and 5 additional findings" in section


def test_risk_areas_shows_by_kind_breakdown_when_overflowing():
    # Regression test: a real 440-file repo's report said "...and 576
    # additional findings" with no further structure -- a reader has no
    # way to tell whether that's 576 near-duplicates or 576 distinct
    # problems. Reported (2026-07-24).
    issues = [
        QualityIssue(file=f"app/mod_{i}.py", line=1, kind="long_function", message="x", severity="minor")
        for i in range(15)
    ] + [
        QualityIssue(file=f"app/mod_{i}.py", line=1, kind="high_complexity", message="x", severity="important")
        for i in range(10)
    ]
    quality = QualityReport(overall_score=0, maintainability_score=0, architecture_score=100, issues=issues)

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git())

    section = doc.split("## Risk Areas")[1].split("## ")[0]
    assert "25 findings across 2 categories" in section
    assert "long_function: 15" in section
    assert "high_complexity: 10" in section


def test_risk_areas_omits_breakdown_when_under_the_cap():
    issues = [
        QualityIssue(file="app/a.py", line=1, kind="long_function", message="x", severity="minor")
        for _ in range(3)
    ]
    quality = QualityReport(overall_score=90, maintainability_score=90, architecture_score=100, issues=issues)

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), quality, _empty_security(), _empty_git())

    section = doc.split("## Risk Areas")[1].split("## ")[0]
    assert "findings across" not in section


def test_security_findings_lists_issues_with_relative_paths():
    security = SecurityReport(
        issues=[
            SecurityIssue(
                file=str(REPO_ROOT / "app/config.py"),
                line=5,
                kind="hardcoded_secret",
                message="Hardcoded AWS access key detected",
                severity="critical",
            )
        ]
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), security, _empty_git()
    )

    assert "## Security Findings" in doc
    assert "hardcoded_secret" in doc
    assert "app/config.py" in doc
    assert str(REPO_ROOT) not in doc


def test_security_findings_reports_none_detected_when_clean():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    section = doc.split("## Security Findings")[1].split("## ")[0]
    assert "No issues detected." in section


def test_high_churn_section_lists_top_files_and_truncation_state():
    git_report = GitIntelligenceReport(
        commits_analyzed=500,
        history_truncated=True,
        churn=[FileChurn(file="app/main.py", commit_count=12, bug_fix_count=3)],
        ownership=[],
        co_changes=[],
    )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), git_report)

    assert "## Recent High-Churn Components" in doc
    assert "app/main.py" in doc
    assert "12" in doc
    assert "truncated" in doc.lower()


def test_dependency_diagram_caps_at_40_nodes_with_note():
    graph = nx.DiGraph()
    for i in range(45):
        graph.add_node(str(REPO_ROOT / f"mod_{i}.py"), type="module")
    for i in range(44):
        graph.add_edge(str(REPO_ROOT / f"mod_{i}.py"), str(REPO_ROOT / f"mod_{i + 1}.py"), type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    assert "## Dependency Diagram" in doc
    assert "```mermaid" in doc
    assert "capped for readability" in doc


def test_dependency_diagram_shows_system_overview_when_capped_and_cross_directory():
    # Regression test: fitting dozens of modules into one Mermaid diagram
    # becomes unreadable for large repos -- render a directory-level system
    # overview first. Reported against a real 440-file repo (2026-07-24).
    graph = nx.DiGraph()
    for i in range(45):
        subdir = "backend" if i % 2 == 0 else "frontend"
        graph.add_node(str(REPO_ROOT / subdir / f"mod_{i}.py"), type="module")
    for i in range(44):
        subdir_a = "backend" if i % 2 == 0 else "frontend"
        subdir_b = "backend" if (i + 1) % 2 == 0 else "frontend"
        graph.add_edge(
            str(REPO_ROOT / subdir_a / f"mod_{i}.py"),
            str(REPO_ROOT / subdir_b / f"mod_{i + 1}.py"),
            type="import",
        )

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    section = doc.split("## Dependency Diagram")[1]
    assert "**System Overview**" in section
    assert "**Detailed Module Diagram**" in section
    assert section.count("```mermaid") == 2
    assert '["backend"]' in section
    assert '["frontend"]' in section
    assert "Top-level directories with analyzed source modules" in section
    assert "`backend` (23)" in section
    assert "`frontend` (22)" in section


def test_dependency_diagram_system_overview_lists_directories_with_no_cross_edges_too():
    # Regression test: a directory with real analyzed files but zero
    # cross-directory import edges (e.g. a self-contained tests/ package)
    # was invisible in an edges-only overview. Reported against a real
    # 440-file repo: "expand it slightly to show key top-level
    # directories" (2026-07-24).
    graph = nx.DiGraph()
    for i in range(41):
        graph.add_node(str(REPO_ROOT / "backend" / f"mod_{i}.py"), type="module")
    for i in range(40):
        graph.add_edge(
            str(REPO_ROOT / "backend" / f"mod_{i}.py"),
            str(REPO_ROOT / "backend" / f"mod_{i + 1}.py"),
            type="import",
        )
    # A self-contained directory: real files, but no edges crossing out.
    for i in range(5):
        graph.add_node(str(REPO_ROOT / "tests" / f"test_{i}.py"), type="module")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    section = doc.split("## Dependency Diagram")[1]
    assert "`tests` (5)" in section
    assert "`backend` (41)" in section
    assert "No cross-directory import edges detected" in section


def test_dependency_diagram_omits_system_overview_when_not_capped():
    a = str(REPO_ROOT / "backend" / "a.py")
    b = str(REPO_ROOT / "frontend" / "b.py")
    graph = nx.DiGraph()
    graph.add_node(a, type="module")
    graph.add_node(b, type="module")
    graph.add_edge(a, b, type="import")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    section = doc.split("## Dependency Diagram")[1].split("## ")[0]
    assert "System Overview" not in section


def test_dependency_diagram_ranks_by_import_degree_not_route_degree():
    graph = nx.DiGraph()
    chain = [str(REPO_ROOT / f"mod_{i}.py") for i in range(40)]
    for node in chain:
        graph.add_node(node, type="module")
    for i in range(39):
        graph.add_edge(chain[i], chain[i + 1], type="import")

    route_heavy = str(REPO_ROOT / "route_heavy.py")
    graph.add_node(route_heavy, type="module")
    for i in range(20):
        route_id = f"route:GET /path{i}"
        graph.add_node(route_id, type="route")
        graph.add_edge(route_heavy, route_id, type="route")

    doc = generate_documentation(REPO_ROOT, StackReport(), [], graph, _empty_quality(), _empty_security(), _empty_git())

    assert "route_heavy.py" not in doc
    assert "mod_0.py" in doc
    assert "mod_39.py" in doc


def test_empty_repo_renders_without_crashing():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    for header in (
        "## Executive Summary",
        "## Architecture Overview",
        "## Directory Guide",
        "## API Reference",
        "## Dependency Diagram",
        "## Risk Areas",
        "## Security Findings",
        "## Recent High-Churn Components",
        "## Analysis Coverage",
        "## Executive Recommendations",
    ):
        assert header in doc


def _single_module_semantic() -> SemanticReport:
    return SemanticReport(
        architecture_health=ArchitectureHealth(
            module_count=1, import_edge_count=0, circular_cluster_count=0,
            articulation_point_count=0, bridge_count=0, betweenness_computed=True,
            dependency_concentration_top5_ratio=0.0,
        ),
        critical_modules=[],
        subsystem_overview=SubsystemOverview(confident=False, coverage_ratio=0.0, layer_counts={}, layer_edges=[]),
        hotspots=[],
        coupling_issues=[],
        architectural_smells=[],
    )


def test_architecture_health_shows_size_note_for_single_module_repo():
    # Regression test: dependency concentration ("top 5 modules receive 0%")
    # and the rest of Architecture Health are all trivially zero/undefined
    # for a one-module repo. Reported against a real one-file repo
    # (2026-07-24).
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [_file("only.py")], nx.DiGraph(), _empty_quality(), _empty_security(),
        _empty_git(), semantic=_single_module_semantic(),
    )

    assert "## Architecture Health" in doc
    assert "require more than one module" in doc
    assert "receive" not in doc.split("## Architecture Health")[1].split("##")[0]


def test_technical_debt_section_only_appears_when_debt_provided():
    without_debt = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )
    assert "## Technical Debt" not in without_debt

    debt = TechnicalDebtReport(
        average_debt_score=8.5,
        top_debt_modules=[
            DebtModule(
                file="hub.py", debt_score=8.5, category="coupling_smell",
                confidence="high", evidence=["flagged as a coupling issue"],
            )
        ],
        recommended_refactoring_order=["hub.py"],
    )
    with_debt = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        debt=debt,
    )
    assert "## Technical Debt" in with_debt
    assert "hub.py" in with_debt
    assert "8.50" in with_debt
    assert "flagged as a coupling issue" in with_debt


def test_performance_analysis_section_only_appears_when_performance_provided():
    without_perf = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )
    assert "## Performance Analysis" not in without_perf

    performance = PerformanceReport(
        findings=[
            PerformanceFinding(
                file="hub.py", line=10, kind="very_large_function",
                message="too big", confidence="high",
            )
        ],
        bottleneck_modules=["hub.py"],
    )
    with_perf = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        performance=performance,
    )
    assert "## Performance Analysis" in with_perf
    assert "hub.py:10" in with_perf
    assert "too big" in with_perf
    assert "Dependency bottlenecks" in with_perf


def test_performance_analysis_caps_findings_with_by_kind_breakdown_when_overflowing():
    # Regression test: a real 440-file repo's Performance Analysis section
    # spanned dozens of entries with no cap and no shape -- unlike Risk
    # Areas and Security Findings, which already capped. Reported (2026-07-24).
    findings = [
        PerformanceFinding(file=f"mod_{i}.py", line=1, kind="very_large_function", message="x", confidence="high")
        for i in range(15)
    ] + [
        PerformanceFinding(file=f"mod_{i}.py", line=1, kind="high_branch_count", message="x", confidence="low")
        for i in range(10)
    ]
    performance = PerformanceReport(findings=findings, bottleneck_modules=[])

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        performance=performance,
    )

    section = doc.split("## Performance Analysis")[1].split("## ")[0]
    assert "25 findings across 2 categories" in section
    assert "very_large_function: 15" in section
    assert section.count("mod_") == 20  # 20 shown bullets; breakdown lines name kinds, not files
    assert "and 5 additional findings" in section


def test_technical_debt_shows_concentration_note_when_more_than_three_modules():
    # Regression test: a 15-row debt table gave no sense of whether debt was
    # spread evenly or concentrated in a few modules. Reported against a
    # real 440-file repo (2026-07-24).
    modules = [
        DebtModule(file=f"m{i}.py", debt_score=score, category="coupling_smell", confidence="high", evidence=["x"])
        for i, score in enumerate([50.0, 30.0, 20.0, 5.0, 5.0])
    ]
    debt = TechnicalDebtReport(average_debt_score=22.0, top_debt_modules=modules, recommended_refactoring_order=[])

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(), debt=debt,
    )

    assert "The top 3 of the 5 modules shown account for 91% of their combined debt score." in doc


def test_technical_debt_omits_concentration_note_for_three_or_fewer_modules():
    modules = [
        DebtModule(file="a.py", debt_score=10.0, category="coupling_smell", confidence="high", evidence=["x"]),
    ]
    debt = TechnicalDebtReport(average_debt_score=10.0, top_debt_modules=modules, recommended_refactoring_order=[])

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(), debt=debt,
    )

    assert "account for" not in doc


def test_analysis_coverage_footer_discloses_support_and_limitations():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git()
    )

    assert "## Analysis Coverage" in doc
    assert "Python imports" in doc
    assert "ES Module" in doc
    assert "CommonJS" in doc
    assert "5,000 source files" in doc
    assert "Git history" in doc
    assert "Security scanning" in doc
    assert "can't be resolved statically" in doc
    assert "pattern-based" in doc
    assert "heuristic engineering signals" in doc


def test_executive_recommendations_says_so_when_nothing_flagged():
    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        semantic=_single_module_semantic(),
    )

    assert "## Executive Recommendations" in doc
    assert "No significant priorities identified" in doc


def test_executive_recommendations_synthesizes_debt_coupling_functions_and_cycles():
    # Regression test: requested a concluding action-plan section rather
    # than leaving the report a pure diagnostic dump. Every line here must
    # trace back to a finding already shown elsewhere -- no invented
    # judgment calls. Reported (2026-07-24).
    semantic = SemanticReport(
        architecture_health=ArchitectureHealth(
            module_count=5, import_edge_count=8, circular_cluster_count=3,
            articulation_point_count=0, bridge_count=0, betweenness_computed=True,
            dependency_concentration_top5_ratio=0.5,
        ),
        critical_modules=[],
        subsystem_overview=SubsystemOverview(confident=False, coverage_ratio=0.0, layer_counts={}, layer_edges=[]),
        hotspots=[],
        coupling_issues=[
            CouplingIssue(file="main.py", kind="god_module", message="fan-out 39 across 68 functions", severity="important"),
        ],
        architectural_smells=[],
    )
    debt = TechnicalDebtReport(
        average_debt_score=10.0,
        top_debt_modules=[
            DebtModule(file="patcher.py", debt_score=42.0, category="complexity_churn", confidence="high", evidence=["x"]),
        ],
        recommended_refactoring_order=["patcher.py"],
    )
    performance = PerformanceReport(
        findings=[
            PerformanceFinding(file="a.py", line=1, kind="very_large_function", message="x", confidence="high"),
            PerformanceFinding(file="b.py", line=1, kind="very_large_function", message="x", confidence="high"),
        ],
        bottleneck_modules=[],
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        semantic=semantic, debt=debt, performance=performance,
    )

    section = doc.split("## Executive Recommendations")[1]
    assert "patcher.py" in section
    assert "42.00" in section
    assert "main.py" in section
    assert "2 function(s) flagged as very large" in section
    assert "3 circular-dependency clusters" in section


def test_executive_recommendations_does_not_duplicate_a_file_already_named_for_debt():
    semantic = SemanticReport(
        architecture_health=ArchitectureHealth(
            module_count=1, import_edge_count=0, circular_cluster_count=0,
            articulation_point_count=0, bridge_count=0, betweenness_computed=True,
            dependency_concentration_top5_ratio=0.0,
        ),
        critical_modules=[],
        subsystem_overview=SubsystemOverview(confident=False, coverage_ratio=0.0, layer_counts={}, layer_edges=[]),
        hotspots=[],
        coupling_issues=[
            CouplingIssue(file="main.py", kind="god_module", message="fan-out 39", severity="important"),
        ],
        architectural_smells=[],
    )
    debt = TechnicalDebtReport(
        average_debt_score=10.0,
        top_debt_modules=[
            DebtModule(file="main.py", debt_score=10.0, category="coupling_smell", confidence="high", evidence=["x"]),
        ],
        recommended_refactoring_order=["main.py"],
    )

    doc = generate_documentation(
        REPO_ROOT, StackReport(), [], nx.DiGraph(), _empty_quality(), _empty_security(), _empty_git(),
        semantic=semantic, debt=debt,
    )

    section = doc.split("## Executive Recommendations")[1]
    assert section.count("main.py") == 1
