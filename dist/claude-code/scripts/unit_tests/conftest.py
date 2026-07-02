"""Shared pytest fixtures for Shipwright unit tests (PRD 054 R15)."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Generator
from pathlib import Path

import pytest

from _sw.vendor_paths import bootstrap_vendor_paths, repo_root as sw_repo_root


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_vendored_deps() -> None:
    bootstrap_vendor_paths()


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """Repository root resolved via git or layout fallback."""
    return sw_repo_root()


@pytest.fixture
def sw_env(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Environment with PYTHONPATH and repo roots for subprocess helpers."""
    env = os.environ.copy()
    scripts = str(repo_root / "scripts")
    existing = env.get("PYTHONPATH", "")
    parts = [p for p in (scripts, existing) if p]
    env["PYTHONPATH"] = os.pathsep.join(parts)
    env["SW_REPO_ROOT"] = str(repo_root)
    env["ROOT"] = str(repo_root)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Generator[Path, None, None]:
    """Ephemeral git repository for W1+ porting of legacy git fixture patterns."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "sw-test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Shipwright Test"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    yield repo
    shutil.rmtree(repo, ignore_errors=True)
