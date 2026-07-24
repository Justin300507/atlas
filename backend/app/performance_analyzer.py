from __future__ import annotations

from pathlib import Path, PurePath

from .code_parser import FileSymbols
from .models import PerformanceFinding, PerformanceReport, SemanticReport

# See docs/superpowers/specs/2026-07-24-engineering-advisor-suite-design.md
# for what's deliberately NOT implemented here (N^2 pattern detection,
# parameter-count checks, real nesting-depth analysis) and why -- static,
# deterministic only, never estimates runtime.

# 3x quality_engine._LONG_FUNCTION_LINES (50): a function merely "long"
# is already a quality-engine finding; a *performance* risk flag needs a
# much higher bar to not just duplicate that one under a new name.
_VERY_LARGE_FUNCTION_LINES = 150
_HIGH_BRANCH_COUNT = 25


def _relative(repo_root: Path | None, path: str) -> str:
    if repo_root is not None:
        try:
            return PurePath(Path(path).relative_to(repo_root)).as_posix()
        except ValueError:
            pass
    return PurePath(path).as_posix()


def analyze_performance(
    files: list[FileSymbols], semantic: SemanticReport, repo_root: Path | None = None
) -> PerformanceReport:
    findings: list[PerformanceFinding] = []

    for f in files:
        rel = _relative(repo_root, f.path)
        for fn in f.functions:
            length = fn.end_line - fn.start_line + 1
            if length > _VERY_LARGE_FUNCTION_LINES:
                findings.append(
                    PerformanceFinding(
                        file=rel,
                        line=fn.start_line,
                        kind="very_large_function",
                        message=(
                            f"Function '{fn.name}' is {length} lines -- large enough that "
                            "initialization, allocation, or repeated work inside it is easy "
                            f"to miss in review (threshold {_VERY_LARGE_FUNCTION_LINES})"
                        ),
                        confidence="high",
                    )
                )
            if fn.branch_count > _HIGH_BRANCH_COUNT:
                findings.append(
                    PerformanceFinding(
                        file=rel,
                        line=fn.start_line,
                        kind="high_branch_count",
                        message=(
                            f"Function '{fn.name}' has branch count {fn.branch_count} "
                            f"(threshold {_HIGH_BRANCH_COUNT}) -- may indicate deep nesting; "
                            "Atlas measures branch count, not actual nesting depth, so this "
                            "is a proxy signal, not a direct nesting measurement"
                        ),
                        confidence="low",
                    )
                )

    # Dependency-bottleneck detection reuses coupling_issues' god_module/
    # excessive_fan_out findings (already per-file, already capturing
    # "unusually concentrated") intersected with dependency-criticality
    # top 15, rather than threading a new is_articulation_point field
    # through SemanticReport just for this one check.
    bottleneck_modules: list[str] = []
    critical_files = {m.file for m in semantic.critical_modules}
    coupling_files = {i.file for i in semantic.coupling_issues}
    for rel in critical_files & coupling_files:
        findings.append(
            PerformanceFinding(
                file=rel,
                line=0,
                kind="dependency_bottleneck",
                message=(
                    f"{rel} is both in the dependency-criticality top 15 and flagged for "
                    "high fan-out/fan-in -- a large share of the codebase's import paths "
                    "may route through this one file with no alternative"
                ),
                confidence="high",
            )
        )
        bottleneck_modules.append(rel)

    return PerformanceReport(findings=findings, bottleneck_modules=sorted(bottleneck_modules))
