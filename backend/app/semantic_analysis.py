from __future__ import annotations

import statistics
from pathlib import Path, PurePath

import networkx as nx

from .code_parser import FileSymbols
from .git_log_parser import Commit
from .models import (
    ArchitecturalSmell,
    ArchitectureHealth,
    CouplingIssue,
    CriticalModule,
    EngineeringHotspot,
    LayerEdge,
    QualityReport,
    SemanticReport,
    SubsystemOverview,
)

# See docs/superpowers/specs/2026-07-24-semantic-repository-intelligence-design.md
# for the full rationale behind every threshold/algorithm choice below.

# Betweenness centrality is O(V*(V+E)) (Brandes' algorithm). Measured
# directly against real repos during validation of this feature:
# django/django (3038 modules, 8787 import edges) took 4.28s, and
# facebook/react (4482 modules, 3527 edges) took 6.88s -- both trivial
# next to the 40-80s clone+parse time those repos already cost. Since
# report_pipeline._MAX_FILES_PER_REPO already hard-caps any single
# analysis at 5,000 source files (so module_count can never exceed
# that), this ceiling is set comfortably above it: it exists as a
# defensive backstop against a pathological route-heavy or future-
# uncapped scenario, not because 5,000 real modules is actually
# expensive -- measurement said it isn't. Above this ceiling,
# betweenness/closeness are skipped and
# ArchitectureHealth.betweenness_computed reports False rather than
# silently taking a long time.
_MAX_MODULES_FOR_BETWEENNESS = 5500

_LAYER_VOCABULARY: list[tuple[str, set[str]]] = [
    ("presentation", {"presentation", "ui", "views", "templates", "components"}),
    ("api", {"api", "routes", "controllers", "endpoints"}),
    ("service", {"services", "handlers"}),
    ("domain", {"domain", "models", "entities"}),
    ("infrastructure", {"infrastructure", "adapters", "clients"}),
    ("persistence", {"db", "database", "repositories", "persistence", "dao"}),
]
_LAYER_ORDER = [name for name, _ in _LAYER_VOCABULARY]
_LAYER_ORDER_INDEX = {name: i for i, name in enumerate(_LAYER_ORDER)}
_LAYER_CONFIDENCE_THRESHOLD = 0.40

_FACADE_FILENAMES = {"__init__.py", "index.js", "index.jsx", "index.ts", "index.tsx"}
_MIN_FUNCTIONS_FOR_SIZE_GATE = 15
_TOP_N = 15
_MAX_SMELLS_PER_KIND = 20


def _relative(repo_root: Path | None, path: str) -> str:
    if repo_root is not None:
        try:
            return PurePath(Path(path).relative_to(repo_root)).as_posix()
        except ValueError:
            pass
    return PurePath(path).as_posix()


def _module_subgraph(graph: nx.DiGraph) -> nx.DiGraph:
    # Route nodes are never module nodes, so restricting to module nodes
    # already excludes every route-typed edge -- same trick
    # quality_engine._find_circular_dependency_clusters already relies on.
    module_nodes = [n for n, d in graph.nodes(data=True) if d.get("type") == "module"]
    return graph.subgraph(module_nodes).copy()


def _articulation_points_and_bridges(undirected: nx.Graph) -> tuple[set[str], list[tuple[str, str]]]:
    # Computed per connected component explicitly (rather than passing the
    # whole possibly-disconnected graph straight to nx.articulation_points/
    # nx.bridges) so this doesn't depend on exactly how those functions
    # handle disconnected input -- a real repo's import graph very
    # commonly has many disconnected single-node components (config files,
    # scripts), and correctness here shouldn't hinge on an assumption about
    # networkx internals that isn't worth the risk of getting wrong.
    articulation: set[str] = set()
    bridges: list[tuple[str, str]] = []
    for component_nodes in nx.connected_components(undirected):
        if len(component_nodes) < 2:
            continue
        component = undirected.subgraph(component_nodes)
        articulation.update(nx.articulation_points(component))
        bridges.extend(nx.bridges(component))
    return articulation, bridges


