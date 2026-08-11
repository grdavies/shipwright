#!/usr/bin/env python3
"""Deliver target-branch exclusion lock (PRD 081 R19).

Exclusive lock keyed by repository identity and target branch digest. Heartbeat-based
liveness reuses the ship-lease staleness predicate from wave_lock.
"""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wave_lock import (
    append_doc_run_lock_journal,
    append_doc_to_feature_handoff_lock_journal,
    append_target_lock_journal,
    doc_run_lock_key_digest,
    doc_run_lock_path_for,
    doc_to_feature_handoff_lock_key_digest,
    doc_to_feature_handoff_lock_path_for,
    lock_host,
    ship_lease_is_stale,
    ship_lease_owner_live,
    ship_lease_pid_alive,
    target_lock_key_digest,
    target_lock_path_for,
)
from wave_remote_lease import acquire_remote_lease, release_remote_lease
from wave_state import emit, fail, parse_kv, read_lock_meta, utc_now


def _owner_label(host: str, pid: int) -> str:
    return f"{host}:{pid}"


def _lock_meta(
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
        "kind": "target-lock",
        "targetBranch": target_branch,
        "runId": run_id,
        "owner": _owner_label(host_val, pid_val),
        "host": host_val,
        "pid": pid_val,
        "acquiredAt": now,
        "heartbeatAt": now,
        "lockKeyDigest": "",  # filled by caller
    }


def _doc_lock_meta(
    *,
    topic: str,
    run_id: str,
    host: str | None = None,
    pid: int | None = None,
) -> dict[str, Any]:
    now = utc_now()
    host_val = host or lock_host()
    pid_val = pid if pid is not None else os.getpid()
    return {
        "kind": "doc-run-lock",
        "topic": topic,
        "runId": run_id,
        "owner": _owner_label(host_val, pid_val),
        "host": host_val,
        "pid": pid_val,
        "acquiredAt": now,
        "heartbeatAt": now,
        "lockKeyDigest": "",
    }


def reclaim_stale_doc_run_lock(
    lock_path: Path,
    *,
    root: Path,
    reclaiming_run_id: str,
    takeover_reason: str,
    cross_host_ack: bool = False,
) -> bool:
    """Reclaim stale doc-run lock; journal every successful takeover (R11)."""
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
        if target_lock_owner_live(meta):
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
    append_doc_run_lock_journal(root, journal_entry)
    lock_path.unlink(missing_ok=True)
    return True


def acquire_doc_run_lock(
    root: Path,
    topic: str,
    run_id: str,
    *,
    cross_host_ack: bool = False,
) -> dict[str, Any]:
    """Acquire doc-run lock keyed by repository identity plus docs topic (R11)."""
    lock_path = doc_run_lock_path_for(root, topic)
    digest = doc_run_lock_key_digest(root, topic)
    if lock_path.is_file():
        existing = read_lock_meta(lock_path)
        if (
            existing.get("pid") == os.getpid()
            and existing.get("host") == lock_host()
            and target_lock_owner_live(existing)
            and existing.get("runId") == run_id
        ):
            return {
                "verdict": "pass",
                "action": "doc-run-lock-acquire",
                "reentrant": True,
                "topic": topic,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
            }
    meta = _doc_lock_meta(topic=topic, run_id=run_id)
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
            reclaim_stale_doc_run_lock(
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
                "action": "doc-run-lock-acquire",
                "reclaimed": True,
                "topic": topic,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
                "previousHolder": existing,
            }
        return {
            "verdict": "fail",
            "error": "doc-run-lock-held",
            "holder": existing,
            "lockPath": str(lock_path),
        }
    return {
        "verdict": "pass",
        "action": "doc-run-lock-acquire",
        "topic": topic,
        "lockPath": str(lock_path),
        "lockKeyDigest": digest,
    }


