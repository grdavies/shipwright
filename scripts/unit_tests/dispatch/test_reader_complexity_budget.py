"""Unit tests for PRD 064 phase 9 reader/complexity/token-budget dispatch libs."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from dispatch_reader_lib import (
    evaluate_reader_role,
    validate_reader_tool_log,
    READER_DEFAULT_ON_BOUNDARIES,
)
from dispatch_complexity_lib import probe_complexity, clamp_tier
from dispatch_budget_lib import resolve_token_budget, format_partial_result_handoff


def test_reader_boundary_requires_role() -> None:
    assert "feedback-intake" in READER_DEFAULT_ON_BOUNDARIES
    fail = evaluate_reader_role(role=None, boundary="feedback-intake")
    assert fail is not None
    assert fail["cause"] == "binding:reader-role-missing"
    assert evaluate_reader_role(role="reader", boundary="feedback-intake") is None


def test_reader_rejects_mutating_tool_log() -> None:
    log = [{"toolName": "Write", "args": {}}]
    fail = validate_reader_tool_log(log)
    assert fail is not None
    assert fail["cause"] == "binding:reader-mutating-call"
    assert validate_reader_tool_log([{"toolName": "Read"}]) is None


def test_complexity_probe_disabled_keeps_static() -> None:
    result = probe_complexity(static_tier="build", signal_context={"file_paths": ["a", "b", "c", "d"]}, config={})
    assert result["enabled"] is False
    assert result["chosenTier"] == "build"


def test_complexity_probe_enabled_uses_band() -> None:
    config = {"dispatch": {"complexityProbe": {"enabled": True, "bandFloor": "cheap", "bandCeiling": "deep"}}}
    low = probe_complexity(static_tier="build", signal_context={"file_paths": []}, config=config)
    high = probe_complexity(static_tier="build", signal_context={"file_paths": ["a", "b", "c", "d"]}, config=config)
    assert low["enabled"] is True
    assert low["chosenTier"] == "cheap"
    assert high["chosenTier"] == "deep"


def test_clamp_tier() -> None:
    assert clamp_tier("deep", "cheap", "mid") == "mid"


def test_token_budget_always_advisory() -> None:
    budget = resolve_token_budget({})
    assert budget["enforced"] is False
    assert budget["advisory"] >= 1
    handoff = format_partial_result_handoff(budget)
    assert "partialResult" in handoff
    assert "enforced" in handoff


def test_dispatch_check_reader_missing(repo_root: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "dispatch-check.py"),
            "--agent", "generalPurpose",
            "--command", "sw-feedback",
            "--skill", "feedback",
            "--parent-model", "composer-2.5",
            "--boundary", "feedback-intake",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 20
    data = json.loads(proc.stdout)
    assert data["cause"] == "binding:reader-role-missing"


def test_dispatch_check_includes_token_budget(repo_root: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts" / "dispatch-check.py"),
            "--agent", "generalPurpose",
            "--command", "sw-prd",
            "--parent-model", "composer-2.5",
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    data = json.loads(proc.stdout)
    assert "tokenBudget" in data
    assert data["tokenBudget"]["enforced"] is False
    assert "complexityProbe" in data
