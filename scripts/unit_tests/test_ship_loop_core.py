"""Unit tests for ship-loop driver classification and durable resume (PRD 065 R1, R2, R23)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kernel_classification import normalize_step
from ship_loop import AGENT_STEPS, MECHANICAL_STEPS, classify_step, resume_from_durable, step_dispatch
from ship_phase_steps import cmd_advance, load_steps, resolve_steps_path, save_steps


def test_mechanical_agent_split() -> None:
    for step in MECHANICAL_STEPS:
        assert classify_step(step) == "mechanical"
    for step in AGENT_STEPS:
        assert classify_step(step) == "agent"


def test_resume_from_durable_without_chat(repo_root: Path, tmp_path: Path) -> None:
    phase = "ship-loop-driver-core-step-classification-and-durable-resume-r1-r2-r23"
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    steps_path = run_dir / "ship-steps.json"
    chain = [
        "sw-tmp-init",
        "sw-execute",
        "sw-verify",
        "verification-gate",
        "sw-review",
        "sw-simplify",
        "gap-check",
        "sw-commit",
        "sw-pr",
        "sw-watch-ci",
        "sw-stabilize",
        "sw-ready",
        "sw-tmp-clean",
    ]
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "sw-verify",
            "lastCompletedStep": "sw-execute",
            "stepAttempts": {"sw-execute": 1},
            "chain": chain,
            "chainSource": "test-fixture",
        },
    )
    payload = resume_from_durable(repo_root, phase, steps_path=steps_path)
    assert payload["verdict"] == "pass"
    assert payload["currentStep"] == "sw-verify"
    assert payload["classification"] == "mechanical"
    assert payload["complete"] is False


def test_agent_step_emits_await_agent_contract(repo_root: Path, tmp_path: Path) -> None:
    phase = "ship-loop-driver-core-step-classification-and-durable-resume-r1-r2-r23"
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    steps_path = run_dir / "ship-steps.json"
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "sw-execute",
            "lastCompletedStep": "sw-tmp-init",
            "stepAttempts": {},
            "chain": ["sw-tmp-init", "sw-execute", "sw-verify"],
            "chainSource": "test-fixture",
        },
    )
    payload = step_dispatch(repo_root, phase, steps_path=steps_path)
    assert payload["awaitAgent"] is True
    assert payload["classification"] == "agent"
    assert payload["contract"]["expectedOutcomeArtifact"]


def test_kernel_ordering_enforced_on_advance(repo_root: Path, tmp_path: Path) -> None:
    phase = "ship-loop-driver-core-step-classification-and-durable-resume-r1-r2-r23"
    steps_path = tmp_path / "ship-steps.json"
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "sw-tmp-init",
            "lastCompletedStep": None,
            "stepAttempts": {},
            "chain": ["sw-tmp-init", "sw-execute", "sw-verify"],
            "chainSource": "test-fixture",
        },
    )
    proc = subprocess.run(
        [
            "python3",
            str(repo_root / "scripts" / "ship_loop.py"),
            str(repo_root),
            "advance",
            "--phase",
            phase,
            "--step",
            "sw-verify",
            "--out",
            str(steps_path),
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode != 0
    assert "out-of-order" in proc.stderr.lower() or "out-of-order" in proc.stdout.lower()


def test_wave_ship_loop_entrypoint(repo_root: Path) -> None:
    phase = "ship-loop-driver-core-step-classification-and-durable-resume-r1-r2-r23"
    proc = subprocess.run(
        [
            "python3",
            str(repo_root / "scripts" / "wave.py"),
            "ship-loop",
            "chain",
            "--phase",
            phase,
        ],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    payload = json.loads(proc.stdout)
    assert payload["verdict"] == "pass"
    assert payload["chainSource"] in {"canonical-fallback", "persisted-plan"}
    assert normalize_step(payload["chain"][0]) == "sw-tmp-init"

