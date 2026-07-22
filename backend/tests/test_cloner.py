import subprocess
from pathlib import Path

import pytest

from app.cloner import CloneError, InvalidRepoUrlError, _clone_to, shallow_clone, validate_github_url


def test_validate_github_url_accepts_valid_url():
    validate_github_url("https://github.com/octocat/Hello-World")


def test_validate_github_url_rejects_invalid():
    with pytest.raises(InvalidRepoUrlError):
        validate_github_url("not-a-url")


def test_clone_to_local_repo(tmp_path):
    source = tmp_path / "source_repo"
    source.mkdir()
    subprocess.run(["git", "init"], cwd=source, check=True, capture_output=True)
    (source / "file.txt").write_text("hello")
    subprocess.run(["git", "add", "file.txt"], cwd=source, check=True, capture_output=True)
    subprocess.run(
        ["git", "-c", "user.email=test@test.com", "-c", "user.name=test", "commit", "-m", "init"],
        cwd=source,
        check=True,
        capture_output=True,
    )

    dest = tmp_path / "dest_repo"
    _clone_to(str(source), str(dest), timeout=30)

    assert (dest / "file.txt").exists()


def test_clone_to_raises_on_missing_source(tmp_path):
    dest = tmp_path / "dest_repo"
    with pytest.raises(CloneError):
        _clone_to(str(tmp_path / "does_not_exist"), str(dest), timeout=30)


def test_shallow_clone_cleans_up_temp_dir(monkeypatch, tmp_path):
    captured = {}

    def fake_clone_to(source, dest, timeout):
        Path(dest).mkdir(parents=True, exist_ok=True)
        (Path(dest) / "marker.txt").write_text("ok")
        captured["dest"] = dest

    monkeypatch.setattr("app.cloner._clone_to", fake_clone_to)

    with shallow_clone("https://github.com/octocat/Hello-World") as repo_path:
        assert (repo_path / "marker.txt").exists()

    assert not Path(captured["dest"]).exists()
