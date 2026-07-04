"""Pytest port of run_hook_worktree_alignment_fixtures.py (PRD 054 W3 behavioral)."""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import pytest
_PKG = "scripts/unit_tests/hooks"
_HARNESS = "harness_hook_worktree_alignment.py"

def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_hook_worktree_alignment", path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod

@pytest.mark.git
def test_hook_worktree_alignment_tmp_git_repo_ready(tmp_git_repo: Path) -> None:
    assert (tmp_git_repo/".git").is_dir()


@pytest.mark.integration
@pytest.mark.git
def test_hook_worktree_alignment_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for k,v in sw_env.items(): monkeypatch.setenv(k,v)
    monkeypatch.chdir(repo_root)
    assert int(_load_harness(repo_root).main()) == 0

def test_hook_worktree_alignment_harness_present(repo_root: Path) -> None:
    assert (repo_root / _PKG / _HARNESS).is_file()
