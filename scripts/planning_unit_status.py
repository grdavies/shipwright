#!/usr/bin/env python3
"""Unified planning-unit status surface and deliver entry reference helpers (PRD 059 R1-R4)."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_discover as pd  # noqa: E402
import planning_index_gen as pig  # noqa: E402
import planning_materialize as pm  # noqa: E402
import planning_paths as pp  # noqa: E402
import planning_path_redirect as ppr  # noqa: E402
import planning_visibility as pv  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from planning_deliver_gate import task_list_for_unit  # noqa: E402
from planning_store import (  # noqa: E402
    get_backend,
    host_issue_probe_facade,
    issue_get_facade,
    issue_search_by_unit_facade,
    resolve_effective_backend,
    resolve_store_location,
    validate_project_key,
)

ISSUE_SOURCE_PLANNING_STORE = "planning-store"
ISSUE_SOURCE_HOST_REPO = "host-repo"
VALID_ISSUE_SOURCES = frozenset({ISSUE_SOURCE_PLANNING_STORE, ISSUE_SOURCE_HOST_REPO})

CANONICAL_STATUSES = frozenset({"backlog", "planned", "in-progress", "complete"})
META_STATUSES = frozenset({"unauthorized", "unknown"})
UNIFIED_STATUSES = CANONICAL_STATUSES | META_STATUSES

_COMPLETE = frozenset({"complete", "resolved", "superseded", "cancelled", "closed"})
_IN_PROGRESS = frozenset({"in-progress"})
_PLANNED = frozenset({"planned", "proposed", "scheduled", "partially resolved"})
_BACKLOG = frozenset({"open", "not-started", "backlog"})


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    import json

    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def map_native_status_to_unified(native_status: str, unit_type: str) -> str:
    lowered = (native_status or "").strip().lower()
    if not lowered:
        return "backlog" if unit_type == "gap" else "unknown"
    if lowered in _COMPLETE:
        return "complete"
    if lowered in _IN_PROGRESS:
        return "in-progress"
    if lowered in _PLANNED:
        return "planned"
    if lowered in _BACKLOG:
        return "backlog"
    if lowered == "blocked":
        return "planned"
    return "unknown"


def _unit_visible(root: Path, unit: pig.PlanningUnit) -> bool:
    vis = pig.resolved_visibility(unit, root)
    return not pv.body_is_redacted(vis)


def _find_discover_unit(root: Path, unit_id: str) -> pig.PlanningUnit | None:
    for unit in pd.discover_units(root):
        if unit.id == unit_id:
            return unit
    return None


def _inflight_unit_ids(root: Path) -> set[str]:
    from inflight_signal import read_tuples

    return set(read_tuples(root).keys())


def derive_unified_status_for_unit(root: Path, unit: pig.PlanningUnit) -> str:
    if not _unit_visible(root, unit):
        return "unauthorized"
    if unit.id in _inflight_unit_ids(root):
        return "in-progress"
    return map_native_status_to_unified(unit.status, unit.type)


def canonical_status(status: str) -> str:
    lowered = (status or "").strip().lower()
    if lowered in CANONICAL_STATUSES:
        return lowered
    # Unknown and unauthorized are explicitly non-terminal.
    return "planned"


def status_is_complete(status: str) -> bool:
    return is_terminal_unified_status(status)


def is_non_terminal_meta_status(status: str) -> bool:
    return (status or "").strip().lower() in META_STATUSES


def is_terminal_unified_status(status: str) -> bool:
    lowered = (status or "").strip().lower()
    if is_non_terminal_meta_status(lowered):
        return False
    return canonical_status(lowered) == "complete" and lowered == "complete"


def query_unit_status(
    root: Path,
    *,
    unit_id: str | None = None,
    issue: str | None = None,
    issue_source: str | None = None,
) -> dict[str, Any]:
    resolved_id, issue_ref, issue_resolution = resolve_unit_reference(
        root,
        unit_id=unit_id,
        issue=issue,
        issue_source=issue_source,
    )
    unit = _find_discover_unit(root, resolved_id)
    if unit is None:
        backend = get_backend(root)
        for candidate in task_list_for_unit_candidates(root, resolved_id):
            exists = backend.exists(Path(candidate).stem, candidate)
            if exists.verdict == "ok":
                fail(
                    f"unit {resolved_id!r} exists in store but is outside active visibility",
                    exit_code=2,
                    status="unauthorized",
                    unitId=resolved_id,
                )
        fail(f"unit not found: {resolved_id}", exit_code=2, unitId=resolved_id)
    status = derive_unified_status_for_unit(root, unit)
    out: dict[str, Any] = {
        "verdict": "pass",
        "action": "unit-status",
        "unitId": resolved_id,
        "unitType": unit.type,
        "status": status,
        "canonicalStatus": canonical_status(status),
        "isComplete": status_is_complete(status),
        "nativeStatus": unit.status,
    }
    if issue_ref:
        out["issue"] = issue_ref
    if issue_resolution:
        out["issueSource"] = issue_resolution.get("issueSource")
        out["swUnitId"] = issue_resolution.get("unitId")
    return out


def task_list_for_unit_candidates(root: Path, unit_id: str) -> list[str]:
    from planning_deliver_gate import logical_task_list_candidates

    return logical_task_list_candidates(root, unit_id)


def _normalize_issue_ref(raw: str) -> str:
    return raw.strip().lstrip("#")


def _normalize_issue_source(raw: str | None) -> str | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    if normalized not in VALID_ISSUE_SOURCES:
        fail(
            f"invalid --issue-source {raw!r}; want planning-store or host-repo",
            exit_code=2,
            halt="disambiguation",
        )
    return normalized


def _issue_collision_mode(root: Path) -> bool:
    cfg = load_workflow_config(root)
    location = resolve_store_location(root, cfg)
    return location.get("verdict") == "ok" and location.get("mode") == "separate-project"


def _fail_issue_lookup(root: Path, issue_ref: str, lookup: dict[str, Any]) -> None:
    error = str(lookup.get("error") or "issue lookup failed")
    if error == "issue-not-found-or-outside-scope":
        fail(
            f"issue {issue_ref!r} not found or outside project scope",
            exit_code=2,
            issue=issue_ref,
            remediation="verify issue number belongs to the configured planning project",
        )
    if error == "--issue requires issue-store effective backend":
        fail(
            "--issue requires issue-store effective backend",
            exit_code=2,
            effectiveBackend=lookup.get("effectiveBackend"),
        )
    fail(
        f"issue lookup failed for {issue_ref!r}",
        exit_code=2,
        errorClass=error,
    )


def _probe_planning_store_issue(root: Path, issue_ref: str) -> dict[str, Any] | None:
    cfg = load_workflow_config(root)
    lookup = issue_get_facade(root, cfg, issue_ref)
    if lookup.get("verdict") != "ok":
        error = str(lookup.get("error") or "issue lookup failed")
        if error == "issue-not-found-or-outside-scope":
            return None
        _fail_issue_lookup(root, issue_ref, lookup)
    record = lookup["record"]
    return {
        "issueSource": ISSUE_SOURCE_PLANNING_STORE,
        "issue": issue_ref,
        "unitId": str(record.unit_id or "").strip(),
        "record": record,
    }


def _probe_host_repo_issue(root: Path, issue_ref: str) -> dict[str, Any] | None:
    if not _issue_collision_mode(root):
        return None
    cfg = load_workflow_config(root)
    probe = host_issue_probe_facade(root, cfg, issue_ref)
    if probe.get("verdict") != "ok":
        return None
    return {
        "issueSource": ISSUE_SOURCE_HOST_REPO,
        "issue": issue_ref,
        "unitId": str(probe.get("unitId") or "").strip(),
        "record": probe.get("record"),
    }


def _ensure_issue_has_unit_id(resolution: dict[str, Any], issue_ref: str) -> None:
    uid = str(resolution.get("unitId") or "").strip()
    if not uid:
        fail(
            f"issue {issue_ref!r} has no sw-unit-id marker",
            exit_code=2,
            issue=issue_ref,
            issueSource=resolution.get("issueSource"),
        )


def resolve_issue_entry(
    root: Path,
    issue: str,
    *,
    issue_source: str | None = None,
) -> dict[str, Any]:
    """Resolve deliver --issue entry with optional store/host selector (PRD 339 R38)."""
    issue_ref = _normalize_issue_ref(issue)
    selected_source = _normalize_issue_source(issue_source)
    planning_hit = _probe_planning_store_issue(root, issue_ref)
    host_hit = _probe_host_repo_issue(root, issue_ref)
    candidates = [hit for hit in (planning_hit, host_hit) if hit is not None]

    if selected_source:
        selected = next((c for c in candidates if c["issueSource"] == selected_source), None)
        if selected is None:
            fail(
                f"issue {issue_ref!r} not found in {selected_source!r}",
                exit_code=2,
                issue=issue_ref,
                issueSource=selected_source,
            )
        _ensure_issue_has_unit_id(selected, issue_ref)
        return selected

    if len(candidates) > 1:
        fail(
            f"ambiguous issue {issue_ref!r}: same number in planning-store and host-repo; "
            "pass --issue-source planning-store or --issue-source host-repo",
            exit_code=2,
            halt="issue-source-collision",
            issue=issue_ref,
            collisionSources=[c["issueSource"] for c in candidates],
        )

    if not candidates:
        fail(
            f"issue {issue_ref!r} not found or outside project scope",
            exit_code=2,
            issue=issue_ref,
            remediation="verify issue number belongs to the configured planning project",
        )

    hit = candidates[0]
    _ensure_issue_has_unit_id(hit, issue_ref)
    return hit


def resolve_unit_reference(
    root: Path,
    *,
    unit_id: str | None = None,
    issue: str | None = None,
    issue_source: str | None = None,
) -> tuple[str, str | None, dict[str, Any] | None]:
    if unit_id and issue:
        fail("provide only one of --unit-id or --issue", exit_code=2, halt="disambiguation")
    if issue:
        resolution = resolve_issue_entry(root, issue, issue_source=issue_source)
        return str(resolution["unitId"]), str(resolution["issue"]), resolution
    if unit_id:
        return unit_id.strip(), None, None
    fail("unit reference required: --unit-id or --issue", exit_code=2)


def _lookup_issue_record(root: Path, issue_ref: str):
    hit = _probe_planning_store_issue(root, issue_ref)
    if hit is None:
        fail(
            f"issue {issue_ref!r} not found or outside project scope",
            exit_code=2,
            issue=issue_ref,
            remediation="verify issue number belongs to the configured planning project",
        )
    _ensure_issue_has_unit_id(hit, issue_ref)
    return hit["record"]


def resolve_task_list_reference(
    root: Path,
    args: list[str],
    *,
    parse_kv,
    has_flag,
) -> str | None:
    """Resolve --task-list | --unit-id | --issue to a logical task-list path."""
    task_list = parse_kv(args, "--task-list")
    unit_id = parse_kv(args, "--unit-id")
    issue = parse_kv(args, "--issue")
    provided = sum(1 for v in (task_list, unit_id, issue) if v)
    if provided > 1:
        fail(
            "ambiguous input: provide only one of --task-list, --unit-id, or --issue",
            exit_code=2,
            halt="disambiguation",
        )
    if task_list:
        return task_list
    issue_source = parse_kv(args, "--issue-source")
    if issue_source and not issue:
        fail(
            "--issue-source requires --issue",
            exit_code=2,
            halt="disambiguation",
        )
    if unit_id or issue:
        uid, _issue_ref, _resolution = resolve_unit_reference(
            root,
            unit_id=unit_id,
            issue=issue,
            issue_source=issue_source,
        )
        rel = task_list_for_unit(root, uid)
        if not rel:
            fail(
                f"no frozen task list mapped for unit {uid!r}",
                exit_code=2,
                unitId=uid,
                remediation="freeze tasks for this unit or pass an explicit --task-list",
            )
        return rel
    return None


def materialized_task_list_path(root: Path, task_list_rel: str) -> str:
    """Return the path operators should cite — materialized dest when redirected."""
    worktree = pp.git_root(root)
    logical = ppr.resolve_path(worktree, task_list_rel)
    _resolved_rel, readable = ppr.resolve_readable_path(root, logical)
    if readable is not None:
        try:
            return str(readable.relative_to(worktree.resolve())).replace("\\", "/")
        except ValueError:
            return str(readable)
    try:
        dest = pm.materialized_dest(worktree, logical)
        if dest.is_file():
            return str(dest.relative_to(worktree.resolve())).replace("\\", "/")
    except Exception:
        pass
    return logical


def issue_ref_for_task_list(root: Path, task_list_rel: str) -> str | None:
    cfg = load_workflow_config(root)
    if resolve_effective_backend(root, cfg).get("effective") != "issue-store":
        return None
    unit_id = pm.unit_id_from_task_list_rel(task_list_rel)
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        return None
    result = issue_search_by_unit_facade(root, cfg, unit_id=unit_id)
    if result.get("verdict") != "ok":
        return None
    matches = result.get("records") or []
    if not matches:
        return None
    record = matches[0]
    number = getattr(record, "number", None)
    return str(number) if number is not None else str(record.id)


def format_deliver_entry_ref(root: Path, task_list_rel: str) -> str:
    """Prefer --unit-id / --issue under issue-store; else cite materialized path."""
    cfg = load_workflow_config(root)
    path = materialized_task_list_path(root, task_list_rel)
    if resolve_effective_backend(root, cfg).get("effective") == "issue-store":
        issue_ref = issue_ref_for_task_list(root, task_list_rel)
        if issue_ref:
            return f"--issue {issue_ref}"
        unit_id = pm.unit_id_from_task_list_rel(task_list_rel)
        prd_match = re.match(r"tasks-(\d+)-(.+)$", unit_id)
        if prd_match:
            return f"--unit-id {prd_match.group(2)}"
        return f"--unit-id {unit_id}"
    return f"--task-list {path}"


def format_deliver_run_command(root: Path, task_list_rel: str) -> str:
    return f"/sw-deliver run {format_deliver_entry_ref(root, task_list_rel)}"


def format_spec_seed_command(root: Path, task_list_rel: str) -> str:
    return f"python3 scripts/wave.py spec-seed {format_deliver_entry_ref(root, task_list_rel)}"


def format_preflight_command(root: Path, task_list_rel: str) -> str:
    return f"python3 scripts/wave.py preflight {format_deliver_entry_ref(root, task_list_rel)} --skip-base-check"


def deliver_handoff_paths(root: Path, state: dict[str, Any]) -> dict[str, str]:
    task_list = str(state.get("source_task_list") or "")
    if not task_list:
        return {}
    path = materialized_task_list_path(root, task_list)
    return {
        "taskListLogical": task_list,
        "taskListMaterialized": path,
        "deliverEntryRef": format_deliver_entry_ref(root, task_list),
        "resumeCommand": format_deliver_run_command(root, task_list),
        "specSeedCommand": format_spec_seed_command(root, task_list),
    }
