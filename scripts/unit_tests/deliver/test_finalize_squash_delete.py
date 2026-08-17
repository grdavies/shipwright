"""PRD 276 R3 — squash-delete merge evidence via host PR."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_json_io import write_json
from wave_run_paths import run_directory, state_path
from wave_state import load_run_scoped_state, write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run, verify_terminal_merge_via_host
from wave_transition_receipt import read_terminal_receipt


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "checkout", "-qb", "feat/squash-demo"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "feat"], cwd=tmp_path, check=True)


def _seed_run(tmp_path: Path, run_id: str) -> dict:
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/squash-demo", "slug": "squash-demo"},
        "terminalPr": {"number": 42, "headBranch": "feat/squash-demo"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {},
        "phaseWorktrees": {},
    }
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/squash-demo")
    acquire_target_lock(tmp_path, "feat/squash-demo", run_id)
    return state


def test_finalize_uses_host_pr_merge_when_branch_deleted(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-squash-delete"
    state = _seed_run(tmp_path, run_id)

    # Squash-merge deletes the feature branch tip from the local repo.
    subprocess.run(["git", "checkout", "-q", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "-D", "feat/squash-demo"], cwd=tmp_path, check=True)
    gone = subprocess.run(
        ["git", "rev-parse", "feat/squash-demo"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert gone.returncode != 0

    merge_info = {
        "merged": True,
        "mergeCommit": "squashdeadbeef01",
        "prNumber": 42,
        "mergedAt": "2026-08-17T12:00:00Z",
        "detail": "terminal-pr-host",
    }

    with patch("wave_compound.terminal_pr_merged_via_host", return_value=merge_info) as host_mock:
        verified = verify_terminal_merge_via_host(tmp_path, state)
        assert verified["verdict"] == "pass"
        assert verified["mergeCommit"] == "squashdeadbeef01"
        payload = finalize_run(tmp_path, run_id, state, actor="tester")
        assert host_mock.called

    assert payload["verdict"] == "pass"
    assert payload["immutable"] is True
    receipt = read_terminal_receipt(tmp_path, run_id)
    assert receipt is not None
    assert receipt["mergeCommit"] == "squashdeadbeef01"
    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("terminalMerge", {}).get("mergeCommit") == "squashdeadbeef01"
