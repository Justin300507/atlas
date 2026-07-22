from __future__ import annotations

from pydantic import BaseModel


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


class AnalyzeRequest(BaseModel):
    repo_url: str


class AnalyzeResponse(BaseModel):
    stack: StackReport
    graph: GraphResponse
    quality: QualityReport
