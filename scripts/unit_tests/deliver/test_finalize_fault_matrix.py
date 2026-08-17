"""PRD 276 R16 — crash/fault-injection matrix across finalize phases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import FINALIZE_CHECKPOINT_PHASES, load_finalize_checkpoint
from wave_json_io import write_json
from wave_run_paths import run_directory, state_path
from wave_state import load_run_scoped_state, write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run
from wave_transition_receipt import read_terminal_receipt


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def _seed_run(tmp_path: Path, run_id: str) -> dict:
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/fault-matrix", "slug": "fault-matrix"},
        "terminalPr": {"number": 88, "headBranch": "feat/fault-matrix"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {},
        "phaseWorktrees": {},
    }
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/fault-matrix")
    acquire_target_lock(tmp_path, "feat/fault-matrix", run_id)
    projection = (
        tmp_path
        / ".cursor"
        / "sw-deliver-runs"
        / "_progress-projections"
        / "docs/prds/276-demo/tasks-276-demo.md"
    )
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text("# projected\n", encoding="utf-8")
    return state


def _merge_info() -> dict:
    return {
        "merged": True,
        "mergeCommit": "faultbeef01",
        "prNumber": 88,
        "mergedAt": "2026-08-17T14:00:00Z",
        "detail": "terminal-pr-host",
    }


@pytest.mark.parametrize(
    "fail_phase,patch_target",
    [
        ("release", "wave_terminal.release_run_resources"),
        ("projection", "wave_terminal.close_run_projections"),
        ("receipt", "wave_transition_receipt.persist_terminal_receipt"),
        ("immutable", "wave_state.save_run_scoped_state"),
    ],
)
def test_fault_matrix_phase_failure_typed_resume(
    tmp_path: Path, fail_phase: str, patch_target: str
) -> None:
    _init_repo(tmp_path)
    run_id = f"deliver-fault-{fail_phase}"
    state = _seed_run(tmp_path, run_id)

    with (
        patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()),
        patch(patch_target, side_effect=RuntimeError(f"inject-{fail_phase}")),
    ):
        payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "fail"
    assert payload["halt"] == "finalize:partial"
    assert payload["failedPhase"] == fail_phase
    assert "resumeCommand" in payload
    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt["phases"][fail_phase]["status"] == "failed"
    # Prior phases (if any) remain complete; later phases pending.
    idx = FINALIZE_CHECKPOINT_PHASES.index(fail_phase)
    for prior in FINALIZE_CHECKPOINT_PHASES[:idx]:
        assert ckpt["phases"][prior]["status"] == "complete"
    for later in FINALIZE_CHECKPOINT_PHASES[idx + 1 :]:
        assert ckpt["phases"][later]["status"] == "pending"
    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("immutable") is not True


def test_partial_resource_failure_during_release(tmp_path: Path) -> None:
    """One resource succeeds, another fails — not treated as finalize success (R16)."""
    _init_repo(tmp_path)
    run_id = "deliver-fault-partial-resource"
    state = _seed_run(tmp_path, run_id)

    def _partial_release(root, rid, st):
        return {
            "targetLock": {"verdict": "pass"},
            "runLocalLease": {"verdict": "pass"},
            "scopedDeliverLock": {"verdict": "fail", "error": "scoped-lock-run-mismatch"},
            "worktrees": [],
        }

    with (
        patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()),
        patch("wave_terminal.release_run_resources", side_effect=_partial_release),
    ):
        payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "fail"
    assert payload["halt"] == "finalize:partial"
    assert payload["failedPhase"] == "release"
    assert read_terminal_receipt(tmp_path, run_id) is None
