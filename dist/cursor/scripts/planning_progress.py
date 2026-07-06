#!/usr/bin/env python3
"""Deliver progress sync — hierarchy map + phase/issue alignment (PRD 056 R5-R7)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_materialize as pm  # noqa: E402
import planning_path_redirect  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_hierarchy import project_task_list_hierarchy  # noqa: E402
from planning_store import resolve_effective_backend  # noqa: E402
from wave_state import load_hierarchy_map, set_hierarchy_map  # noqa: E402

CHECKBOX_FALLBACK_NOTICE = (
    "issue-store not effective; deliver hierarchy uses checkbox/body fallback only"
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hierarchy_map_from_apply(result: dict[str, Any]) -> dict[str, Any]:
    """Build durable hierarchyMap from hierarchy apply projection (PRD 056 R5)."""
    phases: dict[str, Any] = {}
    for sub in result.get("subIssues") or []:
        if not isinstance(sub, dict):
            continue
        pid = str(sub.get("phaseId", ""))
        if not pid:
            continue
        phases[pid] = {
            "phaseId": pid,
            "issueId": sub.get("issueId"),
            "number": sub.get("number"),
        }
    return {
        "unitId": result.get("unitId"),
        "mode": result.get("mode"),
        "provider": result.get("provider"),
        "projectKey": result.get("projectKey"),
        "epicIssueId": result.get("epicIssueId"),
        "phases": phases,
        "applied": True,
        "appliedAt": utc_now(),
        "notice": result.get("notice"),
    }


def _resolve_task_list_path(root: Path, task_rel: str) -> Path:
    pm.ensure_run_entry_materialized(root, task_rel)
    _resolved_rel, path = planning_path_redirect.resolve_readable_path(root, task_rel)
    if path is not None:
        return path
    return root / task_rel


def provision_deliver_hierarchy(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Apply task-list hierarchy on phase provision when issue-store is effective (R5, R9)."""
    cfg = load_workflow_config(root)
    backend = resolve_effective_backend(root, cfg)
    if backend.get("effective") != "issue-store":
        return {
            "verdict": "ok",
            "skipped": True,
            "mode": "checkbox-fallback",
            "notice": CHECKBOX_FALLBACK_NOTICE,
        }

    existing = load_hierarchy_map(state)
    if existing.get("applied"):
        return {"verdict": "ok", "idempotent": True, "hierarchyMap": existing}

    task_rel = state.get("source_task_list")
    if not isinstance(task_rel, str) or not task_rel.strip():
        return {"verdict": "fail", "error": "missing source_task_list for hierarchy apply"}

    task_path = _resolve_task_list_path(root, task_rel)
    if not task_path.is_file():
        return {"verdict": "fail", "error": f"task list not found: {task_rel}"}

    result = project_task_list_hierarchy(root, task_path, dry_run=False)
    if result.get("verdict") != "ok":
        return result

    hmap = hierarchy_map_from_apply(result)
    set_hierarchy_map(state, hmap)
    out: dict[str, Any] = {
        "verdict": "ok",
        "hierarchyMap": hmap,
        "applied": True,
        "mode": hmap.get("mode"),
    }
    if result.get("notice"):
        out["notice"] = result["notice"]
    return out
