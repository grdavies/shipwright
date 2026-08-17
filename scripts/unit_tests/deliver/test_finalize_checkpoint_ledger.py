"""PRD 276 R2/R15 — durable finalize checkpoint ledger + primary re-run."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import (
    FINALIZE_CHECKPOINT_PHASES,
    finalize_checkpoint_path,
    load_finalize_checkpoint,
)
from wave_json_io import write_json
from wave_run_paths import lease_path, run_directory, state_path
from wave_state import load_run_scoped_state, scoped_paths, write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run
from wave_transition_receipt import read_terminal_receipt


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def _seed_run(tmp_path: Path, run_id: str, *, with_orch: bool = True) -> dict:
    orch = tmp_path / "orch-wt"
    if with_orch:
        orch.mkdir(parents=True, exist_ok=True)
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/demo-finalize", "slug": "demo-finalize"},
        "terminalPr": {"number": 99, "headBranch": "feat/demo-finalize"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {"path": str(orch)} if with_orch else {},
        "phaseWorktrees": {"1": {"path": str(tmp_path / "phase-wt")}},
    }
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/demo-finalize")
    acquire_target_lock(tmp_path, "feat/demo-finalize", run_id)
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
        "mergeCommit": "abc123deadbeef",
        "prNumber": 99,
        "mergedAt": "2026-08-17T10:00:00Z",
        "detail": "terminal-pr-host",
    }


def test_finalize_writes_checkpoint_ledger_phases(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-ckpt-ok"
    state = _seed_run(tmp_path, run_id)

    with patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()):
        payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "pass"
    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt is not None
    assert ckpt["status"] == "complete"
    assert finalize_checkpoint_path(tmp_path, run_id).is_file()
    for phase in FINALIZE_CHECKPOINT_PHASES:
        assert ckpt["phases"][phase]["status"] == "complete"
    assert ckpt["lastCompletedPhase"] == "immutable"


def test_finalize_rerun_from_primary_after_orch_teardown(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-ckpt-rerun"
    state = _seed_run(tmp_path, run_id, with_orch=True)
    orch = Path(state["orchestratorWorktree"]["path"])

    # Simulate orch teardown before finalize completes.
    if orch.is_dir():
        for child in orch.iterdir():
            if child.is_file():
                child.unlink()
        orch.rmdir()

    with patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()):
        first = finalize_run(tmp_path, run_id, state, actor="primary")
    assert first["verdict"] == "pass"
    assert first["immutable"] is True

    # Idempotent re-run from primary (R2).
    with patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()):
        second = finalize_run(tmp_path, run_id, load_run_scoped_state(tmp_path, run_id))
    assert second["verdict"] == "pass"
    assert second.get("note") == "already finalized"
    receipt = read_terminal_receipt(tmp_path, run_id)
    assert receipt is not None
    assert receipt["mergeCommit"] == "abc123deadbeef"
    assert not lease_path(tmp_path, run_id).is_file()


def test_release_before_complete_is_not_success(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-ckpt-partial"
    state = _seed_run(tmp_path, run_id)

    def _boom(*_a, **_k):
        raise RuntimeError("projection-crash")

    with (
        patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()),
        patch("wave_terminal.close_run_projections", side_effect=_boom),
    ):
        payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "fail"
    assert payload["halt"] == "finalize:partial"
    assert payload["lastCompletedPhase"] == "release"
    assert "resumeCommand" in payload
    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt["phases"]["release"]["status"] == "complete"
    assert ckpt["phases"]["projection"]["status"] == "failed"
    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("immutable") is not True
    assert stored.get("verdict") == "running"
