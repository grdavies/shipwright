"""Pytest port of run_status_integrity_fixtures.py (PRD 054 W1 shadow)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_LEGACY = "scripts/test/run_status_integrity_fixtures.py"


def test_status_integrity_legacy_parity(repo_root: Path, sw_env: dict[str, str]) -> None:
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


def test_status_integrity_negative_smoke(repo_root: Path) -> None:
  """R16 — pytest collection path exists for W1 inventory."""
  assert (repo_root / _LEGACY).is_file()
