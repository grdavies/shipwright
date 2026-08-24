"""PRD 328 R1/R2 — finalize scripts bootstrap and checkpoint repair."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from deliver_finalize_fixtures import seed_proven_run_identity
from wave_deliver_loop import (
    FINALIZE_CHECKPOINT_PHASES,
    ensure_finalize_scripts_bootstrap,
    finalize_checkpoint_needs_repair,
    load_finalize_checkpoint,
    repair_finalize_checkpoint_from_immutable,
)
from wave_json_io import write_json
from wave_run_paths import run_directory, state_path
from wave_state import load_run_scoped_state, write_run_local_lease
from wave_target_lock import acquire_target_lock
from wave_terminal import finalize_run
from wave_transition_receipt import persist_terminal_receipt, read_terminal_receipt


def _init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=tmp_path, check=True)


def _seed_run(tmp_path: Path, run_id: str) -> dict:
    state = {
        "runId": run_id,
        "verdict": "finalized",
        "immutable": True,
        "finalizedAt": "2026-08-24T18:00:00Z",
        "terminalMerge": {
            "mergeCommit": "immutablecafe01",
            "prNumber": 42,
            "mergedAt": "2026-08-24T17:00:00Z",
        },
        "source_task_list": "docs/prds/328-demo/tasks-328-demo.md",
        "target": {"branch": "feat/import-bootstrap", "slug": "import-bootstrap"},
        "terminalPr": {"number": 42, "headBranch": "feat/import-bootstrap"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {},
        "phaseWorktrees": {},
    }
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/import-bootstrap")
    acquire_target_lock(tmp_path, "feat/import-bootstrap", run_id)
    return seed_proven_run_identity(tmp_path, run_id, state)


def test_finalize_bootstrap_imports_planning_txn_without_pythonpath(
    repo_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PYTHONPATH", raising=False)
    scripts = str(repo_root / "scripts")
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != scripts])
    sys.modules.pop("planning_txn", None)

    ensure_finalize_scripts_bootstrap(repo_root)
    import planning_txn  # noqa: F401


def test_repair_checkpoint_when_immutable_without_complete_ledger(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-immutable-repair"
    state = _seed_run(tmp_path, run_id)
    persist_terminal_receipt(
        tmp_path,
        run_id,
        {
            "mergeCommit": "immutablecafe01",
            "actor": "tester",
            "releasedResources": {},
        },
    )

    assert load_finalize_checkpoint(tmp_path, run_id) is None
    assert finalize_checkpoint_needs_repair(None, immutable_written=True)

    repaired, err = repair_finalize_checkpoint_from_immutable(
        tmp_path, run_id, state, checkpoint=None
    )
    assert err is None
    assert repaired is not None
    assert repaired["status"] == "complete"
    assert repaired.get("repairedFromImmutable") is True
    for phase in FINALIZE_CHECKPOINT_PHASES:
        assert repaired["phases"][phase]["status"] == "complete"


def test_finalize_run_repairs_checkpoint_after_immutable_write_crash(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-immutable-crash"
    state = _seed_run(tmp_path, run_id)
    persist_terminal_receipt(
        tmp_path,
        run_id,
        {
            "mergeCommit": "immutablecafe01",
            "actor": "tester",
            "releasedResources": {},
        },
    )

    payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "pass"
    assert payload["immutable"] is True
    assert payload.get("note") == "checkpoint repaired from immutable state"
    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt is not None
    assert ckpt["status"] == "complete"
    assert read_terminal_receipt(tmp_path, run_id) is not None
    stored = load_run_scoped_state(tmp_path, run_id)
    assert stored.get("immutable") is True


def test_finalize_succeeds_without_ambient_pythonpath(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_repo(tmp_path)
    run_id = "deliver-bootstrap-save"
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks-276-demo.md",
        "target": {"branch": "feat/bootstrap-save", "slug": "bootstrap-save"},
        "terminalPr": {"number": 55, "headBranch": "feat/bootstrap-save"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {},
        "phaseWorktrees": {},
    }
    run_directory(tmp_path, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(tmp_path, run_id), state)
    write_run_local_lease(tmp_path, run_id, "feat/bootstrap-save")
    acquire_target_lock(tmp_path, "feat/bootstrap-save", run_id)
    seed_proven_run_identity(tmp_path, run_id, state)
    projection = (
        tmp_path
        / ".cursor"
        / "sw-deliver-runs"
        / "_progress-projections"
        / "docs/prds/276-demo/tasks-276-demo.md"
    )
    projection.parent.mkdir(parents=True, exist_ok=True)
    projection.write_text("# projected\n", encoding="utf-8")

    merge_info = {
        "merged": True,
        "mergeCommit": "bootstrabcafe",
        "prNumber": 55,
        "mergedAt": "2026-08-24T18:00:00Z",
        "detail": "terminal-pr-host",
    }

    scripts = str(SCRIPT_DIR)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != scripts])
    sys.modules.pop("planning_txn", None)

    with patch(
        "wave_terminal.verify_terminal_merge_via_host",
        return_value={"verdict": "pass", "merged": True, **merge_info},
    ):
        payload = finalize_run(tmp_path, run_id, state, actor="tester")

    assert payload["verdict"] == "pass"
    assert payload["immutable"] is True
    ckpt = load_finalize_checkpoint(tmp_path, run_id)
    assert ckpt is not None
    assert ckpt["status"] == "complete"
