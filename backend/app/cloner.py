from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

_GITHUB_URL_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?$")


class CloneError(Exception):
    pass


class InvalidRepoUrlError(CloneError):
    pass


def validate_github_url(url: str) -> None:
    if not _GITHUB_URL_RE.match(url.strip()):
        raise InvalidRepoUrlError(f"Not a valid GitHub repository URL: {url}")


def _clone_to(source: str, dest: str, timeout: int) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", source, dest],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise CloneError(result.stderr.strip() or "git clone failed")


@contextmanager
def shallow_clone(url: str, timeout: int = 60):
    validate_github_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="atlas-clone-")
    try:
        _clone_to(url, tmp_dir, timeout)
        yield Path(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _clone_history_to(source: str, dest: str, depth: int, timeout: int) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", str(depth), source, dest],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise CloneError(result.stderr.strip() or "git clone failed")


@contextmanager
def clone_with_history(url: str, depth: int = 500, timeout: int = 120):
    validate_github_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="atlas-clone-history-")
    try:
        _clone_history_to(url, tmp_dir, depth, timeout)
        yield Path(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
