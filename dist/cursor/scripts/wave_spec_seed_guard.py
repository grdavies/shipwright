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
    doc_to_feature_handoff_lock_key_digest,
    doc_to_feature_handoff_lock_path_for,
    target_lock_key_digest,
    target_lock_path_for,
)
from wave_state import read_lock_meta, read_run_local_lease, utc_now
from wave_target_lock import (
    acquire_doc_to_feature_handoff_lock,
    is_doc_loop_run_id,
    release_doc_to_feature_handoff_lock,
)

VERIFIED_COMPLETION_OUTCOMES = frozenset({"committed", "already-present"})


def assert_handoff_completion_remote_state(remote_state: dict[str, Any]) -> None:
    """Reject ambiguous dryRun defaults — completion requires verified commit outcome (R6)."""
    if not remote_state:
        raise PermissionError("feature-seed completion refused: missing remote state")
    if remote_state.get("dryRun") is True:
        raise PermissionError(
            "feature-seed completion refused: ambiguous unflipped dryRun default"
        )
    if remote_state.get("dryRun") is None and not remote_state.get("commit"):
        raise PermissionError(
            "feature-seed completion refused: ambiguous remote state (no commit, dryRun unset)"
        )
    completion = remote_state.get("completion")
    if isinstance(completion, dict):
        outcome = completion.get("outcome")
        if outcome not in VERIFIED_COMPLETION_OUTCOMES:
            raise PermissionError(
                f"feature-seed completion refused: outcome {outcome!r} not verified-complete"
            )
        if not completion.get("verified"):
            raise PermissionError("feature-seed completion refused: completion not verified")
        if not completion.get("commit"):
            raise PermissionError(
                "feature-seed completion refused: completion missing commit SHA"
            )
        return
    commit = remote_state.get("commit")
    if not commit:
        raise PermissionError("feature-seed completion refused: missing commit SHA")
    if remote_state.get("dryRun") is not False:
        raise PermissionError(
            "feature-seed completion refused: dryRun must be false for verified completion"
        )


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