def heartbeat_doc_run_lock(root: Path, topic: str, run_id: str) -> dict[str, Any]:
    lock_path = doc_run_lock_path_for(root, topic)
    if not lock_path.is_file():
        return {"verdict": "fail", "error": "doc-run-lock-missing", "lockPath": str(lock_path)}
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {"verdict": "fail", "error": "doc-run-lock-run-mismatch", "holder": meta}
    holder_pid = meta.get("pid")
    if isinstance(holder_pid, int) and holder_pid != os.getpid():
        return {"verdict": "fail", "error": "doc-run-lock-other-pid", "holder": meta}
    if meta.get("host") != lock_host():
        return {"verdict": "fail", "error": "doc-run-lock-other-host", "holder": meta}
    now = utc_now()
    meta["heartbeatAt"] = now
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    os.chmod(lock_path, 0o600)
    return {
        "verdict": "pass",
        "action": "doc-run-lock-heartbeat",
        "heartbeatAt": now,
        "topic": topic,
    }


def validate_doc_run_lock(root: Path, topic: str, run_id: str) -> dict[str, Any]:
    """Validate an already-held doc-run lease without a full re-acquire (PRD 089 R3).

    Distinct from ``acquire_doc_run_lock``: never creates or steals a lock. On success,
    heartbeats the existing lease. Fails closed when missing, run-mismatched, or held by
    another live PID/host.
    """
    lock_path = doc_run_lock_path_for(root, topic)
    digest = doc_run_lock_key_digest(root, topic)
    if not lock_path.is_file():
        return {
            "verdict": "fail",
            "error": "doc-run-lock-missing",
            "lockPath": str(lock_path),
            "lockKeyDigest": digest,
        }
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {
            "verdict": "fail",
            "error": "doc-run-lock-run-mismatch",
            "holder": meta,
            "lockPath": str(lock_path),
        }
    if meta.get("host") != lock_host():
        return {
            "verdict": "fail",
            "error": "doc-run-lock-other-host",
            "holder": meta,
            "lockPath": str(lock_path),
        }
    holder_pid = meta.get("pid")
    if isinstance(holder_pid, int) and holder_pid != os.getpid():
        if ship_lease_pid_alive(meta) and target_lock_owner_live(meta):
            return {
                "verdict": "fail",
                "error": "doc-run-lock-other-pid",
                "holder": meta,
                "lockPath": str(lock_path),
            }
        return {
            "verdict": "fail",
            "error": "doc-run-lock-stale-self",
            "holder": meta,
            "lockPath": str(lock_path),
            "note": "same runId but dead/other pid — use validate_or_acquire_doc_run_lock",
        }
    hb = heartbeat_doc_run_lock(root, topic, run_id)
    if hb.get("verdict") != "pass":
        return hb
    return {
        "verdict": "pass",
        "action": "doc-run-lock-validate",
        "topic": topic,
        "lockPath": str(lock_path),
        "lockKeyDigest": digest,
        "heartbeatAt": hb.get("heartbeatAt"),
    }


def validate_or_acquire_doc_run_lock(
    root: Path,
    topic: str,
    run_id: str,
    *,
    cross_host_ack: bool = False,
) -> dict[str, Any]:
    """Resume helper: validate held lease or acquire; fail closed on other live holder (R3)."""
    validated = validate_doc_run_lock(root, topic, run_id)
    if validated.get("verdict") == "pass":
        return validated
    err = str(validated.get("error") or "")
    if err in ("doc-run-lock-missing", "doc-run-lock-stale-self"):
        acquired = acquire_doc_run_lock(
            root, topic, run_id, cross_host_ack=cross_host_ack
        )
        if acquired.get("verdict") == "pass":
            acquired = {**acquired, "via": "validate-or-acquire"}
        return acquired
    return validated


def release_doc_run_lock(root: Path, topic: str, run_id: str) -> dict[str, Any]:
    lock_path = doc_run_lock_path_for(root, topic)
    if not lock_path.is_file():
        return {"verdict": "pass", "action": "doc-run-lock-release", "note": "no lock file"}
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {"verdict": "fail", "error": "doc-run-lock-run-mismatch", "holder": meta}
    holder_pid = meta.get("pid")
    if isinstance(holder_pid, int) and holder_pid != os.getpid():
        return {"verdict": "fail", "error": "doc-run-lock-other-pid", "holder": meta}
    lock_path.unlink(missing_ok=True)
    return {"verdict": "pass", "action": "doc-run-lock-release", "topic": topic}


