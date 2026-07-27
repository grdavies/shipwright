#!/usr/bin/env python3
"""Per-run plan persistence and hash verification (PRD 081 R18)."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

from wave_json_io import StateCorruptError, read_json, write_json
from wave_run_paths import mint_run_id, plan_path, require_run_id


class PlanHashMismatchError(ValueError):
    """Raised when plan content hash differs from the recorded hash."""


class PlanRecordMissingError(ValueError):
    """Raised when run state lacks required plan metadata."""


class PlanCommitShaMismatchError(ValueError):
    """Raised when plan commit SHA does not match expected HEAD."""


def canonical_plan_bytes(plan: dict[str, Any]) -> bytes:
    return (
        json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def compute_plan_hash(plan: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_plan_bytes(plan)).hexdigest()


def next_plan_revision(state: dict[str, Any]) -> int:
    prior = state.get("planRevision")
    if isinstance(prior, int) and prior >= 0:
        return prior + 1
    return 1


def resolve_run_id(state: dict[str, Any]) -> str:
    return require_run_id(state.get("runId"))


def ensure_run_id(root: Path, state: dict[str, Any]) -> str:
    existing = state.get("runId")
    if existing:
        return require_run_id(str(existing))
    run_id = mint_run_id(root)
    state["runId"] = run_id
    return run_id


def head_sha(root: Path) -> str | None:
    proc = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    sha = proc.stdout.strip()
    return sha if len(sha) == 40 else None


def relative_plan_path(root: Path, run_id: str) -> str:
    path = plan_path(root, run_id).resolve()
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)


def persist_plan(
    root: Path,
    run_id: str,
    plan: dict[str, Any],
    state: dict[str, Any],
) -> dict[str, Any]:
    rid = require_run_id(run_id)
    target = plan_path(root, rid)
    write_json(target, plan)
    content_hash = compute_plan_hash(plan)
    revision = next_plan_revision(state)
    metadata: dict[str, Any] = {
        "planPath": relative_plan_path(root, rid),
        "planHash": content_hash,
        "planRevision": revision,
    }
    commit_sha = head_sha(root)
    if commit_sha:
        metadata["planCommitSha"] = commit_sha
    state.update(metadata)
    return metadata


def verify_plan_hash(root: Path, run_id: str, state: dict[str, Any]) -> None:
    recorded_hash = state.get("planHash")
    if not isinstance(recorded_hash, str) or not recorded_hash:
        raise PlanRecordMissingError("planHash missing from run state")
    path_rel = state.get("planPath")
    if not isinstance(path_rel, str) or not path_rel:
        raise PlanRecordMissingError("planPath missing from run state")
    on_disk = (root / path_rel).resolve()
    expected = plan_path(root, run_id).resolve()
    if on_disk != expected:
        raise PlanHashMismatchError(f"planPath {path_rel!r} outside run namespace")
    if not on_disk.is_file():
        raise PlanHashMismatchError(f"plan file missing: {on_disk}")
    try:
        plan = read_json(on_disk, absent_ok=False)
    except StateCorruptError as exc:
        raise PlanHashMismatchError(str(exc)) from exc
    actual = compute_plan_hash(plan)
    if actual != recorded_hash:
        raise PlanHashMismatchError(
            f"plan hash mismatch: recorded={recorded_hash[:12]} actual={actual[:12]}"
        )


def check_plan_commit_sha(
    state: dict[str, Any], expected_head: str | None = None
) -> tuple[bool, str | None]:
    recorded = state.get("planCommitSha")
    if not recorded:
        return False, "plan:missing-commit-sha"
    if not isinstance(recorded, str) or len(recorded) != 40:
        return False, "plan:abbreviated-commit-sha"
    if expected_head and str(recorded) != expected_head:
        return False, "plan:stale-commit-sha"
    return True, None


def load_verified_plan(
    root: Path,
    run_id: str,
    state: dict[str, Any],
    *,
    expected_head: str | None = None,
) -> dict[str, Any]:
    verify_plan_hash(root, run_id, state)
    if expected_head is not None:
        ok, cause = check_plan_commit_sha(state, expected_head)
        if not ok:
            raise PlanCommitShaMismatchError(cause or "plan:stale-commit-sha")
    return read_json(plan_path(root, run_id), absent_ok=False)


def load_plan_for_state(
    root: Path, state: dict[str, Any], *, expected_head: str | None = None
) -> dict[str, Any]:
    if not state.get("planHash"):
        return {}
    run_id = resolve_run_id(state)
    return load_verified_plan(root, run_id, state, expected_head=expected_head)
