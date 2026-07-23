"""Repeatable performance & load benchmark for Atlas's analysis pipeline.

Two legs, deliberately using different methodology for different questions:

- Real-repo leg: validates against actual public repos, network clone
  included. Kept to a short fixed list to avoid hammering GitHub.
- Synthetic LOC-scaling leg: generates local repos of controlled size
  (no network), isolating pure parse/graph/quality/security/doc-gen
  compute time from clone-time network variance.

Not part of the deployed app or the pytest suite (network + wall-clock
heavy) -- run manually:

    cd backend && .venv/Scripts/python scripts/benchmark.py

Requires backend/requirements-bench.txt (psutil).
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.git_intelligence import analyze_git_history
from app.git_log_parser import parse_git_log
from app.report_pipeline import analyze_structure, run_full_analysis
from app.doc_generator import generate_documentation
from scripts.generate_synthetic_repo import generate_synthetic_repo

REAL_REPOS = [
    "https://github.com/octocat/Hello-World",
    "https://github.com/tiangolo/typer",
]
SYNTHETIC_LOC_TIERS = [10_000, 25_000, 50_000, 100_000, 250_000]

_PROCESS = psutil.Process()


@dataclass
class Measurement:
    label: str
    durations: dict[str, float] = field(default_factory=dict)
    peak_rss_mb: float = 0.0
    error: str | None = None


class _PeakRssSampler:
    def __init__(self, interval_seconds: float = 0.05) -> None:
        self._interval = interval_seconds
        self._peak_bytes = _PROCESS.memory_info().rss
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)

    def _sample_loop(self) -> None:
        while not self._stop.is_set():
            rss = _PROCESS.memory_info().rss
            if rss > self._peak_bytes:
                self._peak_bytes = rss
            self._stop.wait(self._interval)

    def __enter__(self) -> "_PeakRssSampler":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._thread.join()

    @property
    def peak_mb(self) -> float:
        return self._peak_bytes / (1024 * 1024)


def _time_stage(durations: dict[str, float], name: str):
    class _Ctx:
        def __enter__(self_inner):
            self_inner.start = time.monotonic()
            return self_inner

        def __exit__(self_inner, *exc):
            durations[name] = time.monotonic() - self_inner.start

    return _Ctx()


def benchmark_real_repo(url: str) -> Measurement:
    m = Measurement(label=url)
    with _PeakRssSampler() as sampler:
        start = time.monotonic()
        try:
            run_full_analysis(url)
        except Exception as exc:  # pragma: no cover - benchmark script
            m.error = str(exc)
        m.durations["total"] = time.monotonic() - start
    m.peak_rss_mb = sampler.peak_mb
    return m


def benchmark_synthetic(target_loc: int) -> Measurement:
    m = Measurement(label=f"{target_loc:,} LOC (synthetic)")
    with tempfile.TemporaryDirectory(prefix="atlas-bench-") as tmp:
        repo_path = generate_synthetic_repo(Path(tmp) / "repo", target_loc)
        with _PeakRssSampler() as sampler:
            start = time.monotonic()
            try:
                with _time_stage(m.durations, "parsing_and_graph_and_quality_and_security"):
                    stack, files, graph, quality, security = analyze_structure(repo_path)
                with _time_stage(m.durations, "git_history"):
                    commits, truncated = parse_git_log(repo_path, max_commits=500)
                    git_report = analyze_git_history(commits, truncated)
                with _time_stage(m.durations, "generating_documentation"):
                    generate_documentation(
                        repo_path, stack, files, graph, quality, security, git_report
                    )
            except Exception as exc:  # pragma: no cover - benchmark script
                m.error = str(exc)
            m.durations["total"] = time.monotonic() - start
        m.peak_rss_mb = sampler.peak_mb
    return m


def _format_report(real: list[Measurement], synthetic: list[Measurement]) -> str:
    lines = [
        "# Atlas Performance & Load Benchmark",
        "",
        f"Generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}.",
        "",
        "## Real-repo leg (network clone included)",
        "",
        "| Repo | Total (s) | Peak RSS (MB) | Notes |",
        "|---|---:|---:|---|",
    ]
    for m in real:
        note = m.error if m.error else ""
        lines.append(f"| {m.label} | {m.durations.get('total', 0):.2f} | {m.peak_rss_mb:.1f} | {note} |")

    lines += [
        "",
        "## Synthetic LOC-scaling leg (no network, isolates compute time)",
        "",
        "| Size | Parse+Graph+Quality+Security (s) | Git History (s) | Doc Gen (s) | Total (s) | Peak RSS (MB) | Notes |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for m in synthetic:
        note = m.error if m.error else ""
        lines.append(
            "| {label} | {parse:.2f} | {git:.2f} | {doc:.2f} | {total:.2f} | {rss:.1f} | {note} |".format(
                label=m.label,
                parse=m.durations.get("parsing_and_graph_and_quality_and_security", 0),
                git=m.durations.get("git_history", 0),
                doc=m.durations.get("generating_documentation", 0),
                total=m.durations.get("total", 0),
                rss=m.peak_rss_mb,
                note=note,
            )
        )

    return "\n".join(lines) + "\n"


def main() -> None:
    print("Real-repo leg...")
    real_results = [benchmark_real_repo(url) for url in REAL_REPOS]
    for m in real_results:
        print(f"  {m.label}: {m.durations.get('total', 0):.2f}s, {m.peak_rss_mb:.1f}MB peak")

    print("Synthetic LOC-scaling leg...")
    synthetic_results = [benchmark_synthetic(loc) for loc in SYNTHETIC_LOC_TIERS]
    for m in synthetic_results:
        print(f"  {m.label}: {m.durations.get('total', 0):.2f}s, {m.peak_rss_mb:.1f}MB peak")

    report = _format_report(real_results, synthetic_results)
    out_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "benchmarks"
        / "2026-07-23-performance-and-load-benchmark.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nReport written to {out_path}")


if __name__ == "__main__":
    main()
