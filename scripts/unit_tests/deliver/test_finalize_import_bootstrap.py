"""PRD 328 R1/R2 — finalize scripts bootstrap and checkpoint repair."""

from __future__ import annotations

import os
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


def _repo_with_orchestrator(tmp_path: Path) -> tuple[Path, Path]:
    primary = tmp_path / "primary"
    primary.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=primary, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=primary, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-qm", "init"], cwd=primary, check=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=primary, check=True)
    subprocess.run(["git", "branch", "feat/r10-bind"], cwd=primary, check=True)
    orch = primary / ".sw-worktrees" / "r10-orchestrator"
    orch.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "worktree", "add", "-q", str(orch), "feat/r10-bind"],
        cwd=primary,
        check=True,
    )
    return primary, orch


def test_finalize_primary_bind_before_release(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """R10 — chdir/sys.path/import/root bind before release_run_resources."""
    primary, orch = _repo_with_orchestrator(tmp_path)
    run_id = "deliver-r10-primary-bind"
    state = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/362-demo/tasks-362-demo.md",
        "target": {"branch": "feat/r10-bind", "slug": "r10-bind"},
        "terminalPr": {"number": 362, "headBranch": "feat/r10-bind"},
        "phases": {"1": {"status": "green-merged", "slug": "phase-one"}},
        "orchestratorWorktree": {"path": str(orch), "branch": "feat/r10-bind"},
        "phaseWorktrees": {},
    }
    run_directory(primary, run_id).mkdir(parents=True, exist_ok=True)
    write_json(state_path(primary, run_id), state)
    write_run_local_lease(primary, run_id, "feat/r10-bind")
    acquire_target_lock(primary, "feat/r10-bind", run_id)
    seed_proven_run_identity(primary, run_id, state)
    task_rel = Path("docs/prds/362-demo/tasks-362-demo.md")
    for root in (primary, orch):
        task_path = root / task_rel
        task_path.parent.mkdir(parents=True, exist_ok=True)
        task_path.write_text("# tasks\n", encoding="utf-8")
        projection = (
            root
            / ("." + "cursor")
            / "sw-deliver-runs"
            / "_progress-projections"
            / task_rel
        )
        projection.parent.mkdir(parents=True, exist_ok=True)
        projection.write_text("# projected\n", encoding="utf-8")

    monkeypatch.chdir(orch)
    import wave_deliver_loop as wave_deliver_loop_mod
    from sw_scripts_resolve import ensure_scripts_on_path

    scripts_entry = str(
        ensure_scripts_on_path(primary.resolve(), executor=Path(wave_deliver_loop_mod.__file__)).resolve()
    )
    monkeypatch.setattr(
        sys,
        "path",
        [p for p in sys.path if Path(p).resolve() != Path(scripts_entry)],
    )
    sys.modules.pop("deliver_closeout", None)
    sys.modules.pop("planning_projection_ledger", None)

    captured: dict[str, object] = {}

    def _capture_release(root: Path, rid: str, st: dict) -> dict:
        captured["cwd"] = Path.cwd().resolve()
        captured["root"] = root.resolve()
        captured["scripts_on_path"] = scripts_entry in sys.path
        captured["deliver_closeout"] = sys.modules.get("deliver_closeout")
        captured["planning_projection_ledger"] = sys.modules.get("planning_projection_ledger")
        return {"worktrees": [], "gitCwd": str(root)}

    merge_info = {
        "merged": True,
        "mergeCommit": "r10primarycafe",
        "prNumber": 362,
        "mergedAt": "2026-08-24T18:00:00Z",
        "detail": "terminal-pr-host",
    }

    safe_cwd = SCRIPT_DIR.parent
    try:
        with (
            patch(
                "wave_terminal.verify_terminal_merge_via_host",
                return_value={"verdict": "pass", "merged": True, **merge_info},
            ),
            patch("wave_terminal.release_run_resources", side_effect=_capture_release),
        ):
            payload = finalize_run(orch, run_id, state, actor="tester")
    finally:
        os.chdir(safe_cwd)

    assert payload["verdict"] == "pass"
    assert captured["cwd"] == primary.resolve()
    assert captured["root"] == primary.resolve()
    assert captured["scripts_on_path"] is True
    assert captured["deliver_closeout"] is not None
    assert captured["planning_projection_ledger"] is not None


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
        / ("." + "cursor")
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
