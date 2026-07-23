from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_COMMIT_MARKER = "@@ATLAS-COMMIT@@"
_FIELD_SEP = "@@ATLAS-FIELD@@"


@dataclass
class FileChange:
    path: str
    additions: int
    deletions: int


@dataclass
class Commit:
    hash: str
    author_email: str
    message: str
    files: list[FileChange] = field(default_factory=list)


def parse_git_log(repo_path: Path, max_commits: int = 500) -> tuple[list[Commit], bool]:
    result = subprocess.run(
        [
            "git",
            "log",
            f"-n{max_commits + 1}",
            "--numstat",
            f"--pretty=format:{_COMMIT_MARKER}%H{_FIELD_SEP}%ae{_FIELD_SEP}%s",
        ],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # A repo with no commits yet is a legitimate degenerate case (e.g. a
        # freshly-created GitHub repo before the first push), not a clone
        # failure — `git log` exits non-zero with "does not have any commits
        # yet" rather than returning empty output.
        return [], False

    commits = _parse_log_output(result.stdout)
    truncated = len(commits) > max_commits
    return commits[:max_commits], truncated


def _parse_log_output(output: str) -> list[Commit]:
    commits: list[Commit] = []
    current: Commit | None = None

    for line in output.splitlines():
        if line.startswith(_COMMIT_MARKER):
            commit_hash, author_email, message = line[len(_COMMIT_MARKER):].split(_FIELD_SEP, 2)
            current = Commit(hash=commit_hash, author_email=author_email, message=message)
            commits.append(current)
        elif line.strip() and current is not None:
            parts = line.split("\t")
            if len(parts) != 3:
                continue
            added_raw, removed_raw, path = parts
            if added_raw == "-" or removed_raw == "-":
                continue
            try:
                current.files.append(
                    FileChange(path=path, additions=int(added_raw), deletions=int(removed_raw))
                )
            except ValueError:
                continue

    return commits
