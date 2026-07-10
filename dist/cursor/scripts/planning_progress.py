#!/usr/bin/env python3
"""Deliver progress sync — hierarchy map + phase/issue alignment (PRD 056 R5-R7)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import doc_format  # noqa: E402
import planning_materialize as pm  # noqa: E402
import planning_path_redirect  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_hierarchy import project_task_list_hierarchy  # noqa: E402
from planning_store import progress_update, resolve_effective_backend  # noqa: E402
from wave_state import load_deliver_state, load_hierarchy_map, set_hierarchy_map  # noqa: E402


_PROVISION_APPLY_COUNT = 0


def _checked_phase_ids(hmap: dict[str, Any], phase_id: str) -> list[str]:
    checked: list[str] = []
    phases = hmap.get("phases")
    if isinstance(phases, dict):
        for pid, entry in phases.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("doneSynced") or str(pid) == str(phase_id):
                checked.append(str(pid))
    if str(phase_id) not in checked:
        checked.append(str(phase_id))
    return sorted(set(checked))


def _parent_progress_mode(hmap: dict[str, Any]) -> bool:
    return str(hmap.get("mode") or "") in {"parent-checkbox", "checkbox"}

CHECKBOX_FALLBACK_NOTICE = (
    "issue-store not effective; deliver hierarchy uses checkbox/body fallback only"
)
_PROGRESS_LABEL_DEGRADED_EMITTED = False
_PROGRESS_BODY_DEGRADED_EMITTED = False


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hierarchy_map_from_apply(result: dict[str, Any]) -> dict[str, Any]:
    """Build durable hierarchyMap from hierarchy apply projection (PRD 056 R5, PRD 061 R6)."""
    phases: dict[str, Any] = {}
    mode = str(result.get("mode") or "")
    if mode == "epic-sub-issue":
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
    else:
        for phase in result.get("phases") or []:
            if not isinstance(phase, dict):
                continue
            pid = str(phase.get("id", ""))
            if not pid:
                continue
            phases[pid] = {"phaseId": pid}
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

    global _PROVISION_APPLY_COUNT
    _PROVISION_APPLY_COUNT += 1
    result = project_task_list_hierarchy(root, task_path, dry_run=False)
    if result.get("verdict") != "ok":
        return result

    hmap = hierarchy_map_from_apply(result)
    hmap["provisionApplyCount"] = _PROVISION_APPLY_COUNT
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


def phase_done_label(phase_id: str) -> str:
    """Durable phase-complete label on sub-issues (PRD 056 D3)."""
    return f"sw:phase:{phase_id}:done"


def _emit_progress_notice(kind: str, message: str) -> None:
    global _PROGRESS_LABEL_DEGRADED_EMITTED, _PROGRESS_BODY_DEGRADED_EMITTED
    if kind == "label" and _PROGRESS_LABEL_DEGRADED_EMITTED:
        return
    if kind == "body" and _PROGRESS_BODY_DEGRADED_EMITTED:
        return
    if kind == "label":
        _PROGRESS_LABEL_DEGRADED_EMITTED = True
        notice = "progress-label-degraded"
    else:
        _PROGRESS_BODY_DEGRADED_EMITTED = True
        notice = "progress-body-degraded"
    payload = {"verdict": "notice", "notice": notice, "message": message}
    print(json.dumps(payload, ensure_ascii=False), file=sys.stderr)


def _issue_store_effective(root: Path) -> bool:
    cfg = load_workflow_config(root)
    return resolve_effective_backend(root, cfg).get("effective") == "issue-store"


def _phase_map_entry(hmap: dict[str, Any], phase_id: str) -> dict[str, Any] | None:
    phases = hmap.get("phases")
    if not isinstance(phases, dict):
        return None
    entry = phases.get(str(phase_id))
    return entry if isinstance(entry, dict) else None


def _mark_phase_done_synced(state: dict[str, Any], phase_id: str) -> None:
    hmap = load_hierarchy_map(state)
    phases = hmap.get("phases")
    if not isinstance(phases, dict):
        return
    entry = phases.get(str(phase_id))
    if not isinstance(entry, dict):
        return
    entry["doneSynced"] = True
    entry["doneSyncedAt"] = utc_now()
    phases[str(phase_id)] = entry
    hmap["phases"] = phases
    set_hierarchy_map(state, hmap)


def resolve_phase_id(
    state: dict[str, Any],
    phase_slug: str,
    *,
    tasks_text: str | None = None,
) -> str | None:
    phases = state.get("phases") or {}
    if isinstance(phases, dict):
        for pid, meta in phases.items():
            if isinstance(meta, dict) and meta.get("slug") == phase_slug:
                return str(pid)
    if tasks_text:
        for phase in doc_format.extract_phases(tasks_text):
            if phase.get("slug") == phase_slug:
                return str(phase.get("id") or "")
    return None


def sync_phase_done(root: Path, state: dict[str, Any], phase_id: str) -> dict[str, Any]:
    """Apply phase-done progress on parent or opt-in sub-issue (PRD 056 R6, PRD 061 R6–R8)."""
    if not _issue_store_effective(root):
        return {"verdict": "ok", "skipped": True, "reason": "file-store"}

    hmap = load_hierarchy_map(state)
    if not hmap.get("applied"):
        return {"verdict": "ok", "skipped": True, "reason": "no-hierarchy-map"}

    entry = _phase_map_entry(hmap, phase_id)
    if entry is None:
        return {"verdict": "ok", "skipped": True, "reason": "phase-not-in-map", "phaseId": phase_id}

    if entry.get("doneSynced"):
        target = entry.get("issueId") or hmap.get("epicIssueId")
        return {
            "verdict": "ok",
            "idempotent": True,
            "phaseId": phase_id,
            "issueId": target,
        }

    if _parent_progress_mode(hmap):
        parent_id = hmap.get("epicIssueId")
        if not parent_id:
            return {"verdict": "ok", "skipped": True, "reason": "missing-parent-issue", "phaseId": phase_id}
        task_rel = state.get("source_task_list")
        task_list = str(task_rel) if isinstance(task_rel, str) else None
        out = progress_update(
            root,
            parent_issue_id=str(parent_id),
            phase_id=str(phase_id),
            action="phase-done",
            provider=str(hmap.get("provider") or "none"),
            project_key=str(hmap.get("projectKey") or ""),
            task_list=task_list,
            checked_phase_ids=_checked_phase_ids(hmap, phase_id),
        )
        if out.get("degraded"):
            _emit_progress_notice("label", str(out.get("error") or out.get("notice") or "progress-update-degraded"))
        if out.get("verdict") == "ok" and not out.get("skipped"):
            _mark_phase_done_synced(state, phase_id)
        out.setdefault("phaseId", phase_id)
        out.setdefault("issueId", parent_id)
        return out

    issue_id = entry.get("issueId")
    if not issue_id:
        return {"verdict": "ok", "skipped": True, "reason": "missing-sub-issue", "phaseId": phase_id}

    out = progress_update(
        root,
        parent_issue_id=str(issue_id),
        phase_id=str(phase_id),
        action="phase-done",
        provider=str(hmap.get("provider") or "none"),
        project_key=str(hmap.get("projectKey") or ""),
    )
    if out.get("degraded"):
        _emit_progress_notice("label", str(out.get("error") or out.get("notice") or "progress-update-degraded"))
    if out.get("verdict") == "ok" and not out.get("skipped"):
        _mark_phase_done_synced(state, phase_id)
    out.setdefault("phaseId", phase_id)
    out.setdefault("issueId", issue_id)
    return out


def sync_task_checkbox(
    root: Path,
    state: dict[str, Any],
    *,
    phase_id: str,
    task_list: str | Path,
    task_ref: str | None = None,
) -> dict[str, Any]:
    """Mirror phase task checkboxes onto the phase sub-issue body (PRD 056 R7)."""
    if not _issue_store_effective(root):
        return {"verdict": "ok", "skipped": True, "reason": "file-store"}

    hmap = load_hierarchy_map(state)
    if not hmap.get("applied"):
        return {"verdict": "ok", "skipped": True, "reason": "no-hierarchy-map"}

    entry = _phase_map_entry(hmap, phase_id)
    target_id = hmap.get("epicIssueId") if _parent_progress_mode(hmap) else (entry.get("issueId") if entry else None)
    if not target_id:
        return {"verdict": "ok", "skipped": True, "reason": "missing-progress-target", "phaseId": phase_id}

    out = progress_update(
        root,
        parent_issue_id=str(target_id),
        phase_id=str(phase_id),
        action="task-checkbox",
        provider=str(hmap.get("provider") or "none"),
        project_key=str(hmap.get("projectKey") or ""),
        task_list=task_list,
        task_ref=task_ref,
    )
    if out.get("degraded"):
        _emit_progress_notice("body", str(out.get("error") or out.get("notice") or "progress-body-degraded"))
    out.setdefault("phaseId", phase_id)
    out.setdefault("issueId", target_id)
    if task_ref:
        out.setdefault("taskRef", task_ref)
    return out


def propagate_checkbox_to_issue_store(
    root: Path,
    task_ref: str,
    task_list: str,
    phase_slug: str,
) -> dict[str, Any]:
    """Load deliver state and sync checkbox toggles when hierarchyMap is present."""
    try:
        state = load_deliver_state(root)
    except Exception:
        return {"verdict": "ok", "skipped": True, "reason": "no-deliver-state"}

    task_path = Path(task_list)
    if not task_path.is_absolute():
        task_path = (root / task_list).resolve()
    tasks_text = task_path.read_text(encoding="utf-8") if task_path.is_file() else None
    phase_id = resolve_phase_id(state, phase_slug, tasks_text=tasks_text)
    if not phase_id:
        return {"verdict": "ok", "skipped": True, "reason": "phase-id-unresolved", "phaseSlug": phase_slug}
    return sync_task_checkbox(
        root,
        state,
        phase_id=phase_id,
        task_list=task_list,
        task_ref=task_ref,
    )