def release_doc_run_lock_on_terminal_complete(
    root: Path,
    topic: str,
    run_id: str,
) -> dict[str, Any]:
    """Release doc-run lock when a doc-loop run reaches terminal ``complete`` (R9)."""
    lock_path = doc_run_lock_path_for(root, topic)
    had_lock = lock_path.is_file()
    out = release_doc_run_lock(root, topic, run_id)
    if out.get("verdict") == "pass" and had_lock:
        append_doc_run_lock_journal(
            root,
            {
                "action": "doc-run-lock-terminal-release",
                "topic": topic,
                "runId": run_id,
                "timestamp": utc_now(),
                "lockPath": str(lock_path),
            },
        )
        out["action"] = "doc-run-lock-terminal-release"
    out["terminalComplete"] = True
    return out


def cmd_doc_acquire(root: Path, args: list[str]) -> None:
    topic = parse_kv(args, "--topic")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DOC_RUN_ID", "")
    if not topic:
        fail("--topic required")
    if not run_id:
        fail("--run-id or SW_DOC_RUN_ID required")
    cross_host_ack = "--ack-cross-host" in args
    out = acquire_doc_run_lock(root, topic, run_id, cross_host_ack=cross_host_ack)
    if out.get("verdict") != "pass":
        fail(out.get("error", "doc-run lock held"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_doc_release(root: Path, args: list[str]) -> None:
    topic = parse_kv(args, "--topic")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DOC_RUN_ID", "")
    if not topic or not run_id:
        fail("--topic and --run-id required")
    out = release_doc_run_lock(root, topic, run_id)
    if out.get("verdict") != "pass":
        fail(out.get("error", "doc-run lock release failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_doc_heartbeat(root: Path, args: list[str]) -> None:
    topic = parse_kv(args, "--topic")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DOC_RUN_ID", "")
    if not topic or not run_id:
        fail("--topic and --run-id required")
    out = heartbeat_doc_run_lock(root, topic, run_id)
    if out.get("verdict") != "pass":
        fail(out.get("error", "doc-run lock heartbeat failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_doc_status(root: Path, args: list[str]) -> None:
    topic = parse_kv(args, "--topic")
    if not topic:
        fail("--topic required")
    lock_path = doc_run_lock_path_for(root, topic)
    if not lock_path.is_file():
        emit(
            {
                "verdict": "pass",
                "action": "doc-run-lock-status",
                "held": False,
                "lockPath": str(lock_path),
                "lockKeyDigest": doc_run_lock_key_digest(root, topic),
            }
        )
    meta = read_lock_meta(lock_path)
    emit(
        {
            "verdict": "pass",
            "action": "doc-run-lock-status",
            "held": True,
            "live": target_lock_owner_live(meta),
            "meta": meta,
            "lockPath": str(lock_path),
            "lockKeyDigest": doc_run_lock_key_digest(root, topic),
        }
    )


def target_lock_owner_live(meta: dict[str, Any]) -> bool:
    """True when heartbeat is fresh or same-host PID is still alive."""
    return ship_lease_owner_live(meta)


def reclaim_stale_target_lock(
    lock_path: Path,
    *,
    root: Path,
    reclaiming_run_id: str,
    takeover_reason: str,
    cross_host_ack: bool = False,
) -> bool:
    """Reclaim stale target lock; journal every successful takeover (R19)."""
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
        if target_lock_owner_live(meta):
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
    append_target_lock_journal(root, journal_entry)
    lock_path.unlink(missing_ok=True)
    return True


def acquire_target_lock(
    root: Path,
    target_branch: str,
    run_id: str,
    *,
    cross_host_ack: bool = False,
) -> dict[str, Any]:
    remote_lease = acquire_remote_lease(root, target_branch, run_id)
    if remote_lease.get("verdict") != "pass":
        return remote_lease
    lock_path = target_lock_path_for(root, target_branch)
    digest = target_lock_key_digest(root, target_branch)
    if lock_path.is_file():
        existing = read_lock_meta(lock_path)
        if (
            existing.get("pid") == os.getpid()
            and existing.get("host") == lock_host()
            and target_lock_owner_live(existing)
            and existing.get("runId") == run_id
        ):
            out = {
                "verdict": "pass",
                "action": "target-lock-acquire",
                "reentrant": True,
                "targetBranch": target_branch,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
            }
            if remote_lease.get("mode"):
                out["remoteLease"] = remote_lease
            return out
    meta = _lock_meta(target_branch=target_branch, run_id=run_id)
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
            reclaim_stale_target_lock(
                lock_path,
                root=root,
                reclaiming_run_id=run_id,
                takeover_reason=reason,
                cross_host_ack=cross_host_ack,
            )
            and try_acquire()
        ):
            out = {
                "verdict": "pass",
                "action": "target-lock-acquire",
                "reclaimed": True,
                "targetBranch": target_branch,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
                "previousHolder": existing,
            }
            if remote_lease.get("mode"):
                out["remoteLease"] = remote_lease
            return out
        release_remote_lease(root, target_branch, run_id)
        out = {
            "verdict": "fail",
            "error": "target-lock-held",
            "holder": existing,
            "lockPath": str(lock_path),
        }
        if remote_lease.get("warning"):
            out["remoteLeaseWarning"] = remote_lease.get("warning")
        return out
    out = {
        "verdict": "pass",
        "action": "target-lock-acquire",
        "targetBranch": target_branch,
        "lockPath": str(lock_path),
        "lockKeyDigest": digest,
    }
    if remote_lease.get("mode"):
        out["remoteLease"] = remote_lease
    return out


def heartbeat_target_lock(root: Path, target_branch: str, run_id: str) -> dict[str, Any]:
    lock_path = target_lock_path_for(root, target_branch)
    if not lock_path.is_file():
        return {"verdict": "fail", "error": "target-lock-missing", "lockPath": str(lock_path)}
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {"verdict": "fail", "error": "target-lock-run-mismatch", "holder": meta}
    holder_pid = meta.get("pid")
    if isinstance(holder_pid, int) and holder_pid != os.getpid():
        return {"verdict": "fail", "error": "target-lock-other-pid", "holder": meta}
    if meta.get("host") != lock_host():
        return {"verdict": "fail", "error": "target-lock-other-host", "holder": meta}
    now = utc_now()
    meta["heartbeatAt"] = now
    lock_path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    os.chmod(lock_path, 0o600)
    return {
        "verdict": "pass",
        "action": "target-lock-heartbeat",
        "heartbeatAt": now,
        "targetBranch": target_branch,
    }


def release_target_lock(
    root: Path,
    target_branch: str,
    run_id: str,
    *,
    finalize: bool = False,
) -> dict[str, Any]:
    lock_path = target_lock_path_for(root, target_branch)
    if not lock_path.is_file():
        return {"verdict": "pass", "action": "target-lock-release", "note": "no lock file"}
    meta = read_lock_meta(lock_path)
    if meta.get("runId") != run_id:
        return {"verdict": "fail", "error": "target-lock-run-mismatch", "holder": meta}
    holder_pid = meta.get("pid")
    if (
        not finalize
        and isinstance(holder_pid, int)
        and holder_pid != os.getpid()
    ):
        return {"verdict": "fail", "error": "target-lock-other-pid", "holder": meta}
    lock_path.unlink(missing_ok=True)
    remote_release = release_remote_lease(root, target_branch, run_id)
    out: dict[str, Any] = {
        "verdict": "pass",
        "action": "target-lock-release",
        "targetBranch": target_branch,
    }
    if remote_release.get("mode"):
        out["remoteLease"] = remote_release
    return out


def is_doc_loop_run_id(run_id: str) -> bool:
    return run_id.startswith("doc-loop:")


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
    """Acquire doc-to-feature handoff lock scoped to doc-loop:<runId> (R14, R2)."""
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
    remote_lease = acquire_remote_lease(root, target_branch, run_id)
    if remote_lease.get("verdict") != "pass":
        return remote_lease
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
            out = {
                "verdict": "pass",
                "action": "doc-to-feature-handoff-lock-acquire",
                "reentrant": True,
                "targetBranch": target_branch,
                "runId": run_id,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
            }
            if remote_lease.get("mode"):
                out["remoteLease"] = remote_lease
            return out
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
            out = {
                "verdict": "pass",
                "action": "doc-to-feature-handoff-lock-acquire",
                "reclaimed": True,
                "targetBranch": target_branch,
                "runId": run_id,
                "lockPath": str(lock_path),
                "lockKeyDigest": digest,
                "previousHolder": existing,
            }
            if remote_lease.get("mode"):
                out["remoteLease"] = remote_lease
            return out
        release_remote_lease(root, target_branch, run_id)
        return {
            "verdict": "fail",
            "error": "doc-to-feature-handoff-lock-held",
            "holder": existing,
            "lockPath": str(lock_path),
        }
    out = {
        "verdict": "pass",
        "action": "doc-to-feature-handoff-lock-acquire",
        "targetBranch": target_branch,
        "runId": run_id,
        "lockPath": str(lock_path),
        "lockKeyDigest": digest,
    }
    if remote_lease.get("mode"):
        out["remoteLease"] = remote_lease
    return out


def release_doc_to_feature_handoff_lock(root: Path, target_branch: str, run_id: str) -> dict[str, Any]:
    lock_path = doc_to_feature_handoff_lock_path_for(root, target_branch, run_id)
    if not lock_path.is_file():
        remote_release = release_remote_lease(root, target_branch, run_id)
        out: dict[str, Any] = {
            "verdict": "pass",
            "action": "doc-to-feature-handoff-lock-release",
            "note": "no lock file",
        }
        if remote_release.get("mode"):
            out["remoteLease"] = remote_release
        return out
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
    remote_release = release_remote_lease(root, target_branch, run_id)
    out = {
        "verdict": "pass",
        "action": "doc-to-feature-handoff-lock-release",
        "targetBranch": target_branch,
        "runId": run_id,
    }
    if remote_release.get("mode"):
        out["remoteLease"] = remote_release
    return out


def cmd_acquire(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID", "")
    if not target:
        fail("--target required")
    if not run_id:
        fail("--run-id or SW_DELIVER_RUN_ID required")
    cross_host_ack = "--ack-cross-host" in args
    out = acquire_target_lock(root, target, run_id, cross_host_ack=cross_host_ack)
    if out.get("verdict") != "pass":
        fail(out.get("error", "target lock held"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_release(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID", "")
    if not target or not run_id:
        fail("--target and --run-id required")
    out = release_target_lock(root, target, run_id)
    if out.get("verdict") != "pass":
        fail(out.get("error", "target lock release failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_heartbeat(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    run_id = parse_kv(args, "--run-id") or os.environ.get("SW_DELIVER_RUN_ID", "")
    if not target or not run_id:
        fail("--target and --run-id required")
    out = heartbeat_target_lock(root, target, run_id)
    if out.get("verdict") != "pass":
        fail(out.get("error", "target lock heartbeat failed"), exit_code=20, holder=out.get("holder"))
    emit(out)


def cmd_status(root: Path, args: list[str]) -> None:
    target = parse_kv(args, "--target")
    if not target:
        fail("--target required")
    lock_path = target_lock_path_for(root, target)
    if not lock_path.is_file():
        emit(
            {
                "verdict": "pass",
                "action": "target-lock-status",
                "held": False,
                "lockPath": str(lock_path),
                "lockKeyDigest": target_lock_key_digest(root, target),
            }
        )
    meta = read_lock_meta(lock_path)
    emit(
        {
            "verdict": "pass",
            "action": "target-lock-status",
            "held": True,
            "live": target_lock_owner_live(meta),
            "meta": meta,
            "lockPath": str(lock_path),
            "lockKeyDigest": target_lock_key_digest(root, target),
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: wave_target_lock.py <root> "
            "<acquire|release|heartbeat|status|doc-acquire|doc-release|doc-heartbeat|doc-status> ..."
        )
    root = Path(sys.argv[1]).resolve()
    sub = sys.argv[2]
    rest = sys.argv[3:]
    if sub == "acquire":
        cmd_acquire(root, rest)
    elif sub == "release":
        cmd_release(root, rest)
    elif sub == "heartbeat":
        cmd_heartbeat(root, rest)
    elif sub == "status":
        cmd_status(root, rest)
    elif sub == "doc-acquire":
        cmd_doc_acquire(root, rest)
    elif sub == "doc-release":
        cmd_doc_release(root, rest)
    elif sub == "doc-heartbeat":
        cmd_doc_heartbeat(root, rest)
    elif sub == "doc-status":
        cmd_doc_status(root, rest)
    else:
        fail(f"unknown target-lock subcommand: {sub}")


if __name__ == "__main__":
    main()