def _compute_metrics(module_graph: nx.DiGraph) -> tuple[dict[str, dict], bool, int, int]:
    fan_in = dict(module_graph.in_degree())
    fan_out = dict(module_graph.out_degree())

    betweenness_computed = module_graph.number_of_nodes() <= _MAX_MODULES_FOR_BETWEENNESS
    if betweenness_computed:
        betweenness = nx.betweenness_centrality(module_graph)
        closeness = nx.closeness_centrality(module_graph)
    else:
        betweenness = dict.fromkeys(module_graph.nodes, 0.0)
        closeness = dict.fromkeys(module_graph.nodes, 0.0)

    undirected = module_graph.to_undirected()
    articulation_points, bridges = _articulation_points_and_bridges(undirected)

    metrics = {
        node: {
            "fan_in": fan_in.get(node, 0),
            "fan_out": fan_out.get(node, 0),
            "betweenness": betweenness.get(node, 0.0),
            "closeness": closeness.get(node, 0.0),
            "is_articulation_point": node in articulation_points,
        }
        for node in module_graph.nodes
    }
    return metrics, betweenness_computed, len(articulation_points), len(bridges)


def _critical_modules(metrics: dict[str, dict], repo_root: Path | None) -> list[CriticalModule]:
    # Fan-in-weighted betweenness: fan-in alone answers "who imports this"
    # but not "does removing it fragment the graph"; betweenness alone can
    # rank a low-fan-in bridge above a widely-depended-on module that sits
    # in an already well-connected cluster. The product favors modules
    # that are both heavily used AND structurally load-bearing.
    ranked = []
    for node, m in metrics.items():
        score = m["fan_in"] + m["betweenness"] * m["fan_in"]
        if score > 0:
            ranked.append((node, m, score))
    ranked.sort(key=lambda t: -t[2])
    return [
        CriticalModule(
            file=_relative(repo_root, node),
            fan_in=m["fan_in"],
            fan_out=m["fan_out"],
            betweenness=round(m["betweenness"], 4),
            criticality_score=round(score, 4),
        )
        for node, m, score in ranked[:_TOP_N]
    ]


def _detect_layer(repo_root: Path | None, path: str) -> str | None:
    # Directory segments only (path.parts[:-1] drops the filename) --
    # matching against the filename too would let e.g. "api_client.py"
    # falsely match "api" with no directory-level signal behind it.
    rel = _relative(repo_root, path)
    parts = [p.lower() for p in PurePath(rel).parts[:-1]]
    for part in parts:
        for layer_name, vocab in _LAYER_VOCABULARY:
            if part in vocab:
                return layer_name
    return None


def _detect_layers(
    repo_root: Path | None, module_nodes: list[str]
) -> tuple[dict[str, str], float]:
    assignments = {}
    for node in module_nodes:
        layer = _detect_layer(repo_root, node)
        if layer:
            assignments[node] = layer
    coverage = len(assignments) / len(module_nodes) if module_nodes else 0.0
    return assignments, coverage


def _layer_edges(module_graph: nx.DiGraph, layer_assignments: dict[str, str]) -> list[LayerEdge]:
    counts: dict[tuple[str, str], int] = {}
    for u, v in module_graph.edges():
        layer_u = layer_assignments.get(u)
        layer_v = layer_assignments.get(v)
        if layer_u is None or layer_v is None:
            continue
        key = (layer_u, layer_v)
        counts[key] = counts.get(key, 0) + 1
    return [
        LayerEdge(from_layer=a, to_layer=b, edge_count=count)
        for (a, b), count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]


def _subsystem_overview(
    module_graph: nx.DiGraph, layer_assignments: dict[str, str], coverage: float
) -> SubsystemOverview:
    confident = coverage >= _LAYER_CONFIDENCE_THRESHOLD
    layer_counts: dict[str, int] = {}
    layer_edges: list[LayerEdge] = []
    if confident:
        for layer in layer_assignments.values():
            layer_counts[layer] = layer_counts.get(layer, 0) + 1
        layer_edges = _layer_edges(module_graph, layer_assignments)
    return SubsystemOverview(
        confident=confident,
        coverage_ratio=round(coverage, 4),
        layer_counts=layer_counts,
        layer_edges=layer_edges,
    )


