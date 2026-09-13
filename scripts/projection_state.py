#!/usr/bin/env python3
"""Resumable projection state for partial INDEX/gap progress (PRD 344 R4).

Persists under ``.cursor/sw-projection-state/`` so interrupted living-doc
projection (timeout / rate-limit) can resume without redoing completed steps.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wave_json_io import read_json, write_json

PROJECTION_STATE_SCHEMA_VERSION = 1
PROJECTION_STATE_DIR = Path(("." + "cursor")) / "sw-projection-state"
PROJECTION_STEPS = ("index", "gap-resolve")
PROJECTION_STATUSES = frozenset({"in-progress", "interrupted", "complete"})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sanitize_scope(scope: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", (scope or "default").strip())
    return safe or "default"


def projection_scope(*, prd: str, slug: str = "", action: str = "reconcile") -> str:
    """Stable scope key for a projection run (prd + optional slug + action)."""
    prd_part = (prd or "unknown").strip() or "unknown"
    slug_part = (slug or "").strip()
    action_part = (action or "reconcile").strip() or "reconcile"
    if slug_part:
        return sanitize_scope(f"{prd_part}-{slug_part}-{action_part}")
    return sanitize_scope(f"{prd_part}-{action_part}")


def projection_state_dir(root: Path) -> Path:
    return Path(root).resolve() / PROJECTION_STATE_DIR


def projection_state_path(root: Path, scope: str) -> Path:
    return projection_state_dir(root) / f"{sanitize_scope(scope)}.json"


def empty_projection_state(
    *,
    scope: str,
    prd: str = "",
    slug: str = "",
    action: str = "reconcile",
    worktree: str | None = None,
    steps: tuple[str, ...] | list[str] = PROJECTION_STEPS,
) -> dict[str, Any]:
    return {
        "schemaVersion": PROJECTION_STATE_SCHEMA_VERSION,
        "scope": sanitize_scope(scope),
        "prd": prd,
        "slug": slug,
        "action": action,
        "status": "in-progress",
        "worktree": worktree,
        "steps": list(steps),
        "completedSteps": [],
        "pendingSteps": list(steps),
        "results": {},
        "interrupt": None,
        "createdAt": _utc_now_iso(),
        "updatedAt": _utc_now_iso(),
    }


def load_projection_state(root: Path, scope: str) -> dict[str, Any]:
    """Load projection state; missing file → empty in-progress template."""
    path = projection_state_path(root, scope)
    data = read_json(path, absent_ok=True)
    if not data:
        return empty_projection_state(scope=scope)
    if not isinstance(data.get("completedSteps"), list):
        data["completedSteps"] = []
    if not isinstance(data.get("pendingSteps"), list):
        data["pendingSteps"] = [
            step
            for step in (data.get("steps") or list(PROJECTION_STEPS))
            if step not in data["completedSteps"]
        ]
    if not isinstance(data.get("results"), dict):
        data["results"] = {}
    data["scope"] = sanitize_scope(str(data.get("scope") or scope))
    return data


def save_projection_state(root: Path, state: dict[str, Any]) -> Path:
    """Persist projection state atomically (R4)."""
    scope = sanitize_scope(str(state.get("scope") or "default"))
    state = dict(state)
    state["scope"] = scope
    state["schemaVersion"] = int(state.get("schemaVersion") or PROJECTION_STATE_SCHEMA_VERSION)
    state["updatedAt"] = _utc_now_iso()
    if "createdAt" not in state:
        state["createdAt"] = state["updatedAt"]
    path = projection_state_path(root, scope)
    write_json(path, state)
    return path


def clear_projection_state(root: Path, scope: str) -> bool:
    """Remove persisted state after successful completion. Returns True if removed."""
    path = projection_state_path(root, scope)
    if not path.is_file():
        return False
    path.unlink()
    return True


def mark_step_complete(
    state: dict[str, Any],
    step: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record a completed projection step and refresh pendingSteps (ordered)."""
    completed = [str(s) for s in (state.get("completedSteps") or []) if s]
    if step not in completed:
        completed.append(step)
    state["completedSteps"] = completed
    steps = [str(s) for s in (state.get("steps") or list(PROJECTION_STEPS))]
    state["steps"] = steps
    state["pendingSteps"] = [s for s in steps if s not in completed]
    results = dict(state.get("results") or {})
    if result is not None:
        results[step] = result
    state["results"] = results
    if not state["pendingSteps"]:
        state["status"] = "complete"
        state["interrupt"] = None
    else:
        state["status"] = "in-progress"
    state["updatedAt"] = _utc_now_iso()
    return state


