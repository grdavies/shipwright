"""PRD 348 R7–R10 — finalize-completion stall recovery (gap #950)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from wave_finalize_completion import (
    DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS,
    IncompleteReceiptStallError,
    check_incomplete_transition_receipt,
    clear_dead_living_docs_lock,
    dual_drive_heartbeat_blocks_finalize,
    dual_drive_heartbeat_is_stale,
    prepare_finalize_completion_stall_recovery,
    reclaim_dead_pid_run_lease,
)
from wave_living_doc_lock import lock_path as living_docs_lock_path
from wave_lock import (
    acquire_run_lease,
    run_lease_owner_live,
    run_lease_path_for,
    ship_lease_pid_alive,
)
from wave_state import lock_owner_live, read_lock_meta, utc_now
from wave_transition_receipt import begin_transition, find_incomplete_receipt


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ("." + "cursor")).mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture(autouse=True)
def anchor_repo(repo: Path):
    with patch("wave_lock._canonical_repo_root_for_locks", return_value=repo):
        yield


def _fresh_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _past_ts(seconds: int) -> str:
    past = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    return past.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_reclaim_dead_pid_run_lease_with_fresh_heartbeat(repo: Path) -> None:
    """R7 — dead-PID run lease is reclaimed even when heartbeat is still fresh."""
    run_id = "deliver-dead-pid-fresh-hb"
    first = acquire_run_lease(repo, run_id)
    assert first.get("verdict") == "pass"

    lock_path = run_lease_path_for(repo, run_id)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 700_001
    meta["heartbeatAt"] = _fresh_ts()
    meta["acquiredAt"] = meta["heartbeatAt"]
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    # Baseline: stale-window owner_live still true because heartbeat is fresh.
    assert run_lease_owner_live(meta) is True
    assert ship_lease_pid_alive(meta) is False

    result = reclaim_dead_pid_run_lease(repo, run_id)
    assert result["reclaimed"] is True
    assert result["reason"] == "dead-pid"
    assert not lock_path.is_file()
    assert "warning" in result


def test_reclaim_skips_live_pid_run_lease(repo: Path) -> None:
    """R7 — live PID leases are not reclaimed."""
    run_id = "deliver-live-pid"
    first = acquire_run_lease(repo, run_id)
    assert first.get("verdict") == "pass"
    lock_path = run_lease_path_for(repo, run_id)
    assert lock_path.is_file()

    result = reclaim_dead_pid_run_lease(repo, run_id)
    assert result["reclaimed"] is False
    assert result["reason"] == "pid-alive"
    assert lock_path.is_file()


def test_clear_dead_living_docs_lock_with_fresh_heartbeat(repo: Path) -> None:
    """R8 — living-docs lock with dead PID is cleared despite fresh heartbeat."""
    path = living_docs_lock_path(repo)
    path.write_text(
        json.dumps(
            {
                "holder": "dead-writer",
                "pid": os.getpid() + 800_001,
                "host": "test-host",
                "acquiredAt": _fresh_ts(),
                "heartbeatAt": _fresh_ts(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    meta = read_lock_meta(path)
    assert lock_owner_live(meta) is True

    result = clear_dead_living_docs_lock(repo)
    assert result["cleared"] is True
    assert result["reason"] == "dead-pid"
    assert not path.is_file()
    assert "diagnostic" in result


def test_clear_living_docs_lock_skips_live_pid(repo: Path) -> None:
    """R8 — living-docs lock held by a live PID is left alone."""
    path = living_docs_lock_path(repo)
    path.write_text(
        json.dumps(
            {
                "holder": "live-writer",
                "pid": os.getpid(),
                "host": "test-host",
                "acquiredAt": _fresh_ts(),
                "heartbeatAt": _fresh_ts(),
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = clear_dead_living_docs_lock(repo)
    assert result["cleared"] is False
    assert result["reason"] == "pid-alive"
    assert path.is_file()


def test_incomplete_receipt_past_deadline_fail_closed(repo: Path) -> None:
    """R9 — incomplete receipt past deadline fails closed with resumeCommand."""
    run_id = "deliver-receipt-overdue"
    begin_transition(
        repo,
        run_id,
        "finalize-seal",
        input_revisions={"state": {"label": "state"}},
    )
    receipt = find_incomplete_receipt(repo, run_id)
    assert receipt is not None
    pending = Path(receipt["path"])
    body = json.loads(pending.read_text(encoding="utf-8"))
    body["startedAt"] = _past_ts(900)
    body["timestamp"] = body["startedAt"]
    pending.write_text(json.dumps(body), encoding="utf-8")

    with pytest.raises(IncompleteReceiptStallError) as excinfo:
        check_incomplete_transition_receipt(repo, run_id, deadline_seconds=600)
    err = excinfo.value
    assert err.resume_command
    assert "deliver-loop" in err.resume_command or "finalize" in err.resume_command
    assert err.age_seconds is not None and err.age_seconds > 600

    soft = check_incomplete_transition_receipt(
        repo, run_id, deadline_seconds=600, raise_on_overdue=False
    )
    assert soft["blocked"] is True
    assert soft["resumeCommand"]
    assert soft["reason"] == "incomplete-receipt-past-deadline"


def test_incomplete_receipt_within_deadline_does_not_block(repo: Path) -> None:
    """R9 — incomplete receipt inside the deadline does not fail closed."""
    run_id = "deliver-receipt-fresh"
    begin_transition(
        repo,
        run_id,
        "finalize-seal",
        input_revisions={"state": {"label": "state"}},
    )
    result = check_incomplete_transition_receipt(
        repo, run_id, deadline_seconds=600, raise_on_overdue=True
    )
    assert result["blocked"] is False
    assert result["reason"] == "incomplete-within-deadline"
    assert result["resumeCommand"]


def test_dual_drive_heartbeat_wall_clock_timeout_stale() -> None:
    """R10 — heartbeat older than wall-clock timeout is stale and does not block."""
    state = {
        "verdict": "running",
        "phases": {"1": {"slug": "a"}},
        "driverHeartbeatAt": _past_ts(DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS + 30),
    }
    assert dual_drive_heartbeat_is_stale(state) is True
    assert dual_drive_heartbeat_blocks_finalize(state) is False


def test_dual_drive_heartbeat_within_timeout_blocks() -> None:
    """R10 — heartbeat within wall-clock timeout still blocks finalize-completion."""
    state = {
        "verdict": "running",
        "phases": {"1": {"slug": "a"}},
        "driverHeartbeatAt": _fresh_ts(),
    }
    assert dual_drive_heartbeat_is_stale(state) is False
    assert dual_drive_heartbeat_blocks_finalize(state) is True


def test_prepare_finalize_completion_stall_recovery_bundle(repo: Path) -> None:
    """R7–R10 — prepare runs reclaim/clearance and reports dual-drive status."""
    run_id = "deliver-prepare-bundle"
    acquire_run_lease(repo, run_id)
    lock_path = run_lease_path_for(repo, run_id)
    meta = json.loads(lock_path.read_text(encoding="utf-8"))
    meta["pid"] = os.getpid() + 900_001
    meta["heartbeatAt"] = _fresh_ts()
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")

    living = living_docs_lock_path(repo)
    living.write_text(
        json.dumps(
            {
                "holder": "bundle-writer",
                "pid": os.getpid() + 900_002,
                "host": "test-host",
                "acquiredAt": _fresh_ts(),
                "heartbeatAt": _fresh_ts(),
            }
        )
        + "\n",
        encoding="utf-8",
    )

    state = {
        "runId": run_id,
        "verdict": "running",
        "phases": {"1": {"slug": "a"}},
        "driverHeartbeatAt": _past_ts(DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS + 5),
    }
    out = prepare_finalize_completion_stall_recovery(repo, state, run_id=run_id)
    assert out["mutated"] is True
    assert out["runLease"]["reclaimed"] is True
    assert out["livingDocsLock"]["cleared"] is True
    assert out["dualDriveHeartbeat"]["stale"] is True
    assert out["dualDriveHeartbeat"]["blocksFinalize"] is False
    assert out["transitionReceipt"]["blocked"] is False
    assert not lock_path.is_file()
    assert not living.is_file()
    assert isinstance(utc_now(), str)
