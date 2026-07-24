from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

_GITHUB_URL_RE = re.compile(r"^https://github\.com/[\w.-]+/[\w.-]+(?:\.git)?/?$")

# Found via real-world validation (2026-07-24): git's stderr on a large,
# failing clone can be dominated by "Updating files: NN% (...)" progress
# lines -- one per percentage point, potentially hundreds of lines -- ahead
# of the actual fatal error (confirmed against vercel/next.js, which fails
# checkout on Windows due to MAX_PATH). Left as-is, that whole blob became
# the CloneError message, propagating into job state, logs, and the API
# response verbatim. Surface only the meaningful fatal/error lines instead.
_MAX_ERROR_MESSAGE_CHARS = 500


class CloneError(Exception):
    pass


class InvalidRepoUrlError(CloneError):
    pass


def validate_github_url(url: str) -> None:
    if not _GITHUB_URL_RE.match(url.strip()):
        raise InvalidRepoUrlError(f"Not a valid GitHub repository URL: {url}")


def _clean_git_error(stderr: str) -> str:
    lines = [ln for ln in stderr.strip().splitlines() if ln.startswith(("fatal:", "error:"))]
    message = "\n".join(lines) if lines else stderr.strip()
    if len(message) > _MAX_ERROR_MESSAGE_CHARS:
        message = message[:_MAX_ERROR_MESSAGE_CHARS] + " ... (truncated)"
    return message or "git clone failed"


def _clone_to(source: str, dest: str, timeout: int) -> None:
    result = subprocess.run(
        ["git", "clone", "--depth", "1", source, dest],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        raise CloneError(_clean_git_error(result.stderr))


@contextmanager
def shallow_clone(url: str, timeout: int = 60):
    # validate_github_url only strips for its own regex check -- it doesn't
    # return a normalized value, so a leading/trailing space (e.g. a
    # copy-paste artifact) passed validation but was still handed to `git
    # clone` verbatim, which fails with a confusing "protocol '
    # https' is not supported" error. Strip once, here, before either
    # validating or cloning.
    url = url.strip()
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
        raise CloneError(_clean_git_error(result.stderr))


@contextmanager
def clone_with_history(url: str, depth: int = 500, timeout: int = 120):
    url = url.strip()  # see shallow_clone's comment above
    validate_github_url(url)
    tmp_dir = tempfile.mkdtemp(prefix="atlas-clone-history-")
    try:
        _clone_history_to(url, tmp_dir, depth, timeout)
        yield Path(tmp_dir)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
