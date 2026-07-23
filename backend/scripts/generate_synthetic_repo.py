"""Generate a synthetic local git repo of a target size, for LOC-scaling
benchmarks where real-repo network/clone variance would swamp the signal.

Not part of the deployed app -- a benchmarking tool only, invoked by
benchmark.py or standalone:

    python scripts/generate_synthetic_repo.py /tmp/synthetic-50k 50000
"""

from __future__ import annotations

import argparse
import random
import subprocess
from pathlib import Path

_LINES_PER_MODULE = 80
_FUNCTIONS_PER_MODULE = 6
_LONG_FUNCTION_EVERY_N_MODULES = 20
_COMMITS = 5


def _function_body(index: int, long: bool) -> str:
    line_count = 55 if long else random.randint(4, 9)
    lines = [f"    value = {index}"]
    for i in range(line_count):
        lines.append(f"    value = value + {i} if value % 2 == 0 else value - {i}")
    lines.append("    return value")
    return "\n".join(lines)


def _module_source(module_index: int, import_targets: list[int]) -> str:
    lines: list[str] = ['"""Synthetic module generated for benchmarking."""', ""]
    for target in import_targets:
        lines.append(f"from .mod_{target} import helper_0 as _dep_{target}")
    lines.append("")
    lines.append("")

    is_long = module_index % _LONG_FUNCTION_EVERY_N_MODULES == 0
    for fn_index in range(_FUNCTIONS_PER_MODULE):
        long = is_long and fn_index == 0
        lines.append(f"def helper_{fn_index}(x: int = 0) -> int:")
        lines.append(_function_body(fn_index, long))
        lines.append("")
        lines.append("")

    lines.append(f"class Service{module_index}:")
    lines.append(f'    """Synthetic service class {module_index}."""')
    lines.append("")
    lines.append("    def __init__(self) -> None:")
    lines.append(f"        self.name = 'service-{module_index}'")
    lines.append("")
    lines.append("    def run(self) -> int:")
    dep_calls = " + ".join(f"_dep_{t}()" for t in import_targets) or "0"
    lines.append(f"        return helper_0(self.name.__len__()) + {dep_calls}")
    lines.append("")
    return "\n".join(lines)


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def generate_synthetic_repo(dest: Path, target_loc: int, seed: int = 0) -> Path:
    """Create a synthetic git repo at `dest` with roughly `target_loc` lines
    of Python spread across a package with real cross-module imports."""
    random.seed(seed)
    dest.mkdir(parents=True, exist_ok=True)
    pkg_dir = dest / "pkg"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "__init__.py").write_text("")

    num_modules = max(1, target_loc // _LINES_PER_MODULE)

    for i in range(num_modules):
        import_targets: list[int] = []
        if i > 0:
            import_targets.append(i - 1)
            if i > 5:
                import_targets.append(random.randint(0, i - 2))
        source = _module_source(i, sorted(set(import_targets)))
        (pkg_dir / f"mod_{i}.py").write_text(source)

    _run_git(["init"], dest)
    _run_git(["-c", "user.email=bench@test.com", "-c", "user.name=bench", "add", "."], dest)
    for commit_index in range(_COMMITS):
        # Touch a file each commit so there's real per-commit churn, not one
        # giant initial commit followed by no-op commits.
        touched = pkg_dir / f"mod_{commit_index % num_modules}.py"
        touched.write_text(touched.read_text() + f"\n# revision {commit_index}\n")
        _run_git(["add", "."], dest)
        _run_git(
            [
                "-c",
                "user.email=bench@test.com",
                "-c",
                "user.name=bench",
                "commit",
                "-m",
                f"revision {commit_index}",
            ],
            dest,
        )

    return dest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dest", type=Path)
    parser.add_argument("target_loc", type=int)
    args = parser.parse_args()
    generate_synthetic_repo(args.dest, args.target_loc)
    print(f"Generated synthetic repo at {args.dest} (~{args.target_loc} LOC)")
