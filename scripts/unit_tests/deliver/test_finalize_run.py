"""Finalize-after-external-merge fixtures (PRD 081 R24, R25)."""

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

from deliver_finalize_fixtures import seed_proven_run_identity
from wave_json_io import read_json, write_json
from wave_run_paths import lease_path, run_directory, state_path
from wave_state import load_run_scoped_state, write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run
from wave_transition_receipt import read_terminal_receipt, terminal_receipt_path


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def _seed_run(tmp_path: Path, run_id: str) -> dict:
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/081-demo/tasks-081-demo.md",
        "target": {"branch": "feat/demo-finalize", "slug": "demo-finalize"},
        "terminalPr": {"number": 99, "headBranch": "feat/demo-finalize"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {"path": str(tmp_path / "orch-wt")},
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
        / "docs/prds/081-demo/tasks-081-demo.md"
    )
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text("# projected\n", encoding="utf-8")
    return seed_proven_run_identity(tmp_path, run_id, state)


def test_finalize_after_external_merge_verifies_receipt_and_immutable(
    tmp_path: Path,
) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-finalize-ok"
    state = _seed_run(tmp_path, run_id)
    merge_info = {
        "merged": True,
        "mergeCommit": "abc123deadbeef",
        "prNumber": 99,
        "mergedAt": "2026-07-27T10:00:00Z",
        "detail": "terminal-pr-host",
    }

    with patch("wave_compound.terminal_pr_merged_via_host", return_value=merge_info):
        payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "pass"
    assert payload["immutable"] is True
    receipt = read_terminal_receipt(tmp_path, run_id)
    assert receipt is not None
    assert receipt["mergeCommit"] == "abc123deadbeef"
    assert receipt["actor"] == "tester"
    assert receipt["releasedResources"]["targetLock"]["verdict"] == "pass"
    assert not lease_path(tmp_path, run_id).is_file()
    assert terminal_receipt_path(tmp_path, run_id).is_file()

    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("immutable") is True
    assert stored.get("verdict") == "finalized"
    assert stored.get("terminalMerge", {}).get("mergeCommit") == "abc123deadbeef"
    assert "orchestratorWorktree" not in stored
    assert stored.get("phaseWorktrees") == {}

    projection = (
        tmp_path
        / ".cursor"
        / "sw-deliver-runs"
        / "_progress-projections"
        / "docs/prds/081-demo/tasks-081-demo.md"
    )
    assert not projection.is_file()


def test_unverifiable_merge_leaves_run_nonterminal(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-finalize-fail"
    state = _seed_run(tmp_path, run_id)

    with patch(
        "wave_compound.terminal_pr_merged_via_host",
        return_value={"merged": False, "reason": "not-merged"},
    ):
        payload = finalize_run(tmp_path, run_id, state)

    assert payload["verdict"] == "fail"
    assert payload["error"] == "terminal-merge-unverified"
    assert read_terminal_receipt(tmp_path, run_id) is None
    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("verdict") == "running"
    assert stored.get("immutable") is not True
    assert lease_path(tmp_path, run_id).is_file()


def test_deliver_finalize_command_delegates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-finalize-cli"
    _seed_run(tmp_path, run_id)

    def _fake_finalize(root: Path, rid: str, state: dict, **kwargs):
        assert rid == run_id
        return {
            "verdict": "pass",
            "action": "run-finalize",
            "immutable": True,
            "terminalReceipt": {"mergeCommit": "feedface"},
        }

    monkeypatch.setattr("wave_terminal.finalize_run", _fake_finalize)
    from wave_deliver import cmd_finalize

    with pytest.raises(SystemExit) as exc:
        cmd_finalize(tmp_path, ["--run-id", run_id])
    assert exc.value.code == 0
