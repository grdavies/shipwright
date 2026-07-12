"""Unit tests for mechanical gate handlers and evidence writes (PRD 065 R9)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gate_evidence import evidence_record_path, read_record_file
from ship_gate_handlers import R9_GATE_IDS, build_gate_argv, is_gate_handler_step, run_gate_handler
from ship_loop import execute_mechanical_step, step_dispatch


def _mock_execution(argv: list[str]) -> tuple[int, dict]:
    return 0, {
        "argv": [str(part) for part in argv],
        "exitCode": 0,
        "stdoutDigest": "a" * 64,
        "stderrDigest": "b" * 64,
        "duration": 0.01,
    }



def test_r9_gate_id_coverage() -> None:
    expected = {
        "behavioral-anomaly",
        "build-chain",
        "pre-pr-smoke",
        "decision-log",
        "verification-gate",
    }
    assert R9_GATE_IDS == expected
    for gate_id in expected:
        assert is_gate_handler_step(gate_id)


@pytest.mark.parametrize("gate_id", sorted(R9_GATE_IDS))
def test_build_gate_argv_uses_manifest_scripts(repo_root: Path, tmp_path: Path, gate_id: str) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sw-verify.status.json").write_text('{"verdict":"pass"}\n', encoding="utf-8")
    (run_dir / "ship-steps.json").write_text('{"currentStep":"sw-verify"}\n', encoding="utf-8")
    argv = build_gate_argv(repo_root, gate_id, run_dir)
    assert argv[0]
    assert any("scripts" in part or part.endswith(".py") for part in argv)


@pytest.mark.parametrize("gate_id", sorted(R9_GATE_IDS))
def test_run_gate_handler_writes_evidence_with_execution_proof(
    repo_root: Path, tmp_path: Path, gate_id: str
) -> None:
    phase = "mechanical-gate-handlers-and-evidence-writers-r9"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "sw-verify.status.json").write_text('{"verdict":"pass"}\n', encoding="utf-8")
    (run_dir / "ship-steps.json").write_text('{"currentStep":"sw-verify"}\n', encoding="utf-8")

    with patch("ship_gate_handlers.capture_execution", side_effect=lambda argv, **kw: _mock_execution(argv)):
        result = run_gate_handler(repo_root, phase, gate_id, run_dir)

    assert result["verdict"] == "pass"
    assert result["gateId"] == gate_id
    execution = result["execution"]
    assert execution["argv"]
    assert execution["exitCode"] == 0
    assert len(execution["stdoutDigest"]) == 64
    assert len(execution["stderrDigest"]) == 64
    assert execution["duration"] >= 0

    evidence_path = evidence_record_path(repo_root, phase, gate_id)
    record, cause = read_record_file(evidence_path)
    assert cause is None
    assert record is not None
    assert record["gateId"] == gate_id
    assert record["execution"] == execution
    assert record["verdict"] == "pass"


def test_step_dispatch_flags_r9_gate_handler(repo_root: Path, tmp_path: Path) -> None:
    from ship_phase_steps import save_steps

    phase = "mechanical-gate-handlers-and-evidence-writers-r9"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    steps_path = run_dir / "ship-steps.json"
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "verification-gate",
            "lastCompletedStep": "sw-verify",
            "stepAttempts": {},
            "chain": ["sw-verify", "verification-gate", "sw-commit"],
            "chainSource": "test-fixture",
        },
    )
    payload = step_dispatch(repo_root, phase, steps_path=steps_path)
    assert payload["classification"] == "mechanical"
    assert payload["awaitAgent"] is False
    assert payload["isGateHandler"] is True
    assert payload["executeMechanical"] == "gate-handler"


def test_execute_mechanical_step_advances_on_pass(repo_root: Path, tmp_path: Path) -> None:
    from ship_phase_steps import load_steps, save_steps

    phase = "mechanical-gate-handlers-and-evidence-writers-r9"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    steps_path = run_dir / "ship-steps.json"
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "verification-gate",
            "lastCompletedStep": "sw-verify",
            "stepAttempts": {},
            "chain": ["sw-verify", "verification-gate", "sw-commit"],
            "chainSource": "test-fixture",
        },
    )

    with patch("ship_gate_handlers.capture_execution", side_effect=lambda argv, **kw: _mock_execution(argv)), patch(
        "ship_phase_steps.emit"
    ):
        payload = execute_mechanical_step(repo_root, phase, steps_path=steps_path)

    assert payload["gateHandler"] is True
    doc = load_steps(steps_path)
    assert doc["lastCompletedStep"] == "verification-gate"
