"""Minimal foundation tests — proves pytest collection and shared fixtures."""

from __future__ import annotations

from pathlib import Path


def test_repo_root_fixture(repo_root: Path) -> None:
    assert (repo_root / "scripts").is_dir()
    assert (repo_root / "pytest.ini").is_file()


def test_sw_env_sets_repo_root(sw_env: dict[str, str], repo_root: Path) -> None:
    assert sw_env["SW_REPO_ROOT"] == str(repo_root)


def test_tmp_git_repo_has_commit(tmp_git_repo: Path) -> None:
    assert (tmp_git_repo / ".git").is_dir()
    head = (tmp_git_repo / ".git" / "HEAD").read_text(encoding="utf-8")
    assert "ref:" in head
