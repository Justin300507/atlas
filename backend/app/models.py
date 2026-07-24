from __future__ import annotations

from pydantic import BaseModel, Field


class FileCoverage(BaseModel):
    files_analyzed: int
    files_capped: bool
    files_skipped_oversized: int
    files_parse_failed: int


class StackReport(BaseModel):
    backend: str | None = None
    frontend: str | None = None
    database: str | None = None
    auth: str | None = None
    deployment: str | None = None
    architecture: str | None = None


class GraphNode(BaseModel):
    id: str
    type: str


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class QualityIssue(BaseModel):
    file: str
    line: int
    kind: str
    message: str
    severity: str


class QualityReport(BaseModel):
    overall_score: int
    maintainability_score: int
    architecture_score: int
    issues: list[QualityIssue]


class SecurityIssue(BaseModel):
    file: str
    line: int
    kind: str
    message: str
    severity: str


class SecurityReport(BaseModel):
    issues: list[SecurityIssue]


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(max_length=300)


class AnalyzeResponse(BaseModel):
    stack: StackReport
    graph: GraphResponse
    quality: QualityReport
    security: SecurityReport
    coverage: FileCoverage


class FileChurn(BaseModel):
    file: str
    commit_count: int
    bug_fix_count: int


class FileOwnership(BaseModel):
    file: str
    top_author: str
    top_author_commits: int
    total_commits: int
    ownership_ratio: float


class CoChangePair(BaseModel):
    file_a: str
    file_b: str
    co_change_count: int


class GitIntelligenceReport(BaseModel):
    commits_analyzed: int
    history_truncated: bool
    churn: list[FileChurn]
    ownership: list[FileOwnership]
    co_changes: list[CoChangePair]


class ArchitectureHealth(BaseModel):
    module_count: int
    import_edge_count: int
    circular_cluster_count: int
    articulation_point_count: int
    bridge_count: int
    betweenness_computed: bool
    dependency_concentration_top5_ratio: float


class CriticalModule(BaseModel):
    file: str
    fan_in: int
    fan_out: int
    betweenness: float
    criticality_score: float


class LayerEdge(BaseModel):
    from_layer: str
    to_layer: str
    edge_count: int


class SubsystemOverview(BaseModel):
    confident: bool
    coverage_ratio: float
    layer_counts: dict[str, int]
    layer_edges: list[LayerEdge]


class EngineeringHotspot(BaseModel):
    file: str
    churn: int
    centrality: float
    complexity_issues: int
    hotspot_score: float


class CouplingIssue(BaseModel):
    file: str
    kind: str
    message: str
    severity: str


class ArchitecturalSmell(BaseModel):
    file: str
    kind: str
    message: str
    severity: str


class SemanticReport(BaseModel):
    architecture_health: ArchitectureHealth
    critical_modules: list[CriticalModule]
    subsystem_overview: SubsystemOverview
    hotspots: list[EngineeringHotspot]
    coupling_issues: list[CouplingIssue]
    architectural_smells: list[ArchitecturalSmell]


class DocumentationResponse(BaseModel):
    markdown: str
    snapshot: "AnalysisSnapshot | None" = None


# ---------------------------------------------------------------------------
# Repository Comparison (v1.2) -- see
# docs/superpowers/specs/2026-07-24-repository-comparison-design.md
# ---------------------------------------------------------------------------


class SnapshotSecuritySummary(BaseModel):
    critical_count: int
    important_count: int
    minor_count: int


class SnapshotGitSummary(BaseModel):
    commits_analyzed: int
    top_churn_files: list[str]


class SnapshotSemanticSummary(BaseModel):
    circular_cluster_count: int
    articulation_point_count: int
    dependency_concentration_top5_ratio: float
    critical_modules: list[str]
    hotspot_modules: list[str]
    coupling_issue_count: int
    smell_count: int


class SnapshotDebtSummary(BaseModel):
    average_debt_score: float
    top_debt_modules: list[str]


class SnapshotPerformanceSummary(BaseModel):
    finding_count: int
    bottleneck_modules: list[str]


class AnalysisSnapshot(BaseModel):
    schema_version: int = 2
    repo_url: str
    generated_at: str
    overall_score: int
    maintainability_score: int
    architecture_score: int
    module_count: int
    import_edge_count: int
    security: SnapshotSecuritySummary
    git: SnapshotGitSummary
    semantic: SnapshotSemanticSummary
    # Added in schema_version 2 (v1.3) -- optional with defaults so a
    # snapshot from before this feature still deserializes; comparison
    # against such a snapshot just won't have debt/performance metric
    # changes (see comparison_engine.py).
    debt: SnapshotDebtSummary | None = None
    performance: SnapshotPerformanceSummary | None = None


class MetricChange(BaseModel):
    label: str
    before: float
    after: float
    delta: float
    significant: bool


class SetChange(BaseModel):
    label: str
    added: list[str]
    removed: list[str]


class ComparisonFinding(BaseModel):
    category: str
    kind: str  # "regression" or "improvement"
    message: str
    severity: str


class ComparisonReport(BaseModel):
    repo_url_a: str
    repo_url_b: str
    generated_at_a: str
    generated_at_b: str
    metric_changes: list[MetricChange]
    set_changes: list[SetChange]
    regressions: list[ComparisonFinding]
    improvements: list[ComparisonFinding]


class CompareRequest(BaseModel):
    job_id_a: str
    job_id_b: str


class CompareResponse(BaseModel):
    markdown: str
    comparison: ComparisonReport


# ---------------------------------------------------------------------------
# Engineering Advisor Suite (v1.3) -- see
# docs/superpowers/specs/2026-07-24-engineering-advisor-suite-design.md
# ---------------------------------------------------------------------------


class DebtModule(BaseModel):
    file: str
    debt_score: float
    category: str
    confidence: str  # "high" or "low"
    evidence: list[str]


class TechnicalDebtReport(BaseModel):
    average_debt_score: float
    top_debt_modules: list[DebtModule]
    recommended_refactoring_order: list[str]


class PerformanceFinding(BaseModel):
    file: str
    line: int
    kind: str
    message: str
    confidence: str  # "high" or "low"


class PerformanceReport(BaseModel):
    findings: list[PerformanceFinding]
    bottleneck_modules: list[str]


class ExplanationRequest(BaseModel):
    repo_url: str = Field(max_length=300)
    prompt_kind: str = "repository_overview"


class MentorRequest(BaseModel):
    repo_url: str = Field(max_length=300)
    finding_file: str
    finding_kind: str


class ExplanationResponse(BaseModel):
    text: str
    source: str  # "deterministic" or "anthropic"
    grounded_in: list[str]
