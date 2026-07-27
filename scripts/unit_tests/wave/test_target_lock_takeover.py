"""PRD 081 R19 — target-lock takeover and orphan-recovery fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_lock import lock_host, target_lock_journal_path, target_lock_path_for
from wave_target_lock import acquire_target_lock, reclaim_stale_target_lock


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


def test_stale_heartbeat_dead_pid_reclaimed_and_journaled(repo: Path) -> None:
    target = "feat/demo"
    lock_path = target_lock_path_for(repo, target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "kind": "target-lock",
        "targetBranch": target,
        "runId": "orphan-run",
        "owner": f"{lock_host()}:999999",
        "host": lock_host(),
        "pid": 999999,
        "acquiredAt": "2000-01-01T00:00:00Z",
        "heartbeatAt": "2000-01-01T00:00:00Z",
        "lockKeyDigest": "deadbeef",
    }
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    assert reclaim_stale_target_lock(
        lock_path,
        root=repo,
        reclaiming_run_id="run-new",
        takeover_reason="stale-heartbeat-dead-pid",
    )
    assert not lock_path.is_file()
    journal = target_lock_journal_path(repo)
    assert journal.is_file()
    lines = journal.read_text(encoding="utf-8").strip().splitlines()
    entry = json.loads(lines[-1])
    assert entry["reclaimedRunId"] == "orphan-run"
    assert entry["reclaimingRunId"] == "run-new"
    assert entry["takeoverReason"] == "stale-heartbeat-dead-pid"

    out = acquire_target_lock(repo, target, "run-new")
    assert out["verdict"] == "pass"


def test_live_heartbeat_refused(repo: Path) -> None:
    target = "feat/live"
    first = acquire_target_lock(repo, target, "run-live")
    assert first["verdict"] == "pass"
    lock_path = target_lock_path_for(repo, target)
    assert not reclaim_stale_target_lock(
        lock_path,
        root=repo,
        reclaiming_run_id="run-other",
        takeover_reason="stale-heartbeat-dead-pid",
    )
    second = acquire_target_lock(repo, target, "run-other")
    assert second["verdict"] == "fail"


def test_cross_host_without_ack_refused(repo: Path) -> None:
    target = "feat/cross"
    lock_path = target_lock_path_for(repo, target)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "kind": "target-lock",
        "targetBranch": target,
        "runId": "remote-run",
        "owner": "other-host:1",
        "host": "other-host",
        "pid": 1,
        "acquiredAt": "2000-01-01T00:00:00Z",
        "heartbeatAt": "2000-01-01T00:00:00Z",
        "lockKeyDigest": "abc",
    }
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    assert not reclaim_stale_target_lock(
        lock_path,
        root=repo,
        reclaiming_run_id="local-run",
        takeover_reason="cross-host-ack",
        cross_host_ack=False,
    )
    out = acquire_target_lock(repo, target, "local-run")
    assert out["verdict"] == "fail"

    out_ack = acquire_target_lock(repo, target, "local-run", cross_host_ack=True)
    assert out_ack["verdict"] == "pass"


def test_orphan_lock_recoverable_before_run_directory(repo: Path) -> None:
    """Crash between acquire and run creation leaves recoverable orphan lock."""
    target = "feat/orphan"
    run_id = "run-orphan"
    out = acquire_target_lock(repo, target, run_id)
    assert out["verdict"] == "pass"
    lock_path = target_lock_path_for(repo, target)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["heartbeatAt"] = "2000-01-01T00:00:00Z"
    meta["pid"] = 999999
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    run_dir = repo / ".cursor" / "sw-deliver-runs" / run_id
    assert not run_dir.exists()

    recovered = acquire_target_lock(repo, target, "run-successor")
    assert recovered["verdict"] == "pass"
    assert recovered.get("reclaimed") is True
