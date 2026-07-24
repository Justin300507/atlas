from app.code_parser import FileSymbols, FunctionInfo
from app.models import (
    ArchitectureHealth,
    CouplingIssue,
    CriticalModule,
    SemanticReport,
    SubsystemOverview,
)
from app.performance_analyzer import analyze_performance


def _semantic(**overrides) -> SemanticReport:
    defaults = dict(
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
    defaults.update(overrides)
    return SemanticReport(**defaults)


def test_clean_functions_produce_no_findings():
    files = [
        FileSymbols(
            path="a.py",
            language="python",
            functions=[FunctionInfo(name="ok", start_line=1, end_line=10, branch_count=2)],
        )
    ]

    report = analyze_performance(files, _semantic())

    assert report.findings == []


def test_very_large_function_flagged_but_a_merely_long_one_is_not():
    files = [
        FileSymbols(
            path="a.py",
            language="python",
            functions=[
                FunctionInfo(name="medium", start_line=1, end_line=100, branch_count=1),  # 100 lines: not flagged
                FunctionInfo(name="huge", start_line=200, end_line=400, branch_count=1),  # 201 lines: flagged
            ],
        )
    ]

    report = analyze_performance(files, _semantic())

    kinds_by_fn = {f.line: f.kind for f in report.findings}
    assert 200 in kinds_by_fn and kinds_by_fn[200] == "very_large_function"
    assert 1 not in kinds_by_fn


def test_high_branch_count_flagged_as_low_confidence_proxy():
    files = [
        FileSymbols(
            path="a.py",
            language="python",
            functions=[FunctionInfo(name="branchy", start_line=1, end_line=5, branch_count=30)],
        )
    ]

    report = analyze_performance(files, _semantic())

    finding = next(f for f in report.findings if f.kind == "high_branch_count")
    assert finding.confidence == "low"
    assert "not" in finding.message  # hedged, not asserted as measured nesting


def test_dependency_bottleneck_requires_both_criticality_and_coupling_flag():
    files: list[FileSymbols] = []
    semantic = _semantic(
        critical_modules=[
            CriticalModule(file="hub.py", fan_in=10, fan_out=2, betweenness=0.5, criticality_score=10.5),
            CriticalModule(file="central_but_clean.py", fan_in=8, fan_out=1, betweenness=0.3, criticality_score=8.3),
        ],
        coupling_issues=[
            CouplingIssue(file="hub.py", kind="god_module", message="x", severity="important"),
            CouplingIssue(file="unrelated.py", kind="excessive_fan_out", message="x", severity="minor"),
        ],
    )

    report = analyze_performance(files, semantic)

    assert report.bottleneck_modules == ["hub.py"]


def test_no_parameter_count_or_n_squared_findings_are_ever_produced():
    # Explicitly not implemented -- Atlas doesn't parse function
    # signatures or loop structure, so approximating either would be
    # evidence Atlas doesn't actually have.
    files = [
        FileSymbols(
            path="a.py",
            language="python",
            functions=[FunctionInfo(name="fn", start_line=1, end_line=300, branch_count=50)],
        )
    ]

    report = analyze_performance(files, _semantic())

    kinds = {f.kind for f in report.findings}
    assert "large_parameter_count" not in kinds
    assert "n_squared_pattern" not in kinds
    assert "repeated_imports" not in kinds
