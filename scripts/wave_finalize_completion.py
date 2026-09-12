#!/usr/bin/env python3
"""Finalize-completion stall recovery (PRD 348 R7–R10 / gap #950).

Before finalize-completion retries:
  - Auto-reclaim same-host run leases whose PID is dead even when the heartbeat is
    still within the stale window (R7).
  - Clear living-docs locks held by dead PIDs (R8).
  - Fail closed on incomplete transition receipts past a configurable deadline with a
    ``resumeCommand`` (R9).
  - Treat dual-drive driver heartbeats that exceed a wall-clock timeout as stale so
    they do not block finalize-completion (R10).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# R9 — incomplete transition receipt deadline (seconds).
INCOMPLETE_RECEIPT_DEADLINE_SECONDS = int(
    os.environ.get("SW_INCOMPLETE_RECEIPT_DEADLINE_SECONDS", "600")
)
# R10 — dual-drive heartbeat wall-clock timeout (seconds).
DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS = int(
    os.environ.get("SW_DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS", "120")
)


class IncompleteReceiptStallError(RuntimeError):
    """Fail-closed stall: incomplete transition receipt past deadline (R9)."""

    def __init__(
        self,
        message: str,
        *,
        resume_command: str,
        receipt: dict[str, Any] | None = None,
        age_seconds: float | None = None,
    ) -> None:
        super().__init__(message)
        self.resume_command = resume_command
        self.receipt = receipt or {}
        self.age_seconds = age_seconds


def _utc_now() -> str:
    from wave_state import utc_now

    return utc_now()


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _parse_ts(ts: str) -> datetime | None:
    if not isinstance(ts, str) or not ts.strip():
        return None
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_seconds(ts: str) -> float | None:
    """Wall-clock age of an ISO-8601 UTC timestamp ending in Z."""
    dt = _parse_ts(ts)
    if dt is None:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def resume_finalize_completion_command(run_id: str | None = None) -> str:
    """Operator resume command for fail-closed finalize-completion stalls (R9)."""
    if run_id:
        return (
            f"python3 scripts/wave.py deliver-loop --run-id {run_id} "
            "# then retry finalize-completion after sealing or clearing the pending receipt"
        )
    return (
        "python3 scripts/wave.py completion finalize-if-merged "
        "# after sealing or clearing the incomplete transition receipt"
    )


def reclaim_dead_pid_run_lease(
    root: Path,
    run_id: str,
    *,
    reclaiming_run_id: str | None = None,
) -> dict[str, Any]:
    """Reclaim a same-host run lease whose holder PID is dead (R7).

    Unlike ``reclaim_stale_run_lease``, this path does **not** require the heartbeat
    to be past ``RUN_LEASE_STALE_SECONDS`` — a fresh heartbeat with a dead PID is
    treated as reclaimable so finalize-completion does not stall for ~300s.
    """
    from wave_lock import (
        append_run_lease_journal,
        lock_host,
        run_lease_ownership_certain,
        run_lease_path_for,
    )
    from wave_state import read_lock_meta

    rid = (run_id or "").strip()
    if not rid:
        return {"reclaimed": False, "reason": "run-id-missing"}

    lock_path = run_lease_path_for(root, rid)
    if not lock_path.is_file():
        return {"reclaimed": False, "reason": "lease-absent", "lockPath": str(lock_path)}

    meta = read_lock_meta(lock_path)
    if not meta:
        lock_path.unlink(missing_ok=True)
        return {
            "reclaimed": True,
            "reason": "empty-lease-cleared",
            "lockPath": str(lock_path),
        }

    if not run_lease_ownership_certain(meta):
        return {
            "reclaimed": False,
            "reason": "ownership-uncertain",
            "lockPath": str(lock_path),
            "meta": meta,
        }

    holder_host = meta.get("host")
    if holder_host and holder_host != lock_host():
        return {
            "reclaimed": False,
            "reason": "cross-host",
            "lockPath": str(lock_path),
            "holderHost": holder_host,
        }

    pid = meta.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {
            "reclaimed": False,
            "reason": "pid-invalid",
            "lockPath": str(lock_path),
            "meta": meta,
        }

    if _pid_alive(pid):
        return {
            "reclaimed": False,
            "reason": "pid-alive",
            "lockPath": str(lock_path),
            "pid": pid,
        }

    prior_gen_raw = meta.get("generation")
    try:
        prior_gen = int(prior_gen_raw) if prior_gen_raw is not None else 0
    except (TypeError, ValueError):
        prior_gen = 0
    next_gen = max(prior_gen, 0) + 1
    reclaiming = (reclaiming_run_id or rid).strip()
    journal_entry = {
        "kind": "deliver-run-lease-reclaim",
        "takeoverReason": "dead-pid-finalize-completion",
        "reclaimedOwner": meta.get("owner"),
        "reclaimedHost": meta.get("host"),
        "reclaimedPid": pid,
        "reclaimedAcquiredAt": meta.get("acquiredAt"),
        "reclaimedHeartbeatAt": meta.get("heartbeatAt"),
        "reclaimedRunId": meta.get("runId"),
        "reclaimedGeneration": prior_gen,
        "nextGeneration": next_gen,
        "reclaimingRunId": reclaiming,
    }
    append_run_lease_journal(root, journal_entry)
    lock_path.unlink(missing_ok=True)
    warning = (
        f"finalize-completion: reclaimed dead-PID run lease runId={rid!r} "
        f"pid={pid} host={holder_host!r} generation={prior_gen}->{next_gen}"
    )
    logger.warning(warning)
    return {
        "reclaimed": True,
        "reason": "dead-pid",
        "lockPath": str(lock_path),
        "pid": pid,
        "previousGeneration": prior_gen,
        "nextGeneration": next_gen,
        "warning": warning,
    }


def clear_dead_living_docs_lock(root: Path) -> dict[str, Any]:
    """Clear a living-docs lock held by a dead PID on finalize-completion entry (R8).

    Heartbeat freshness alone does not keep a dead-PID lock; clearance is logged as a
    diagnostic.
    """
    from wave_living_doc_lock import lock_path
    from wave_state import read_lock_meta

    path = lock_path(root)
    if not path.is_file():
        return {"cleared": False, "reason": "lock-absent", "lockPath": str(path)}

    meta = read_lock_meta(path)
    if not meta:
        path.unlink(missing_ok=True)
        diagnostic = f"finalize-completion: cleared empty living-docs lock path={path}"
        logger.info(diagnostic)
        return {
            "cleared": True,
            "reason": "empty-lock",
            "lockPath": str(path),
            "diagnostic": diagnostic,
        }

    pid = meta.get("pid")
    if not isinstance(pid, int) or pid <= 0:
        return {
            "cleared": False,
            "reason": "pid-invalid",
            "lockPath": str(path),
            "meta": meta,
        }

    if _pid_alive(pid):
        return {
            "cleared": False,
            "reason": "pid-alive",
            "lockPath": str(path),
            "pid": pid,
        }

    path.unlink(missing_ok=True)
    diagnostic = (
        f"finalize-completion: cleared dead-PID living-docs lock "
        f"pid={pid} holder={meta.get('holder')!r} path={path}"
    )
    logger.info(diagnostic)
    return {
        "cleared": True,
        "reason": "dead-pid",
        "lockPath": str(path),
        "pid": pid,
        "holder": meta.get("holder"),
        "diagnostic": diagnostic,
    }


def incomplete_receipt_past_deadline(
    receipt: dict[str, Any],
    *,
    deadline_seconds: int | None = None,
    now: datetime | None = None,
) -> tuple[bool, float | None]:
    """Return (past_deadline, age_seconds) for an incomplete receipt (R9)."""
    limit = (
        INCOMPLETE_RECEIPT_DEADLINE_SECONDS
        if deadline_seconds is None
        else int(deadline_seconds)
    )
    started = receipt.get("startedAt") or receipt.get("timestamp")
    if not isinstance(started, str):
        return True, None
    dt = _parse_ts(started)
    if dt is None:
        return True, None
    current = now or datetime.now(timezone.utc)
    age = (current - dt).total_seconds()
    return age > limit, age


def check_incomplete_transition_receipt(
    root: Path,
    run_id: str | None,
    *,
    deadline_seconds: int | None = None,
    raise_on_overdue: bool = True,
) -> dict[str, Any]:
    """Fail closed when an incomplete transition receipt is past its deadline (R9)."""
    from wave_transition_receipt import find_incomplete_receipt

    rid = (run_id or "").strip() or None
    # Finalize-completion may run before runId is bound (closure completeness tests /
    # early mechanical steps). Missing run id means there is no receipt namespace to
    # inspect — do not raise RunIdRequiredError.
    if not rid:
        return {"blocked": False, "reason": "no-run-id"}
    receipt = find_incomplete_receipt(root, rid)
    if not receipt:
        return {"blocked": False, "reason": "no-incomplete-receipt"}

    past, age = incomplete_receipt_past_deadline(
        receipt, deadline_seconds=deadline_seconds
    )
    transition = receipt.get("transitionName") or receipt.get("transition")
    resume = resume_finalize_completion_command(rid)
    limit = (
        INCOMPLETE_RECEIPT_DEADLINE_SECONDS
        if deadline_seconds is None
        else int(deadline_seconds)
    )
    if not past:
        return {
            "blocked": False,
            "reason": "incomplete-within-deadline",
            "receipt": receipt,
            "ageSeconds": age,
            "deadlineSeconds": limit,
            "resumeCommand": resume,
        }

    payload = {
        "blocked": True,
        "reason": "incomplete-receipt-past-deadline",
        "receipt": receipt,
        "transitionName": transition,
        "ageSeconds": age,
        "deadlineSeconds": limit,
        "resumeCommand": resume,
    }
    message = (
        f"incomplete transition receipt {transition!r} past deadline "
        f"(ageSeconds={age}); resume via {resume}"
    )
    if raise_on_overdue:
        raise IncompleteReceiptStallError(
            message,
            resume_command=resume,
            receipt=receipt,
            age_seconds=age,
        )
    payload["error"] = message
    return payload


def dual_drive_heartbeat_is_stale(
    state: dict[str, Any],
    *,
    timeout_seconds: int | None = None,
) -> bool:
    """True when driver heartbeat is missing or older than the wall-clock timeout (R10)."""
    limit = (
        DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS
        if timeout_seconds is None
        else int(timeout_seconds)
    )
    hb = state.get("driverHeartbeatAt")
    if not isinstance(hb, str):
        return True
    age = age_seconds(hb)
    if age is None:
        return True
    return age >= limit


def dual_drive_heartbeat_blocks_finalize(
    state: dict[str, Any],
    *,
    timeout_seconds: int | None = None,
) -> bool:
    """True only while a dual-drive heartbeat is still within the wall-clock timeout (R10)."""
    if state.get("verdict") != "running" or not state.get("phases"):
        return False
    return not dual_drive_heartbeat_is_stale(state, timeout_seconds=timeout_seconds)


def prepare_finalize_completion_stall_recovery(
    root: Path,
    state: dict[str, Any],
    *,
    run_id: str | None = None,
    receipt_deadline_seconds: int | None = None,
    dual_drive_timeout_seconds: int | None = None,
    raise_on_incomplete_receipt: bool = True,
) -> dict[str, Any]:
    """Run R7–R10 stall recovery before finalize-completion proceeds."""
    rid = (run_id or state.get("runId") or "").strip() or None

    if rid:
        lease_result = reclaim_dead_pid_run_lease(root, rid, reclaiming_run_id=rid)
    else:
        lease_result = {"reclaimed": False, "reason": "run-id-missing"}

    living_result = clear_dead_living_docs_lock(root)

    receipt_result = check_incomplete_transition_receipt(
        root,
        rid,
        deadline_seconds=receipt_deadline_seconds,
        raise_on_overdue=raise_on_incomplete_receipt,
    )

    timeout = (
        DUAL_DRIVE_HEARTBEAT_TIMEOUT_SECONDS
        if dual_drive_timeout_seconds is None
        else int(dual_drive_timeout_seconds)
    )
    hb = state.get("driverHeartbeatAt")
    hb_age = age_seconds(hb) if isinstance(hb, str) else None
    dual_stale = dual_drive_heartbeat_is_stale(
        state, timeout_seconds=dual_drive_timeout_seconds
    )
    dual_blocks = dual_drive_heartbeat_blocks_finalize(
        state, timeout_seconds=dual_drive_timeout_seconds
    )
    dual_result = {
        "stale": dual_stale,
        "blocksFinalize": dual_blocks,
        "timeoutSeconds": timeout,
        "driverHeartbeatAt": hb if isinstance(hb, str) else None,
        "ageSeconds": hb_age,
    }

    diagnostics = [
        d
        for d in (
            lease_result.get("warning"),
            living_result.get("diagnostic"),
        )
        if isinstance(d, str) and d
    ]
    return {
        "at": _utc_now(),
        "runId": rid,
        "runLease": lease_result,
        "livingDocsLock": living_result,
        "transitionReceipt": receipt_result,
        "dualDriveHeartbeat": dual_result,
        "diagnostics": diagnostics,
        "mutated": bool(lease_result.get("reclaimed") or living_result.get("cleared")),
    }
