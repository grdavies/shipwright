#!/usr/bin/env python3
"""Target-lock and doc-to-feature handoff-lock guards for spec-seed mutations (PRD 081 R19, PRD 085 R14)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_lock import (
    append_doc_to_feature_handoff_lock_journal,
    doc_to_feature_handoff_lock_key_digest,
    doc_to_feature_handoff_lock_path_for,
    lock_host,
    ship_lease_is_stale,
    ship_lease_owner_live,
    ship_lease_pid_alive,
    target_lock_key_digest,
    target_lock_path_for,
)
from wave_state import read_lock_meta, read_run_local_lease, utc_now


def is_doc_loop_run_id(run_id: str) -> bool:
    return run_id.startswith("doc-loop:")


def assert_target_lock_for_seed(root: Path, target_branch: str, run_id: str) -> dict[str, Any]:
    """Refuse spec-seed unless this run holds the target lock with a matching lease."""
    if not run_id:
        raise ValueError("run id required for spec-seed lock guard")
    lock_path = target_lock_path_for(root, target_branch)
    if not lock_path.is_file():
        raise PermissionError("spec-seed refused: target lock not held")
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        raise PermissionError("spec-seed refused: target lock held by another run")
    expected_digest = target_lock_key_digest(root, target_branch)
    recorded_digest = meta.get("lockKeyDigest")
    if recorded_digest != expected_digest:
        raise PermissionError("spec-seed refused: target lock digest mismatch")
    lease = read_run_local_lease(root, run_id)
    if not lease:
        raise PermissionError("spec-seed refused: run-local lease missing")
    if lease.get("targetBranch") != target_branch:
        raise PermissionError("spec-seed refused: lease target branch mismatch")
    if lease.get("lockKeyDigest") != expected_digest:
        raise PermissionError("spec-seed refused: lease lock digest mismatch")
    return {
        "lockPath": str(lock_path),
        "lockKeyDigest": expected_digest,
        "runId": run_id,
        "targetBranch": target_branch,
        "kind": "target-lock",
    }


def _owner_label(host: str, pid: int) -> str:
    return f"{host}:{pid}"


def _handoff_lock_meta(
    *,
    target_branch: str,
    run_id: str,
    host: str | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    now = utc_now()
    host_val = host or lock_host()
    pid_val = pid if pid is not None else os.getpid()
    return {
        "kind": "doc-to-feature-handoff-lock",
        "targetBranch": target_branch,
        "runId": run_id,
        "owner": _owner_label(host_val, pid_val),
        "host": host_val,
        "pid": pid_val,
        "acquiredAt": now,
        "heartbeatAt": now,
        "lockKeyDigest": "",
    }


def _handoff_lock_owner_live(meta: dict[str, Any]) -> bool:
    return ship_lease_owner_live(meta)


def _assert_no_target_lock_conflict(root: Path, target_branch: str, run_id: str) -> None:
    """Fail closed when a delivery target lock is held by a different run (R14)."""
    lock_path = target_lock_path_for(root, target_branch)
    if not lock_path.is_file():
        return
    meta = read_lock_meta(lock_path)
    holder_run = meta.get("runId")
    if holder_run == run_id:
        return
    if _handoff_lock_owner_live(meta) or (
        meta.get("host") == lock_host() and ship_lease_pid_alive(meta) and not ship_lease_is_stale(meta)
    ):
        raise PermissionError("doc-to-feature handoff refused: target-lock-conflict")


def reclaim_stale_doc_to_feature_handoff_lock(
    lock_path: Path,
    *,
    root: Path,
    reclaiming_run_id: str,
    takeover_reason: str,
    cross_host_ack: bool = False,
) -> bool:
    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return True
    holder_host = meta.get("host")
    if holder_host and holder_host != lock_host():
        if not cross_host_ack:
            return False
        if not ship_lease_is_stale(meta):
            return False
    else:
        if _handoff_lock_owner_live(meta):
            return False
        if not ship_lease_is_stale(meta):
            return False
        if ship_lease_pid_alive(meta):
            return False
    journal_entry = {
        "reclaimedOwner": meta.get("owner"),
        "reclaimedHost": meta.get("host"),
        "reclaimedPid": meta.get("pid"),
        "reclaimedAcquiredAt": meta.get("acquiredAt"),
        "reclaimedHeartbeatAt": meta.get("heartbeatAt"),
        "reclaimedRunId": meta.get("runId"),
        "takeoverReason": takeover_reason,
        "reclaimingRunId": reclaiming_run_id,
    }
    append_doc_to_feature_handoff_lock_journal(root, journal_entry)
    lock_path.unlink(missing_ok=True)
    return True


def acquire_doc_to_feature_handoff_lock(
    root: Path,
    target_branch: str,
    run_id: str,
    *,
    cross_host_ack: bool = False,
) -> dict[str, Any]:
    """Acquire doc-to-feature handoff lock scoped to doc-loop:<runId> (R14)."""
    if not is_doc_loop_run_id(run_id):
        raise ValueError("doc-to-feature handoff lock requires doc-loop:<runId> run id")
    try:
        _assert_no_target_lock_conflict(root, target_branch, run_id)
    except PermissionError as exc:
        if "target-lock-conflict" in str(exc):
            return {
                "verdict": "fail",
                "error": "target-lock-conflict",
                "targetBranch": target_branch,
                "runId": run_id,
            }
        raise
    lock_path = doc_to_feature_handoff_lock_path_for(root, target_branch, run_id)
    digest = doc_to_feature_handoff_lock_key_digest(root, target_branch, run_id)
    if lock_path.is_file():
        existing = read_lock_meta(lock_path)
        if (
            existing.get("pid") == os.getpid()
            and existing.get("host") == lock_host()
            and _handoff_lock_owner_live(existing)
            and existing.get("runId") == run_id
        ):
            return {
                "verdict": "pass",
                "action": "doc-to-feature-handoff-lock-acquire",
                "reentrant": True,
                "targetBranch": target_branch,
                "runId": run_id,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
            }
    meta = _handoff_lock_meta(target_branch=target_branch, run_id=run_id)
    meta["lockKeyDigest"] = digest
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    def try_acquire() -> bool:
        try:
            fd = os.open(lock_path, flags, 0o600)
        except FileExistsError:
            return False
        os.write(fd, (json.dumps(meta) + "\n").encode("utf-8"))
        os.close(fd)
        return True

    if not try_acquire():
        existing = read_lock_meta(lock_path)
        reason = "cross-host-ack" if cross_host_ack else "stale-heartbeat-dead-pid"
        if (
            reclaim_stale_doc_to_feature_handoff_lock(
                lock_path,
                root=root,
                reclaiming_run_id=run_id,
                takeover_reason=reason,
                cross_host_ack=cross_host_ack,
            )
            and try_acquire()
        ):
            return {
                "verdict": "pass",
                "action": "doc-to-feature-handoff-lock-acquire",
                "reclaimed": True,
                "targetBranch": target_branch,
                "runId": run_id,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
                "previousHolder": existing,
            }
        return {
            "verdict": "fail",
            "error": "doc-to-feature-handoff-lock-held",
            "holder": existing,
            "lockPath": str(lock_path),
        }
    return {
        "verdict": "pass",
        "action": "doc-to-feature-handoff-lock-acquire",
        "targetBranch": target_branch,
        "runId": run_id,
        "lockPath": str(lock_path),
        "lockKeyDigest": digest,
    }


def release_doc_to_feature_handoff_lock(root: Path, target_branch: str, run_id: str) -> dict[str, Any]:
    lock_path = doc_to_feature_handoff_lock_path_for(root, target_branch, run_id)
    if not lock_path.is_file():
        return {
            "verdict": "pass",
            "action": "doc-to-feature-handoff-lock-release",
            "note": "no lock file",
        }
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {
            "verdict": "fail",
            "error": "doc-to-feature-handoff-lock-other-run",
            "holder": meta,
        }
    if meta.get("pid") != os.getpid() or meta.get("host") != lock_host():
        return {
            "verdict": "fail",
            "error": "doc-to-feature-handoff-lock-other-pid",
            "holder": meta,
        }
    lock_path.unlink(missing_ok=True)
    return {
        "verdict": "pass",
        "action": "doc-to-feature-handoff-lock-release",
        "targetBranch": target_branch,
        "runId": run_id,
    }


def assert_handoff_lock_for_seed(root: Path, target_branch: str, run_id: str) -> dict[str, Any]:
    """Refuse doc-loop spec-seed unless this run holds the doc-to-feature handoff lock."""
    if not is_doc_loop_run_id(run_id):
        raise ValueError("handoff lock guard requires doc-loop:<runId>")
    lock_path = doc_to_feature_handoff_lock_path_for(root, target_branch, run_id)
    if not lock_path.is_file():
        raise PermissionError("spec-seed refused: doc-to-feature handoff lock not held")
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        raise PermissionError("spec-seed refused: doc-to-feature handoff lock held by another run")
    expected_digest = doc_to_feature_handoff_lock_key_digest(root, target_branch, run_id)
    recorded_digest = meta.get("lockKeyDigest")
    if recorded_digest != expected_digest:
        raise PermissionError("spec-seed refused: doc-to-feature handoff lock digest mismatch")
    if meta.get("kind") != "doc-to-feature-handoff-lock":
        raise PermissionError("spec-seed refused: lock kind mismatch")
    return {
        "lockPath": str(lock_path),
        "lockKeyDigest": expected_digest,
        "runId": run_id,
        "targetBranch": target_branch,
        "kind": "doc-to-feature-handoff-lock",
    }
