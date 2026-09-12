"""PRD 348 R2/R3/R3a — finalize hash rebind + dead orchestrator worktree clearance."""

from __future__ import annotations

import copy
import subprocess
from pathlib import Path

from checkbox_diff import is_checkbox_only_diff
from wave_finalize import (
    clear_dead_orchestrator_worktree,
    orchestrator_worktree_is_dead,
    prepare_finalize_recovery,
    rebind_source_task_list_content_hash,
)
from wave_run_adopt import compute_task_list_content_hash


def _init_repo(root: Path) -> None:
    """Materialize hash helpers require a git worktree root."""
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-qm", "init"],
        cwd=root,
        check=True,
    )


def _write_task_list(root: Path, rel: str, body: str) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_rebind_source_task_list_hash_on_checkbox_diverged_materialize(
    tmp_path: Path,
) -> None:
    """R2 — checkbox-only materialize edits rebind sourceTaskListContentHash."""
    _init_repo(tmp_path)
    rel = "docs/prds/348-demo/tasks-348-demo.md"
    freeze_body = (
        "# Tasks\n\n"
        "- [ ] 2.1 Rebind hash\n"
        "- [ ] 2.2 Clear dead orch\n"
    )
    materialize_body = (
        "# Tasks\n\n"
        "- [x] 2.1 Rebind hash\n"
        "- [x] 2.2 Clear dead orch\n"
    )
    assert is_checkbox_only_diff(freeze_body, materialize_body)

    _write_task_list(tmp_path, rel, freeze_body)
    freeze_hash = compute_task_list_content_hash(tmp_path, rel)
    assert freeze_hash is not None

    _write_task_list(tmp_path, rel, materialize_body)
    materialize_hash = compute_task_list_content_hash(tmp_path, rel)
    assert materialize_hash is not None
    assert materialize_hash != freeze_hash

    state = {
        "runId": "deliver-348-hash-rebind",
        "source_task_list": rel,
        "sourceTaskListContentHash": freeze_hash,
    }
    result = rebind_source_task_list_content_hash(
        tmp_path, state, prior_text=freeze_body
    )
    assert result["rebound"] is True
    assert state["sourceTaskListContentHash"] == materialize_hash
    assert result["previousHash"] == freeze_hash
    assert result["newHash"] == materialize_hash


def test_rebind_skips_non_checkbox_divergence(tmp_path: Path) -> None:
    """R2 — non-checkbox divergence with prior_text does not rebind."""
    _init_repo(tmp_path)
    rel = "docs/prds/348-demo/tasks-348-noncb.md"
    freeze_body = "# Tasks\n\n- [ ] 2.1 Rebind hash\n"
    diverged = "# Tasks\n\n- [ ] 2.1 Rebind hash AND more scope\n"
    assert not is_checkbox_only_diff(freeze_body, diverged)

    _write_task_list(tmp_path, rel, freeze_body)
    freeze_hash = compute_task_list_content_hash(tmp_path, rel)
    _write_task_list(tmp_path, rel, diverged)

    state = {
        "source_task_list": rel,
        "sourceTaskListContentHash": freeze_hash,
    }
    result = rebind_source_task_list_content_hash(
        tmp_path, state, prior_text=freeze_body
    )
    assert result["rebound"] is False
    assert result["reason"] == "divergence-not-checkbox-only"
    assert state["sourceTaskListContentHash"] == freeze_hash


def test_dead_worktree_detection_missing_path() -> None:
    """R3 — missing worktree directory is dead."""
    dead, reason = orchestrator_worktree_is_dead(
        {"path": "/tmp/sw-definitely-missing-orch-348", "pid": 1}
    )
    assert dead is True
    assert reason == "worktree-missing"


def test_dead_worktree_detection_pid_absent(tmp_path: Path) -> None:
    """R3 — recorded PID absent from process table is dead even if path exists."""
    orch_path = tmp_path / "orch-wt"
    orch_path.mkdir()
    dead, reason = orchestrator_worktree_is_dead(
        {"path": str(orch_path), "pid": 2_147_483_646}
    )
    assert dead is True
    assert reason == "pid-absent"


def test_live_worktree_not_cleared(tmp_path: Path) -> None:
    """R3 — live path with current PID is not cleared."""
    import os

    orch_path = tmp_path / "live-orch"
    orch_path.mkdir()
    state = {
        "orchestratorWorktree": {"path": str(orch_path), "pid": os.getpid()},
    }
    checkpoint = {"status": "in-progress", "phases": {"release": {"status": "complete"}}}
    before = copy.deepcopy(checkpoint)
    result = clear_dead_orchestrator_worktree(state, checkpoint=checkpoint)
    assert result["cleared"] is False
    assert "orchestratorWorktree" in state
    assert checkpoint == before


def test_dead_worktree_clearance_preserves_checkpoint(tmp_path: Path) -> None:
    """R3a — clearing dead orch does not discard durable checkpoint data."""
    state = {
        "runId": "deliver-348-dead-orch",
        "orchestratorWorktree": {
            "path": str(tmp_path / "gone-orch"),
            "pid": 2_147_483_645,
        },
    }
    checkpoint = {
        "status": "in-progress",
        "mergeCommit": "abc123",
        "phases": {
            "release": {"status": "complete", "result": {"ok": True}},
            "projection": {"status": "started"},
        },
    }
    before = copy.deepcopy(checkpoint)
    result = clear_dead_orchestrator_worktree(state, checkpoint=checkpoint)
    assert result["cleared"] is True
    assert result["checkpointPreserved"] is True
    assert "orchestratorWorktree" not in state
    assert checkpoint == before
    assert checkpoint["phases"]["release"]["result"]["ok"] is True


def test_prepare_finalize_recovery_hash_and_dead_orch(tmp_path: Path) -> None:
    """R2+R3 — combined recovery rebinds hash and clears dead orch without touching checkpoint."""
    _init_repo(tmp_path)
    rel = "docs/prds/348-demo/tasks-348-combined.md"
    freeze_body = "# Tasks\n\n- [ ] 2.1 Work\n"
    materialize_body = "# Tasks\n\n- [x] 2.1 Work\n"
    _write_task_list(tmp_path, rel, freeze_body)
    freeze_hash = compute_task_list_content_hash(tmp_path, rel)
    _write_task_list(tmp_path, rel, materialize_body)

    state = {
        "runId": "deliver-348-combined",
        "source_task_list": rel,
        "sourceTaskListContentHash": freeze_hash,
        "orchestratorWorktree": {"path": str(tmp_path / "missing-orch")},
    }
    checkpoint = {"status": "in-progress", "phases": {"release": {"status": "complete"}}}
    before = copy.deepcopy(checkpoint)

    result = prepare_finalize_recovery(
        tmp_path,
        state,
        run_id="deliver-348-combined",
        persist=False,
        prior_task_list_text=freeze_body,
        checkpoint=checkpoint,
    )
    assert result["mutated"] is True
    assert result["hashRebind"]["rebound"] is True
    assert result["orchClearance"]["cleared"] is True
    assert "orchestratorWorktree" not in state
    assert state["sourceTaskListContentHash"] != freeze_hash
    assert checkpoint == before
