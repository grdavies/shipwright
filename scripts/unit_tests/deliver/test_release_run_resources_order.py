"""PRD 328 R3/R5 — phase-before-orch release_run_resources ordering."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import release_run_resources


def test_release_run_resources_removes_phase_before_orch(tmp_path: Path) -> None:
    phase_path = str(tmp_path / "phase-wt")
    orch_path = str(tmp_path / "orch-wt")
    state = {
        "target": {"branch": "feat/demo"},
        "phaseWorktrees": {"1": {"path": phase_path}},
        "orchestratorWorktree": {"path": orch_path, "branch": "feat/demo"},
    }
    removed: list[str] = []

    def _track_remove(_top: Path, wt_path: str) -> dict:
        removed.append(wt_path)
        return {"path": wt_path, "removed": True}

    with (
        patch("wave_deliver_loop._git_primary_toplevel", return_value=tmp_path),
        patch("wave_deliver_loop._remove_registered_worktree", side_effect=_track_remove),
        patch("wave_target_lock.release_target_lock", return_value={"verdict": "pass"}),
        patch("wave_run_paths.lease_path", return_value=tmp_path / "no-lease"),
    ):
        payload = release_run_resources(tmp_path, "deliver-order-test", state)

    assert removed == [phase_path, orch_path]
    assert payload.get("gitCwd") == str(tmp_path)
