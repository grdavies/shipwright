"""PRD 081 R19 — target-lock primitive fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_lock import target_lock_path_for, target_locks_dir
from wave_target_lock import acquire_target_lock, heartbeat_target_lock, release_target_lock


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


def test_no_lock_status_not_held(repo: Path) -> None:
    lock_path = target_lock_path_for(repo, "feat/demo")
    assert not lock_path.is_file()


def test_single_acquire_and_metadata_round_trip(repo: Path) -> None:
    target = "feat/workflow-state-machine-hardening"
    run_id = "run-001"
    out = acquire_target_lock(repo, target, run_id)
    assert out["verdict"] == "pass"
    lock_path = target_lock_path_for(repo, target)
    assert lock_path.is_file()
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    assert meta["runId"] == run_id
    assert meta["targetBranch"] == target
    assert meta["owner"]
    assert meta["host"]
    assert isinstance(meta["pid"], int)
    assert meta["acquiredAt"]
    assert meta["heartbeatAt"]
    assert meta["lockKeyDigest"]

    hb = heartbeat_target_lock(repo, target, run_id)
    assert hb["verdict"] == "pass"
    refreshed = json.loads(lock_path.read_text(encoding="utf-8"))
    assert refreshed["heartbeatAt"] >= meta["heartbeatAt"]

    rel = release_target_lock(repo, target, run_id)
    assert rel["verdict"] == "pass"
    assert not lock_path.is_file()


def test_duplicate_acquire_refused_without_touching_holder(repo: Path) -> None:
    target = "feat/demo"
    first = acquire_target_lock(repo, target, "run-a")
    assert first["verdict"] == "pass"
    lock_path = target_lock_path_for(repo, target)
    before = lock_path.read_text(encoding="utf-8")

    second = acquire_target_lock(repo, target, "run-b")
    assert second["verdict"] == "fail"
    assert second["error"] == "target-lock-held"
    after = lock_path.read_text(encoding="utf-8")
    assert before == after


def test_symlinked_locks_directory_refused(repo: Path) -> None:
    cursor = repo / ".cursor"
    cursor.mkdir(parents=True, exist_ok=True)
    real_dir = repo / "real-target-locks"
    real_dir.mkdir()
    symlink_locks = cursor / "sw-target-locks"
    symlink_locks.symlink_to(real_dir)
    with pytest.raises(SystemExit):
        target_locks_dir(repo)
