"""Deliver envelope regression — guardrail harnesses stay green (PRD 065 R19)."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_harness(repo_root: Path, rel: str):
    path = repo_root / rel
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load harness {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_dual_ship_harness_green(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root, "scripts/unit_tests/git/harness_dual_ship.py")
    assert int(mod.main()) == 0


def test_parallel_merge_safety_harness_green(
    repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root, "scripts/unit_tests/deliver/harness_parallel_merge_safety.py")
    assert int(mod.main()) == 0


def test_status_integrity_harness_green(
    repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root, "scripts/unit_tests/deliver/harness_status_integrity.py")
    assert int(mod.main()) == 0


def test_remediation_harness_green(repo_root: Path, sw_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in sw_env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.chdir(repo_root)
    mod = _load_harness(repo_root, "scripts/unit_tests/w4/harness_regression_remediation.py")
    assert int(mod.main()) == 0
