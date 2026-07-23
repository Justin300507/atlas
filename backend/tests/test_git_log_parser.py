import subprocess

import pytest

from app.git_log_parser import parse_git_log


def _init_repo(path):
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)


def _commit(path, message, author_email, files: dict[str, str]):
    for name, content in files.items():
        (path / name).write_text(content)
        subprocess.run(["git", "add", name], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", f"user.email={author_email}", "-c", "user.name=test", "commit", "-m", message],
        cwd=path,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path):
    _init_repo(tmp_path)
    _commit(tmp_path, "add a and b", "alice@example.com", {"a.py": "1\n2\n", "b.py": "1\n"})
    _commit(tmp_path, "fix bug in a", "bob@example.com", {"a.py": "1\n2\n3\n"})
    _commit(tmp_path, "update b", "alice@example.com", {"b.py": "1\n2\n"})
    return tmp_path


def test_parse_git_log_returns_commits_in_order(repo):
    commits, truncated = parse_git_log(repo, max_commits=500)

    assert not truncated
    assert len(commits) == 3
    assert commits[0].message == "update b"
    assert commits[1].message == "fix bug in a"
    assert commits[2].message == "add a and b"


def test_parse_git_log_extracts_author_and_files(repo):
    commits, _ = parse_git_log(repo, max_commits=500)

    first_commit = commits[-1]
    assert first_commit.author_email == "alice@example.com"
    paths = {f.path for f in first_commit.files}
    assert paths == {"a.py", "b.py"}
    a_change = next(f for f in first_commit.files if f.path == "a.py")
    assert a_change.additions == 2
    assert a_change.deletions == 0


def test_parse_git_log_reports_truncation(repo):
    commits, truncated = parse_git_log(repo, max_commits=2)

    assert len(commits) == 2
    assert truncated is True
