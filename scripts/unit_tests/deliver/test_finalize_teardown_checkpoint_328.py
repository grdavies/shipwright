"""PRD 328 R6 — combined regression matrix for bootstrap + teardown order."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cleanup_lib import _classify_orphan, enumerate_orphan_worktrees
from deliver_finalize_fixtures import seed_proven_run_identity
from wave_deliver_loop import (
    FINALIZE_CHECKPOINT_PHASES,
    ensure_finalize_scripts_bootstrap,
    load_finalize_checkpoint,
    release_run_resources,
)
from wave_json_io import write_json
from wave_run_paths import run_directory, state_path
from wave_state import write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        text=True,
        capture_output=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q")
    _git(primary, "config", "user.email", "t@t.com")
    _git(primary, "config", "user.name", "Test")
    _git(primary, "commit", "--allow-empty", "-qm", "init")
    _git(primary, "branch", "-M", "main")
    _git(primary, "branch", "feat/matrix-328")
    _git(primary, "checkout", "feat/matrix-328")
    _git(primary, "commit", "--allow-empty", "-qm", "feat tip")
    _git(primary, "checkout", "main")
    return primary


def _seed_finalize_run(primary: Path, run_id: str) -> dict:
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/328-demo/tasks-328-demo.md",
        "target": {"branch": "feat/matrix-328", "slug": "matrix-328"},
        "terminalPr": {"number": 328, "headBranch": "feat/matrix-328"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {},
        "phaseWorktrees": {},
    }
    run_directory(primary, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(primary, run_id), state)
    write_run_local_lease(primary, run_id, "feat/matrix-328")
    acquire_target_lock(primary, "feat/matrix-328", run_id)
    projection = (
        primary
        / ".cursor"
        / "sw-deliver-runs"
        / "_progress-projections"
        / "docs/prds/328-demo/tasks-328-demo.md"
    )
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text("# projected\n", encoding="utf-8")
    return seed_proven_run_identity(primary, run_id, state)


def _merge_info() -> dict:
    return {
        "merged": True,
        "mergeCommit": "328matrixcafe",
        "prNumber": 328,
        "mergedAt": "2026-08-24T18:00:00Z",
        "detail": "terminal-pr-host",
    }


def test_matrix_finalize_without_ambient_pythonpath(
    repo_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """R1 — finalize completes when ambient PYTHONPATH lacks scripts/."""
    primary = _init_repo(tmp_path)
    run_id = "deliver-328-pythonpath-off"
    state = _seed_finalize_run(primary, run_id)

    scripts = str(repo_root / "scripts")
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != scripts])
    sys.modules.pop("planning_txn", None)

    ensure_finalize_scripts_bootstrap(repo_root)
    import planning_txn  # noqa: F401

    with patch(
        "wave_terminal.verify_terminal_merge_via_host",
        return_value={"verdict": "pass", "merged": True, **_merge_info()},
    ):
        payload = finalize_run(primary, run_id, state, actor="tester")

    assert payload["verdict"] == "pass"
    assert payload["immutable"] is True
    ckpt = load_finalize_checkpoint(primary, run_id)
    assert ckpt is not None
    assert ckpt["status"] == "complete"
    for phase in FINALIZE_CHECKPOINT_PHASES:
        assert ckpt["phases"][phase]["status"] == "complete"


def test_matrix_release_phase_before_orch_order(tmp_path: Path) -> None:
    """R3 — phase worktrees are removed before the orchestrator worktree."""
    primary = _init_repo(tmp_path)
    phase_path = str(primary / ".sw-worktrees" / "matrix-phase")
    orch_path = str(primary / ".sw-worktrees" / "matrix-orchestrator")
    state = {
        "target": {"branch": "feat/matrix-328"},
        "phaseWorktrees": {"1": {"path": phase_path}},
        "orchestratorWorktree": {"path": orch_path, "branch": "feat/matrix-328"},
    }
    removed: list[str] = []

    def _track_remove(_top: Path, wt_path: str) -> dict:
        removed.append(wt_path)
        return {"path": wt_path, "removed": True}

    with (
        patch("wave_deliver_loop._git_primary_toplevel", return_value=primary),
        patch("wave_deliver_loop._remove_registered_worktree", side_effect=_track_remove),
        patch("wave_target_lock.release_target_lock", return_value={"verdict": "pass"}),
        patch("wave_run_paths.lease_path", return_value=primary / "no-lease"),
    ):
        payload = release_run_resources(primary, "deliver-328-order", state)

    assert removed == [phase_path, orch_path]
    assert payload.get("gitCwd") == str(primary)


def test_matrix_release_no_orphan_husks(tmp_path: Path) -> None:
    """R5 — ordered teardown leaves no orphan husks that skew resume."""
    primary = _init_repo(tmp_path)
    sw_root = primary / ".sw-worktrees"
    sw_root.mkdir(parents=True, exist_ok=True)
    phase_wt = sw_root / "matrix-328-phase"
    orch_wt = sw_root / "matrix-328-orchestrator"

    _git(primary, "worktree", "add", "-q", "-b", "feat/matrix-328-phase", str(phase_wt), "feat/matrix-328")
    _git(primary, "worktree", "add", "-q", str(orch_wt), "feat/matrix-328")

    state = {
        "target": {"branch": "feat/matrix-328"},
        "phaseWorktrees": {"1": {"path": str(phase_wt)}},
        "orchestratorWorktree": {"path": str(orch_wt), "branch": "feat/matrix-328"},
    }

    payload = release_run_resources(primary, "deliver-328-husks", state)

    assert payload.get("gitCwd") == str(primary)
    assert not phase_wt.exists()
    assert not orch_wt.exists()

    listed = subprocess.check_output(
        ["git", "worktree", "list", "--porcelain"],
        cwd=primary,
        text=True,
    )
    assert str(phase_wt) not in listed
    assert str(orch_wt) not in listed

    orphans = enumerate_orphan_worktrees(primary)
    assert orphans == []
    for child in sw_root.iterdir():
        assert _classify_orphan(child) != "husk"

    worktrees = payload.get("worktrees") or []
    assert len(worktrees) == 2
    assert all(entry.get("removed") for entry in worktrees)
