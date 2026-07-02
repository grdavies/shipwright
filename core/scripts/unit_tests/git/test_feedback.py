"""Pytest port of run_feedback_fixtures.py (PRD 054 W2 behavioral)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_PKG = "scripts/unit_tests/git"
_HARNESS = "harness_feedback.py"


def _load_harness(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("harness_feedback", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.git
def test_feedback_tmp_git_repo_ready(tmp_git_repo: Path) -> None:
    """R15 — shared tmp_git_repo fixture is usable for W2 git scenarios."""
    assert (tmp_git_repo / ".git").is_dir()


@pytest.mark.git
def test_feedback_behavior(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root)
    assert int(mod.main()) == 0


def test_feedback_harness_present(repo_root: Path) -> None:
    """R16 — harness module must exist (fail-closed if port regresses)."""
    assert (repo_root / _PKG / _HARNESS).is_file()
