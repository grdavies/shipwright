"""Zero-interaction ship-loop bar — mechanical vs agent dispatch (PRD 065 R17)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT_DIR = Path(__file__).resolve().parent
_SCRIPTS = SCRIPT_DIR.parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from ship_loop import (
    AGENT_STEPS,
    MECHANICAL_STEPS,
    agent_outcome_binding_valid,
    classify_step,
    consume_agent_outcome,
    drive_tick,
    resolve_run_dir,
)
from ship_phase_steps import advance_step_silent, resolve_steps_path


def test_classify_step_mechanical_vs_agent() -> None:
    for step in MECHANICAL_STEPS:
        assert classify_step(step) == "mechanical"
    for step in AGENT_STEPS:
        assert classify_step(step) == "agent"


def test_drive_tick_mechanical_never_awaits_agent(repo_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    phase = "zero-interaction-mechanical"
    monkeypatch.setenv("SW_PHASE_MODE", "1")
    monkeypatch.setenv("SW_PHASE_SLUG", phase)
    run_dir = resolve_run_dir(repo_root, phase)
    run_dir.mkdir(parents=True, exist_ok=True)
    steps_path = resolve_steps_path(repo_root, phase, None)
    payload = drive_tick(repo_root, phase, steps_path=steps_path)
    assert payload.get("verdict") == "pass"
    assert payload.get("awaitAgent") is False


def test_agent_outcome_rejects_missing_and_forged_head(repo_root: Path, tmp_path: Path) -> None:
    artifact = tmp_path / "execute-integrate.status.json"
    ok, cause = agent_outcome_binding_valid(repo_root, artifact)
    assert not ok
    assert cause == "agent-outcome:missing"

    artifact.write_text(json.dumps({"verdict": "pass", "head": "0" * 40}), encoding="utf-8")
    proc = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    real_head = proc.stdout.strip()
    ok, cause = agent_outcome_binding_valid(repo_root, artifact, head_sha=real_head)
    assert not ok
    assert cause == "agent-outcome:head-mismatch"

    artifact.write_text(json.dumps({"verdict": "pass", "head": real_head}), encoding="utf-8")
    ok, cause = agent_outcome_binding_valid(repo_root, artifact, head_sha=real_head)
    assert ok
    assert cause is None



def test_consume_outcome_fails_without_binding_valid_artifact(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from ship_phase_steps import save_steps

    phase = "zero-interaction-agent"
    monkeypatch.setenv("SW_PHASE_MODE", "1")
    monkeypatch.setenv("SW_PHASE_SLUG", phase)
    run_dir = resolve_run_dir(repo_root, phase)
    run_dir.mkdir(parents=True, exist_ok=True)
    steps_path = resolve_steps_path(repo_root, phase, None)
    chain = [
        "sw-tmp-init", "sw-execute", "sw-verify", "verification-gate", "sw-review",
        "sw-simplify", "gap-check", "sw-commit", "sw-pr", "sw-watch-ci", "sw-stabilize",
        "sw-ready", "sw-tmp-clean",
    ]
    save_steps(steps_path, {
        "phase": phase,
        "currentStep": "sw-execute",
        "lastCompletedStep": "sw-tmp-init",
        "stepAttempts": {},
        "chain": chain,
        "chainSource": "test-fixture",
    })
    result = consume_agent_outcome(repo_root, phase, steps_path=steps_path)
    assert result.get("verdict") == "fail"
    assert "agent-outcome" in str(result.get("cause") or "")



def test_merge_ready_refuses_missing_mandatory_evidence(repo_root: Path) -> None:
    from merge_ready_enforcement import evaluate_mandatory_gate_evidence

    phase = "zero-interaction-gates"
    evaluation = evaluate_mandatory_gate_evidence(repo_root, phase)
    assert evaluation.get("verdict") == "fail"
    assert evaluation.get("halt") == "merge-ready:mandatory-gate-evidence"


def test_zero_interaction_fixture_readme_present(repo_root: Path) -> None:
    readme = repo_root / "scripts/test/fixtures/ship-loop-zero-interaction/README.md"
    frozen = repo_root / "scripts/test/fixtures/ship-loop-zero-interaction/frozen-task-list.md"
    assert readme.is_file()
    assert frozen.is_file()
    assert "frozen: true" in frozen.read_text(encoding="utf-8")
