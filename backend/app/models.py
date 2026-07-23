from __future__ import annotations

from pydantic import BaseModel, Field


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


class DocumentationResponse(BaseModel):
    markdown: str
