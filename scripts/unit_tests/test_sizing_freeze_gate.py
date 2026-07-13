"""PRD 065 R16 — blocking sizing freeze gate tests."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

import phase_sizing as ps

FIXTURE = "scripts/test/fixtures/phase-sizing/tasks-freeze-gate-oversize.md"
SMALL_FIXTURE = "scripts/test/fixtures/phase-sizing/tasks-split-candidate.md"


def test_freeze_gate_blocks_oversize(repo_root: Path) -> None:
    task_list = repo_root / FIXTURE
    result = ps.evaluate_freeze_gate(repo_root, task_list)
    assert result["verdict"] == "block"
    assert result["overThresholdPhases"] == ["1"]
    assert result.get("splitSuggestions")


def test_freeze_gate_passes_small_phase(repo_root: Path) -> None:
    task_list = repo_root / SMALL_FIXTURE
    result = ps.evaluate_freeze_gate(repo_root, task_list)
    assert result["verdict"] == "pass"
    assert result["overThresholdPhases"] == []


def test_record_override_requires_attribution(repo_root: Path) -> None:
    task_list = repo_root / FIXTURE
    override_path = ps.override_path(repo_root, task_list)
    if override_path.is_file():
        override_path.unlink()
    proc = subprocess.run(
        [
            "python3",
            str(repo_root / "scripts/phase_sizing.py"),
            "--root",
            str(repo_root),
            "record-override",
            FIXTURE,
            "--actor",
            "",
            "--reason",
            "",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo_root / "scripts")},
    )
    assert proc.returncode == 20
    payload = json.loads(proc.stdout)
    assert payload["cause"] == "missing-attribution"


def test_record_override_allows_freeze_with_attribution(repo_root: Path) -> None:
    task_list = repo_root / FIXTURE
    override_path = ps.override_path(repo_root, task_list)
    if override_path.is_file():
        override_path.unlink()
    proc = subprocess.run(
        [
            "python3",
            str(repo_root / "scripts/phase_sizing.py"),
            "--root",
            str(repo_root),
            "record-override",
            FIXTURE,
            "--actor",
            "human@example.com",
            "--reason",
            "accepted single-phase oversize for fixture",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo_root / "scripts")},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    result = ps.evaluate_freeze_gate(repo_root, task_list)
    assert result["verdict"] == "pass"
    assert result.get("overrideApplied", {}).get("actor") == "human@example.com"
    override_path.unlink(missing_ok=True)


def test_record_override_refused_on_agent_dispatch(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SW_DISPATCH_PARENT_COMMAND", "sw-doc")
    proc = subprocess.run(
        [
            "python3",
            str(repo_root / "scripts/phase_sizing.py"),
            "--root",
            str(repo_root),
            "record-override",
            FIXTURE,
            "--actor",
            "human@example.com",
            "--reason",
            "should be denied",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(repo_root / "scripts"), "SW_DISPATCH_PARENT_COMMAND": "sw-doc"},
    )
    assert proc.returncode == 20
    payload = json.loads(proc.stdout)
    assert payload["cause"] == "agent-dispatch-override-denied"
