"""PRD 276 R9/R10/R12 — exclusive runId lease before mutation; single driver."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

SCRIPT_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_deliver_loop import ensure_exclusive_run_lease, save_state
from wave_lock import acquire_run_lease, run_lease_path_for
from wave_state import utc_now


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".cursor").mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def test_lease_acquired_before_run_state_mutation(repo: Path) -> None:
    """R9 — deliver-loop acquires exclusive lease before shared-state mutation."""
    run_id = "deliver-lease-before-mutate"
    state: dict = {
        "runId": run_id,
        "verdict": "running",
        "source_task_list": "docs/prds/276-demo/tasks.md",
        "updatedAt": utc_now(),
    }
    order: list[str] = []
    real_acquire = acquire_run_lease

    def _tracked_acquire(root: Path, rid: str, **kwargs):
        order.append("acquire")
        out = real_acquire(root, rid, **kwargs)
        order.append("acquired")
        return out

    def _tracked_save(root: Path, payload: dict) -> None:
        order.append("mutate")
        lock_path = run_lease_path_for(root, run_id)
        assert lock_path.is_file(), "lease must exist before state mutation"
        meta = json.loads(lock_path.read_text(encoding="utf-8"))
        assert meta["runId"] == run_id
        assert meta["pid"] == os.getpid()
        (root / ".cursor").mkdir(parents=True, exist_ok=True)
        (root / ".cursor" / "sw-deliver-state.json").write_text(
            json.dumps(payload) + "\n", encoding="utf-8"
        )

    with (
        patch("wave_lock.acquire_run_lease", side_effect=_tracked_acquire),
        patch("wave_deliver_loop.save_deliver_state", side_effect=_tracked_save),
    ):
        save_state(repo, state)

    assert order.index("acquire") < order.index("mutate")
    assert state["runLease"]["runId"] == run_id
    assert isinstance(state["runLease"]["generation"], int)
    assert state["runLease"]["generation"] >= 1


def test_second_adopter_halt_typed_resume(repo: Path) -> None:
    """R10 — second concurrent adopter halts with typed code + resumeCommand."""
    run_id = "deliver-second-adopter"
    first = acquire_run_lease(repo, run_id, source_task_list="docs/prds/276/tasks.md")
    assert first["verdict"] == "pass"

    lock_path = run_lease_path_for(repo, run_id)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 424242
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    with patch("wave_lock.ship_lease_pid_alive", return_value=True), patch(
        "wave_lock.run_lease_owner_live", return_value=True
    ):
        second = acquire_run_lease(
            repo, run_id, source_task_list="docs/prds/276/tasks.md"
        )

    assert second["verdict"] == "fail"
    assert second["error"] == "run-lease-held"
    assert second["halt"] == "run-lease-held"
    assert "resumeCommand" in second
    assert "deliver-loop" in second["resumeCommand"]
    assert "docs/prds/276/tasks.md" in second["resumeCommand"]


def test_two_adopters_only_one_drives(repo: Path) -> None:
    """R12 — two adopters on one runId: only one drives (regression)."""
    run_id = "deliver-single-driver"
    first = acquire_run_lease(repo, run_id)
    assert first["verdict"] == "pass"
    gen = first["generation"]

    lock_path = run_lease_path_for(repo, run_id)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 111111
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    with patch("wave_lock.ship_lease_pid_alive", return_value=True), patch(
        "wave_lock.run_lease_owner_live", return_value=True
    ):
        contested = acquire_run_lease(repo, run_id)
        assert contested["verdict"] == "fail"
        assert contested["error"] == "run-lease-held"

        state = {
            "runId": run_id,
            "verdict": "running",
            "source_task_list": "docs/prds/276/tasks.md",
        }
        with pytest.raises(SystemExit) as exc:
            ensure_exclusive_run_lease(repo, state, before_mutation=True)
        assert exc.value.code == 20

    held = json.loads(lock_path.read_text(encoding="utf-8"))
    assert held["pid"] == os.getpid() + 111111
    assert held["generation"] == gen
