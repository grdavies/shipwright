"""PRD 276 R4 — partial finalize leaves typed resume path."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from deliver_finalize_fixtures import seed_proven_run_identity
from wave_deliver_loop import load_finalize_checkpoint, resume_finalize_command
from wave_json_io import write_json
from wave_run_paths import lease_path, run_directory, state_path
from wave_state import load_run_scoped_state, write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run
from wave_transition_receipt import read_terminal_receipt


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def _seed_run(tmp_path: Path, run_id: str) -> dict:
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/partial-finalize", "slug": "partial-finalize"},
        "terminalPr": {"number": 77, "headBranch": "feat/partial-finalize"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {"path": str(tmp_path / "orch-wt")},
        "phaseWorktrees": {},
    }
    (tmp_path / "orch-wt").mkdir(parents=True, exist_ok=True)
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/partial-finalize")
    acquire_target_lock(tmp_path, "feat/partial-finalize", run_id)
    projection = (
        tmp_path
        / ".cursor"
        / "sw-deliver-runs"
        / "_progress-projections"
        / "docs/prds/276-demo/tasks-276-demo.md"
    )
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text("# projected\n", encoding="utf-8")
    return seed_proven_run_identity(tmp_path, run_id, state)


def _merge_info() -> dict:
    return {
        "merged": True,
        "mergeCommit": "partialcafe01",
        "prNumber": 77,
        "mergedAt": "2026-08-17T13:00:00Z",
        "detail": "terminal-pr-host",
    }


def test_partial_finalize_typed_resume_after_release(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-partial-resume"
    state = _seed_run(tmp_path, run_id)

    with (
        patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()),
        patch(
            "wave_terminal.close_run_projections",
            side_effect=RuntimeError("ModuleNotFoundError: boom"),
        ),
    ):
        partial = finalize_run(tmp_path, run_id, state, actor="tester")

    assert partial["verdict"] == "fail"
    assert partial["halt"] == "finalize:partial"
    assert partial["cause"] == "finalize:checkpoint-incomplete"
    assert partial["lastCompletedPhase"] == "release"
    assert partial["resumeCommand"] == resume_finalize_command(run_id)
    assert "checkpointPath" in partial
    # Release happened — lease gone — but run is not stuck without guidance.
    assert not lease_path(tmp_path, run_id).is_file()
    assert read_terminal_receipt(tmp_path, run_id) is None
    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("immutable") is not True

    # Resume from last checkpoint completes remaining phases (R4/R15).
    with patch("wave_compound.terminal_pr_merged_via_host", return_value=_merge_info()):
        resumed = finalize_run(tmp_path, run_id, stored, actor="tester")

    assert resumed["verdict"] == "pass"
    assert resumed["immutable"] is True
    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt["status"] == "complete"
    assert ckpt["phases"]["release"]["status"] == "complete"
    assert ckpt["phases"]["projection"]["status"] == "complete"
    assert ckpt["phases"]["receipt"]["status"] == "complete"
    assert ckpt["phases"]["immutable"]["status"] == "complete"
    assert read_terminal_receipt(tmp_path, run_id) is not None
    final = load_run_scoped_state(tmp_path, run_id)
    assert final.get("immutable") is True
    assert final.get("verdict") == "finalized"