def _layering_violations(
    module_graph: nx.DiGraph, layer_assignments: dict[str, str], repo_root: Path | None
) -> list[ArchitecturalSmell]:
    violations = []
    for u, v in module_graph.edges():
        layer_u = layer_assignments.get(u)
        layer_v = layer_assignments.get(v)
        if layer_u is None or layer_v is None or layer_u == layer_v:
            continue
        if _LAYER_ORDER_INDEX[layer_u] > _LAYER_ORDER_INDEX[layer_v]:
            violations.append(
                ArchitecturalSmell(
                    file=_relative(repo_root, u),
                    kind="layering_violation",
                    message=(
                        f"{layer_u} module imports {layer_v} module "
                        f"{_relative(repo_root, v)} -- against the detected "
                        "presentation to api to service to domain to "
                        "infrastructure to persistence layer order"
                    ),
                    severity="important",
                )
            )
    return violations[:_MAX_SMELLS_PER_KIND]


def _analyze_hotspots(
    files: list[FileSymbols],
    metrics: dict[str, dict],
    quality: QualityReport,
    commits: list[Commit],
    repo_root: Path | None,
) -> list[EngineeringHotspot]:
    churn_by_relpath: dict[str, int] = {}
    for commit in commits:
        for fc in commit.files:
            churn_by_relpath[fc.path] = churn_by_relpath.get(fc.path, 0) + 1

    complexity_by_file: dict[str, int] = {}
    for issue in quality.issues:
        if issue.kind in ("long_function", "high_complexity"):
            complexity_by_file[issue.file] = complexity_by_file.get(issue.file, 0) + 1

    raw = []
    for f in files:
        rel = _relative(repo_root, f.path)
        churn = churn_by_relpath.get(rel, 0)
        m = metrics.get(f.path, {})
        centrality = m.get("fan_in", 0) + m.get("betweenness", 0.0)
        complexity = complexity_by_file.get(f.path, 0)
        raw.append((f.path, rel, churn, centrality, complexity))

    max_churn = max((r[2] for r in raw), default=0) or 1
    max_centrality = max((r[3] for r in raw), default=0.0) or 1.0
    max_complexity = max((r[4] for r in raw), default=0) or 1

    hotspots = []
    for _path, rel, churn, centrality, complexity in raw:
        # Zero churn scores zero regardless of the other two factors,
        # deliberately: "hotspot" means actively risky, not just
        # structurally important or currently messy. A load-bearing module
        # nobody has touched in the analyzed window isn't a maintenance
        # hotspot by this definition.
        score = (churn / max_churn) * (centrality / max_centrality) * (complexity / max_complexity)
        if score > 0:
            hotspots.append(
                EngineeringHotspot(
                    file=rel,
                    churn=churn,
                    centrality=round(centrality, 4),
                    complexity_issues=complexity,
                    hotspot_score=round(score, 4),
                )
            )

    hotspots.sort(key=lambda h: -h.hotspot_score)
    return hotspots[:_TOP_N]


def _percentile(values: list[int], pct: int) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    quantile_cuts = statistics.quantiles(values, n=100, method="inclusive")
    return quantile_cuts[max(0, min(98, pct - 1))]


def _dependency_concentration(metrics: dict[str, dict]) -> float:
    fan_ins = sorted((m["fan_in"] for m in metrics.values()), reverse=True)
    total = sum(fan_ins)
    if total == 0:
        return 0.0
    return round(sum(fan_ins[:5]) / total, 4)


