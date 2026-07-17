"""Pytest port for harness skew-skip fixtures (PRD 072 R3, R12)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from unit_tests._harness_runtime import run_harness_skew_skip_fixtures


def test_harness_skew_skip_per_marker(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for entry in (str(repo_root / "scripts" / "test"), str(repo_root / "scripts")):
        if entry not in sys.path:
            sys.path.insert(0, entry)
    monkeypatch.chdir(repo_root)
    assert run_harness_skew_skip_fixtures(repo_root) == 0
