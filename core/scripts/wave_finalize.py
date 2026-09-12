#!/usr/bin/env python3
"""Finalize adopt recovery — hash rebind + dead orch clearance (PRD 348 R2/R3/R3a).

Before finalize identity assessment:
  - Rebind ``sourceTaskListContentHash`` from primary materialize when the freeze-time
    hash diverges (checkbox edits on orch/primary materialize — R2).
  - Clear a dead ``orchestratorWorktree`` reference (path missing or PID absent) without
    discarding durable finalize checkpoint data (R3, R3a).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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


def read_primary_materialize_task_list(
    root: Path, task_list_rel: str
) -> tuple[Path | None, bytes | None]:
    """Resolve and read the primary materialize task-list bytes (R2 source of truth)."""
    rel = (task_list_rel or "").strip()
    if not rel:
        return None, None
    try:
        import planning_materialize as pm
        import planning_path_redirect

        pm.ensure_run_entry_materialized(root, rel)
        _resolved, readable = planning_path_redirect.resolve_readable_path(root, rel)
        candidate = readable if readable is not None and readable.is_file() else root / rel
    except Exception:
        candidate = root / rel
    if not candidate.is_file():
        return None, None
    return candidate, candidate.read_bytes()


def rebind_source_task_list_content_hash(
    root: Path,
    state: dict[str, Any],
    *,
    prior_text: str | None = None,
) -> dict[str, Any]:
    """Rebind ``sourceTaskListContentHash`` from primary materialize when it diverges (R2).

    When ``prior_text`` is supplied, rebind only if the divergence is checkbox-only
    (``checkbox_diff.is_checkbox_only_diff``). When omitted, any materialize hash
    mismatch triggers rebind — the finalize recovery path for stale freeze-time hashes.
    """
    from wave_run_adopt import compute_task_list_content_hash

    task_list = state.get("source_task_list")
    if not isinstance(task_list, str) or not task_list.strip():
        return {
            "rebound": False,
            "reason": "source-task-list-missing",
        }

    rel = task_list.strip()
    path, body = read_primary_materialize_task_list(root, rel)
    computed = compute_task_list_content_hash(root, rel)
    if computed is None or body is None:
        return {
            "rebound": False,
            "reason": "materialize-unreadable",
            "taskList": rel,
        }

    recorded = state.get("sourceTaskListContentHash")
    recorded_s = str(recorded) if recorded else ""
    if recorded_s and recorded_s == computed:
        return {
            "rebound": False,
            "reason": "hash-already-current",
            "hash": computed,
            "taskList": rel,
            "materializePath": str(path) if path else None,
        }

    if prior_text is not None:
        from checkbox_diff import is_checkbox_only_diff

        new_text = body.decode("utf-8")
        if not is_checkbox_only_diff(prior_text, new_text):
            return {
                "rebound": False,
                "reason": "divergence-not-checkbox-only",
                "recordedHash": recorded_s or None,
                "computedHash": computed,
                "taskList": rel,
            }

    previous = recorded_s or None
    state["sourceTaskListContentHash"] = computed
    diagnostic = (
        f"finalize:rebind-sourceTaskListContentHash "
        f"previous={previous or 'none'} current={computed} taskList={rel}"
    )
    logger.warning(diagnostic)
    return {
        "rebound": True,
        "reason": (
            "checkbox-diverged-materialize"
            if prior_text is not None
            else "materialize-hash-mismatch"
        ),
        "previousHash": previous,
        "newHash": computed,
        "taskList": rel,
        "materializePath": str(path) if path else None,
        "diagnostic": diagnostic,
    }


def orchestrator_worktree_is_dead(orch: Any) -> tuple[bool, str | None]:
    """Return (dead, reason) for an ``orchestratorWorktree`` record (R3).

    Dead when the worktree directory is missing, or a recorded PID is absent from
    the process table.
    """
    if not isinstance(orch, dict) or not orch:
        return False, None
    raw_path = orch.get("path")
    if not raw_path:
        return True, "worktree-missing"
    path = Path(str(raw_path))
    if not path.exists():
        return True, "worktree-missing"
    pid = orch.get("pid")
    if isinstance(pid, int) and pid > 0 and not _pid_alive(pid):
        return True, "pid-absent"
    if isinstance(pid, str) and pid.isdigit() and not _pid_alive(int(pid)):
        return True, "pid-absent"
    return False, None


def clear_dead_orchestrator_worktree(
    state: dict[str, Any],
    *,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Clear a dead ``orchestratorWorktree`` without discarding checkpoint data (R3/R3a).

    ``checkpoint`` is accepted for call-site clarity and is never mutated.
    """
    _ = checkpoint  # R3a — durable checkpoint must remain untouched
    orch = state.get("orchestratorWorktree")
    dead, reason = orchestrator_worktree_is_dead(orch)
    if not dead:
        return {
            "cleared": False,
            "reason": "orchestrator-live-or-absent",
            "dead": False,
        }

    cleared_path = None
    cleared_pid = None
    if isinstance(orch, dict):
        cleared_path = orch.get("path")
        cleared_pid = orch.get("pid")
    state.pop("orchestratorWorktree", None)
    diagnostic = (
        f"finalize:clear-dead-orchestratorWorktree reason={reason} "
        f"path={cleared_path!r} pid={cleared_pid!r}"
    )
    logger.warning(diagnostic)
    return {
        "cleared": True,
        "dead": True,
        "reason": reason,
        "clearedPath": cleared_path,
        "clearedPid": cleared_pid,
        "diagnostic": diagnostic,
        "checkpointPreserved": True,
    }


def prepare_finalize_recovery(
    root: Path,
    state: dict[str, Any],
    *,
    run_id: str | None = None,
    persist: bool = True,
    prior_task_list_text: str | None = None,
    checkpoint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply R2 hash rebind + R3 dead-orch clearance before finalize identity assess."""
    orch_result = clear_dead_orchestrator_worktree(state, checkpoint=checkpoint)
    hash_result = rebind_source_task_list_content_hash(
        root, state, prior_text=prior_task_list_text
    )

    mutated = bool(orch_result.get("cleared") or hash_result.get("rebound"))
    persisted = False
    rid = run_id or state.get("runId")
    if persist and mutated and isinstance(rid, str) and rid.strip():
        from wave_state import save_run_scoped_state

        save_run_scoped_state(root, rid.strip(), state)
        persisted = True

    diagnostics = [
        d
        for d in (orch_result.get("diagnostic"), hash_result.get("diagnostic"))
        if isinstance(d, str) and d
    ]
    return {
        "mutated": mutated,
        "persisted": persisted,
        "at": _utc_now(),
        "orchClearance": orch_result,
        "hashRebind": hash_result,
        "diagnostics": diagnostics,
    }