def next_pending_step(state: dict[str, Any]) -> str | None:
    pending = state.get("pendingSteps") or []
    if not pending:
        steps = state.get("steps") or list(PROJECTION_STEPS)
        completed = set(state.get("completedSteps") or [])
        pending = [s for s in steps if s not in completed]
    return str(pending[0]) if pending else None


def is_projection_complete(state: dict[str, Any]) -> bool:
    if state.get("status") == "complete":
        return True
    return next_pending_step(state) is None


def record_interrupt(
    state: dict[str, Any],
    *,
    cause: str,
    error: str,
    resume_command: str,
    step: str | None = None,
    retryable: bool = True,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mark state interrupted and attach resume metadata (R2/R4)."""
    state["status"] = "interrupted"
    interrupt: dict[str, Any] = {
        "cause": cause,
        "error": error,
        "step": step or next_pending_step(state),
        "retryable": retryable,
        "resumeCommand": resume_command,
        "at": _utc_now_iso(),
    }
    if details:
        interrupt["details"] = details
    state["interrupt"] = interrupt
    state["updatedAt"] = _utc_now_iso()
    return state


def build_projection_resume_command(
    worktree: Path,
    *,
    root: Path | None = None,
    commit: bool = True,
) -> str:
    """Operator-facing resume command for interrupted living-docs projection."""
    wt = worktree.resolve()
    base = "python3 scripts/wave.py living-docs reconcile"
    if commit:
        base += " --commit"
    if root is not None and wt != root.resolve():
        return f"{base} --orchestrator-worktree {wt}"
    return base


def is_primary_checkout(path: Path) -> bool:
    """True when *path* is the repository's primary worktree checkout (R3)."""
    from primary_checkout_guard import canonical_repo_root, primary_worktree_path

    resolved = path.resolve()
    try:
        repo = canonical_repo_root(resolved)
        primary = primary_worktree_path(repo)
    except ValueError:
        return False
    return resolved == primary


def prefer_worktree_projection_root(
    root: Path,
    worktree: Path,
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Prefer a non-primary worktree for projection when running on primary (R3).

    Returns a decision dict with ``projectionRoot`` (where state is stored / ops run)
    and metadata for halt reports.
    """
    import os

    env_map = env if env is not None else os.environ
    root_r = root.resolve()
    wt_r = worktree.resolve()
    decision: dict[str, Any] = {
        "onPrimary": False,
        "projectionRoot": str(wt_r),
        "worktree": str(wt_r),
        "root": str(root_r),
        "preferred": False,
        "reason": "already-worktree-scoped",
    }

    from primary_checkout_guard import canonical_repo_root, primary_worktree_path

    try:
        repo = canonical_repo_root(wt_r)
        primary = primary_worktree_path(repo)
    except ValueError:
        decision["reason"] = "not-a-git-repo"
        return decision

    decision["primaryCheckout"] = str(primary)
    on_primary = wt_r == primary or root_r == primary
    decision["onPrimary"] = on_primary
    if not on_primary:
        return decision

    # Explicit non-primary worktree already selected via --worktree / --orchestrator-worktree.
    if wt_r != primary:
        decision["preferred"] = True
        decision["reason"] = "explicit-non-primary-worktree"
        decision["projectionRoot"] = str(wt_r)
        return decision

    for key in ("SW_ORCHESTRATOR_WORKTREE", "SW_REPO_ROOT"):
        raw = (env_map.get(key) or "").strip()
        if not raw:
            continue
        candidate = Path(raw).expanduser().resolve()
        if candidate.is_dir() and candidate != primary:
            decision["preferred"] = True
            decision["reason"] = f"env:{key}"
            decision["projectionRoot"] = str(candidate)
            decision["worktree"] = str(candidate)
            return decision

    decision["reason"] = "primary-no-alternate-worktree"
    decision["projectionRoot"] = str(wt_r)
    return decision