def _analyze_coupling_and_smells(
    files: list[FileSymbols], metrics: dict[str, dict], repo_root: Path | None
) -> tuple[list[CouplingIssue], list[ArchitecturalSmell]]:
    function_counts = {f.path: len(f.functions) for f in files}
    fan_outs = [m["fan_out"] for m in metrics.values()]
    fan_ins = [m["fan_in"] for m in metrics.values()]

    p95_fan_out = _percentile(fan_outs, 95)
    p75_fan_in = _percentile(fan_ins, 75)
    p25_fan_out = _percentile(fan_outs, 25)

    coupling_issues: list[CouplingIssue] = []
    smells: list[ArchitecturalSmell] = []

    for node, m in metrics.items():
        rel = _relative(repo_root, node)
        fn_count = function_counts.get(node, 0)
        filename = PurePath(node).name

        if p95_fan_out > 0 and m["fan_out"] >= p95_fan_out:
            if fn_count >= _MIN_FUNCTIONS_FOR_SIZE_GATE:
                coupling_issues.append(
                    CouplingIssue(
                        file=rel,
                        kind="god_module",
                        message=(
                            f"fan-out {m['fan_out']} (top 5% of this repo) "
                            f"across {fn_count} functions"
                        ),
                        severity="important",
                    )
                )
            else:
                coupling_issues.append(
                    CouplingIssue(
                        file=rel,
                        kind="excessive_fan_out",
                        message=f"fan-out {m['fan_out']} (top 5% of this repo)",
                        severity="minor",
                    )
                )

        if m["fan_in"] == 0 and m["fan_out"] == 0:
            smells.append(
                ArchitecturalSmell(
                    file=rel,
                    kind="isolated_component",
                    message="No import edges in either direction -- disconnected from the rest of the import graph",
                    severity="minor",
                )
            )
            continue

        is_facade_shape = (
            p75_fan_in > 0 and m["fan_in"] >= p75_fan_in and m["fan_out"] <= p25_fan_out
        )
        if not is_facade_shape:
            continue
        if filename in _FACADE_FILENAMES:
            smells.append(
                ArchitecturalSmell(
                    file=rel,
                    kind="facade_pattern",
                    message=(
                        f"{filename} with fan-in {m['fan_in']} (top 25%), "
                        f"fan-out {m['fan_out']} (bottom 25%) -- matches the "
                        "facade/re-export convention"
                    ),
                    severity="minor",
                )
            )
        elif fn_count >= _MIN_FUNCTIONS_FOR_SIZE_GATE:
            smells.append(
                ArchitecturalSmell(
                    file=rel,
                    kind="utility_dumping",
                    message=(
                        f"fan-in {m['fan_in']} (top 25%), fan-out {m['fan_out']} "
                        f"(bottom 25%), {fn_count} functions -- widely imported "
                        "but self-contained, worth checking it isn't an "
                        "unstructured dumping ground"
                    ),
                    severity="minor",
                )
            )

    return coupling_issues[:_MAX_SMELLS_PER_KIND], smells[:_MAX_SMELLS_PER_KIND]


def analyze_semantics(
    files: list[FileSymbols],
    graph: nx.DiGraph,
    quality: QualityReport,
    commits: list[Commit],
    repo_root: Path | None = None,
) -> SemanticReport:
    module_graph = _module_subgraph(graph)
    module_nodes = list(module_graph.nodes)

    metrics, betweenness_computed, articulation_count, bridge_count = _compute_metrics(
        module_graph
    )

    circular_cluster_count = sum(1 for i in quality.issues if i.kind == "circular_import")

    layer_assignments, coverage = _detect_layers(repo_root, module_nodes)
    subsystem = _subsystem_overview(module_graph, layer_assignments, coverage)

    coupling_issues, smells = _analyze_coupling_and_smells(files, metrics, repo_root)
    if subsystem.confident:
        smells = smells + _layering_violations(module_graph, layer_assignments, repo_root)

    health = ArchitectureHealth(
        module_count=len(module_nodes),
        import_edge_count=module_graph.number_of_edges(),
        circular_cluster_count=circular_cluster_count,
        articulation_point_count=articulation_count,
        bridge_count=bridge_count,
        betweenness_computed=betweenness_computed,
        dependency_concentration_top5_ratio=_dependency_concentration(metrics),
    )

    return SemanticReport(
        architecture_health=health,
        critical_modules=_critical_modules(metrics, repo_root),
        subsystem_overview=subsystem,
        hotspots=_analyze_hotspots(files, metrics, quality, commits, repo_root),
        coupling_issues=coupling_issues,
        architectural_smells=smells,
    )
