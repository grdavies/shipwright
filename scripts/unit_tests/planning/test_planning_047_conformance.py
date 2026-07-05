"""Pytest port — PRD 047 Jira cross-provider conformance."""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
import pytest
_PKG = "scripts/unit_tests/planning"
_HARNESS = "harness_planning_047_conformance.py"

def _load(repo_root: Path):
    path = repo_root / _PKG / _HARNESS
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location("_h", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def test_planning_047_conformance(repo_root: Path, sw_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in sw_env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(repo_root)
    assert _load(repo_root).main() == 0

def test_harness_present(repo_root: Path) -> None:
    assert (repo_root / _PKG / _HARNESS).is_file()
