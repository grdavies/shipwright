"""Pytest port of run_planning_paths_fixtures.py (PRD 054 W2 shadow)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_LEGACY = "scripts/test/run_planning_paths_fixtures.py"


def test_planning_paths_legacy_parity(repo_root: Path, sw_env: dict[str, str]) -> None:
    script = repo_root / _LEGACY
    assert script.is_file(), f"missing legacy script {script}"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(repo_root),
        env=sw_env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_planning_paths_negative_smoke(repo_root: Path) -> None:
    """R16 — pytest collection path exists for W2 inventory."""
    assert (repo_root / _LEGACY).is_file()
