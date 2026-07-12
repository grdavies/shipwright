"""Unit tests for merge-ready refusal and bypass-flag constraints (PRD 065 R8, R10)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from gate_evidence import (
    attach_provenance_marker,
    build_evidence_record,
    evidence_record_path,
    write_evidence_atomic,
)
from merge_ready_enforcement import evaluate_mandatory_gate_evidence
from ship_loop import (
    BYPASS_FLAG_TO_GATE,
    active_bypass_flags,
    drain_bypassed_steps,
    validate_bypass_flags,
    write_bypass_skip_record,
)


def _execution() -> dict:
    return {
        "argv": ["python3", "scripts/example.py"],
        "exitCode": 0,
        "stdoutDigest": "a" * 64,
        "stderrDigest": "b" * 64,
        "duration": 0.01,
    }


def _write_pass_record(repo_root: Path, phase: str, gate_id: str, *, head: str, tree: str) -> None:
    record = build_evidence_record(
        gate_id=gate_id,
        gate_class="mandatory",
        binding_mode="head-exact",
        evaluation_point="test",
        verdict="pass",
        execution=_execution(),
        root=repo_root,
        head_sha=head,
        tree_hash=tree,
    )
    write_evidence_atomic(evidence_record_path(repo_root, phase, gate_id), record)


@pytest.mark.parametrize(
    "cause_fixture",
    [
        "missing",
        "head-mismatch",
        "tree-mismatch",
        "forged-provenance",
        "non-pass",
    ],
)
def test_merge_ready_refusal_matrix(
    repo_root: Path, tmp_path: Path, cause_fixture: str
) -> None:
    phase = "terminal-enforcement-and-bypass-flag-constraint-r8-r10"
    import subprocess

    head = subprocess.check_output(["git", "-C", str(repo_root), "rev-parse", "HEAD"], text=True).strip()
    from gate_evidence import compute_tree_hash

    tree = compute_tree_hash(repo_root)
    gate_id = "verification-gate"

    if cause_fixture == "missing":
        pass
    elif cause_fixture == "head-mismatch":
        _write_pass_record(repo_root, phase, gate_id, head="0" * 40, tree=tree)
    elif cause_fixture == "tree-mismatch":
        record = build_evidence_record(
            gate_id=gate_id,
            gate_class="mandatory",
            binding_mode="tree-stable",
            evaluation_point="test",
            verdict="pass",
            execution=_execution(),
            root=repo_root,
            head_sha=head,
            tree_hash="1" * 40,
        )
        write_evidence_atomic(evidence_record_path(repo_root, phase, gate_id), record)
    elif cause_fixture == "forged-provenance":
        record = build_evidence_record(
            gate_id=gate_id,
            gate_class="mandatory",
            binding_mode="head-exact",
            evaluation_point="test",
            verdict="pass",
            execution=_execution(),
            root=repo_root,
            head_sha=head,
            tree_hash=tree,
        )
        forged = dict(record)
        forged["provenanceMarker"] = "f" * 64
        write_evidence_atomic(evidence_record_path(repo_root, phase, gate_id), forged)
    elif cause_fixture == "non-pass":
        record = build_evidence_record(
            gate_id=gate_id,
            gate_class="mandatory",
            binding_mode="head-exact",
            evaluation_point="test",
            verdict="fail",
            execution=_execution(),
            root=repo_root,
            head_sha=head,
            tree_hash=tree,
        )
        write_evidence_atomic(evidence_record_path(repo_root, phase, gate_id), record)

    result = evaluate_mandatory_gate_evidence(repo_root, phase, head_sha=head)
    assert result["verdict"] == "fail"
    assert result.get("failures")


def test_bypass_flag_optional_only(repo_root: Path) -> None:
    validate_bypass_flags(repo_root, {"--skip-simplify", "--skip-local", "--fast"})


def test_mandatory_bypass_denied(repo_root: Path) -> None:
    with patch.dict(BYPASS_FLAG_TO_GATE, {"--fast": "verification-gate"}, clear=False):
        with pytest.raises(SystemExit):
            validate_bypass_flags(repo_root, {"--fast"})


def test_bypass_writes_skip_record(repo_root: Path) -> None:
    phase = "terminal-enforcement-and-bypass-flag-constraint-r8-r10"
    path = write_bypass_skip_record(
        repo_root,
        phase,
        "sw-simplify",
        flag="--skip-simplify",
        actor="test",
        reason="unit test",
    )
    from gate_evidence import read_record_file

    record, cause = read_record_file(path)
    assert cause is None
    assert record is not None
    assert record["verdict"] == "skip"
    assert record["gateId"] == "sw-simplify"


def test_drain_bypassed_steps_advances_optional(repo_root: Path, tmp_path: Path) -> None:
    from ship_phase_steps import save_steps

    phase = "terminal-enforcement-and-bypass-flag-constraint-r8-r10"
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    steps_path = run_dir / "ship-steps.json"
    save_steps(
        steps_path,
        {
            "phase": phase,
            "currentStep": "sw-simplify",
            "lastCompletedStep": "sw-review",
            "stepAttempts": {},
            "chain": [
                "sw-tmp-init",
                "sw-execute",
                "sw-verify",
                "verification-gate",
                "sw-review",
                "sw-simplify",
                "gap-check",
                "sw-commit",
            ],
            "chainSource": "test-fixture",
        },
    )
    skipped = drain_bypassed_steps(
        repo_root,
        phase,
        steps_path=steps_path,
        flags={"--skip-simplify"},
    )
    assert skipped == ["sw-simplify"]


def test_active_bypass_flags_from_argv() -> None:
    flags = active_bypass_flags(["run", "--fast", "--skip-local"])
    assert flags == {"--fast", "--skip-local"}
