"""Pytest port of run_suite_registry_fixtures.py (PRD 054 W1)."""
from __future__ import annotations

from pathlib import Path

from suite_registry_check import run_suite_registry_check


def test_suite_registry_drift_checks(repo_root: Path) -> None:
    code, lines = run_suite_registry_check(repo_root)
    output = "\n".join(lines)
    assert code == 0, output
