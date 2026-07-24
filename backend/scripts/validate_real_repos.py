"""Real-world validation: does Atlas stay *useful*, not just fast, on
large real repos across ecosystems?

Deliberately separate from benchmark.py (which only measures wall-clock
and memory against two small repos). This script runs the actual
structural pipeline against a curated cross-ecosystem list, keeps the
intermediate objects (not just the final markdown) so quality/blind-spot
questions can be answered after the fact, and writes both a summary table
and the full generated report per repo for manual inspection.

Not part of the deployed app or the pytest suite -- run manually:

    cd backend && .venv/Scripts/python scripts/validate_real_repos.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cloner import clone_with_history
from app.doc_generator import generate_documentation
from app.git_intelligence import analyze_git_history
from app.git_log_parser import parse_git_log
from app.report_pipeline import analyze_structure

REPOS = [
    ("django/django", "https://github.com/django/django", "Python"),
    ("tiangolo/fastapi", "https://github.com/tiangolo/fastapi", "Python"),
    ("pallets/flask", "https://github.com/pallets/flask", "Python"),
    ("facebook/react", "https://github.com/facebook/react", "JavaScript"),
    ("expressjs/express", "https://github.com/expressjs/express", "JavaScript (CommonJS)"),
    ("psf/requests", "https://github.com/psf/requests", "Python"),
    ("vercel/next.js", "https://github.com/vercel/next.js", "TypeScript (monorepo)"),
]

_PROCESS = psutil.Process()


@dataclass
class Result:
    name: str
    ecosystem: str
    ok: bool = False
    error: str = ""
    clone_and_analyze_s: float = 0.0
    peak_rss_mb: float = 0.0
    files_parsed: int = 0
    files_at_cap: bool = False
    graph_nodes: int = 0
    graph_edges: int = 0
    import_edges: int = 0
    overall_score: int = 0
    maintainability_score: int = 0
    architecture_score: int = 0
    circular_clusters: int = 0
    security_findings: int = 0
    commits_analyzed: int = 0
    history_truncated: bool = False
    doc_chars: int = 0
    markdown: str = field(default="", repr=False)


def validate_one(name: str, url: str, ecosystem: str) -> Result:
    r = Result(name=name, ecosystem=ecosystem)
    peak = _PROCESS.memory_info().rss
    start = time.monotonic()
    try:
        with clone_with_history(url, depth=501) as repo_path:
            stack, files, graph, quality, security, coverage = analyze_structure(repo_path)
            commits, history_truncated = parse_git_log(repo_path, max_commits=500)
            git_report = analyze_git_history(commits, history_truncated)
            markdown = generate_documentation(
                repo_path, stack, files, graph, quality, security, git_report, coverage
            )
            rss = _PROCESS.memory_info().rss
            if rss > peak:
                peak = rss

        r.files_parsed = len(files)
        # coverage.files_capped is the real signal -- len(files) >= cap would
        # under-report: the walk can hit the cap at 5,000 *candidates* while
        # only some of those successfully parse (READMEs/configs/etc return
        # None from parse_file and never reach `files`), so len(files) can
        # sit well under the cap even when the walk was truncated.
        r.files_at_cap = coverage.files_capped
        r.graph_nodes = graph.number_of_nodes()
        r.graph_edges = graph.number_of_edges()
        r.import_edges = sum(
            1 for _, _, d in graph.edges(data=True) if d.get("type") == "import"
        )
        r.overall_score = quality.overall_score
        r.maintainability_score = quality.maintainability_score
        r.architecture_score = quality.architecture_score
        r.circular_clusters = sum(1 for i in quality.issues if i.kind == "circular_import")
        r.security_findings = len(security.issues)
        r.commits_analyzed = git_report.commits_analyzed
        r.history_truncated = git_report.history_truncated
        r.doc_chars = len(markdown)
        r.markdown = markdown
        r.ok = True
    except Exception as exc:  # pragma: no cover - validation script
        r.error = f"{type(exc).__name__}: {exc}"
    r.clone_and_analyze_s = time.monotonic() - start
    r.peak_rss_mb = peak / (1024 * 1024)
    return r


def _summary_table(results: list[Result]) -> str:
    lines = [
        "| Repo | Ecosystem | OK | Time (s) | Peak RSS (MB) | Files | Cap hit | Import edges | Overall | Arch | Circular clusters | Security | Commits |",
        "|---|---|---|---:|---:|---:|:-:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in results:
        if not r.ok:
            lines.append(f"| {r.name} | {r.ecosystem} | ✗ | — | — | — | — | — | — | — | — | — | — | {r.error} |")
            continue
        lines.append(
            "| {n} | {e} | ✓ | {t:.1f} | {rss:.0f} | {f} | {cap} | {ie} | {ov} | {arch} | {cc} | {sec} | {ci}{tr} |".format(
                n=r.name,
                e=r.ecosystem,
                t=r.clone_and_analyze_s,
                rss=r.peak_rss_mb,
                f=r.files_parsed,
                cap="yes" if r.files_at_cap else "no",
                ie=r.import_edges,
                ov=r.overall_score,
                arch=r.architecture_score,
                cc=r.circular_clusters,
                sec=r.security_findings,
                ci=r.commits_analyzed,
                tr=" (truncated)" if r.history_truncated else "",
            )
        )
    return "\n".join(lines)


def main() -> None:
    out_dir = Path(__file__).resolve().parent.parent.parent / "docs" / "benchmarks"
    reports_dir = out_dir / "real-world-validation-reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for name, url, ecosystem in REPOS:
        print(f"Validating {name} ({ecosystem})...")
        r = validate_one(name, url, ecosystem)
        if r.ok:
            print(
                f"  ok — {r.clone_and_analyze_s:.1f}s, {r.peak_rss_mb:.0f}MB peak, "
                f"{r.files_parsed} files ({'CAP HIT' if r.files_at_cap else 'under cap'}), "
                f"{r.import_edges} import edges, overall score {r.overall_score}"
            )
            report_path = reports_dir / f"{name.replace('/', '-')}-report.md"
            report_path.write_text(r.markdown, encoding="utf-8")
        else:
            print(f"  FAILED — {r.error}")
        results.append(r)

    summary = "\n".join(
        [
            "# Atlas Real-World Validation",
            "",
            f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}. Full",
            "reports for each repo are in `real-world-validation-reports/`.",
            "",
            _summary_table(results),
            "",
        ]
    )
    summary_path = out_dir / "2026-07-24-real-world-validation.md"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"\nSummary written to {summary_path}")
    print(f"Full reports written to {reports_dir}")


if __name__ == "__main__":
    main()
