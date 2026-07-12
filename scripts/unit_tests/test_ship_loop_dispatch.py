"""Unit tests for deliver ship-loop dispatch integration (PRD 065 R3, R4, R26, R27, R28)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ship_loop import (
    consume_agent_outcome,
    drive_tick,
    outcome_artifact_path,
    step_attempt_budget_exhausted,
)
from ship_phase_steps import load_steps, save_steps
from wave_lock import ship_lease_is_stale, ship_lease_owner_live


def test_lease_liveness_heartbeat_only() -> None:
    fresh = {"heartbeatAt": "2099-01-01T00:00:00Z", "shipSteps": {"currentStep": "sw-execute"}}
    assert ship_lease_owner_live(fresh) is True
    stale = {"heartbeatAt": "2020-01-01T00:00:00Z", "shipSteps": {"currentStep": "sw-execute"}}
    assert ship_lease_is_stale(stale) is True
    assert ship_lease_owner_live(stale) is False


def test_drive_tick_awaits_agent_on_execute(repo_root: Path, tmp_path: Path) -> None:
    phase = "deliver-integration-dispatch-interactive-parity-watchdog-and-lease-liveness-r3-r4-r26-r27-r28"
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    steps_path = run_dir / "ship-steps.json"
    chain = ["sw-tmp-init", "sw-execute", "sw-verify"]
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "sw-execute",
            "lastCompletedStep": "sw-tmp-init",
            "stepAttempts": {},
            "chain": chain,
            "chainSource": "test-fixture",
        },
    )
    import os

    os.environ["SW_RUN_DIR"] = str(run_dir)
    try:
        payload = drive_tick(repo_root, phase, steps_path=steps_path)
    finally:
        os.environ.pop("SW_RUN_DIR", None)
    assert payload.get("awaitAgent") is True
    assert payload.get("step") == "sw-execute"
    assert payload.get("contract", {}).get("expectedOutcomeArtifact")


def test_consume_agent_outcome_advances(repo_root: Path, tmp_path: Path) -> None:
    phase = "deliver-integration-dispatch-interactive-parity-watchdog-and-lease-liveness-r3-r4-r26-r27-r28"
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    steps_path = run_dir / "ship-steps.json"
    chain = ["sw-tmp-init", "sw-execute", "sw-verify"]
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "sw-execute",
            "lastCompletedStep": "sw-tmp-init",
            "stepAttempts": {"sw-execute": 1},
            "chain": chain,
            "chainSource": "test-fixture",
        },
    )
    import subprocess

    head = subprocess.check_output(["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True).strip()
    artifact = outcome_artifact_path("sw-execute", run_dir)
    artifact.write_text(
        json.dumps({"verdict": "pass", "head": head, "action": "execute-integrate"}) + "\n",
        encoding="utf-8",
    )
    import os

    os.environ["SW_RUN_DIR"] = str(run_dir)
    try:
        consumed = consume_agent_outcome(repo_root, phase, steps_path=steps_path)
    finally:
        os.environ.pop("SW_RUN_DIR", None)
    assert consumed.get("verdict") == "pass"
    doc = load_steps(steps_path)
    assert doc is not None
    assert doc.get("currentStep") == "sw-verify"


def test_agent_budget_exhausted() -> None:
    doc = {"stepAttempts": {"sw-execute": 2}}
    assert step_attempt_budget_exhausted(doc, "sw-execute", budget=2) is True
    assert step_attempt_budget_exhausted(doc, "sw-execute", budget=3) is False
