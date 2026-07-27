#!/usr/bin/env python3
"""Target-lock guard for spec-seed mutations (PRD 081 R19)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from wave_lock import target_lock_key_digest, target_lock_path_for
from wave_state import read_lock_meta, read_run_local_lease


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
    }
