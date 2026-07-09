#!/usr/bin/env python3
"""Unified planning-unit status surface and deliver entry reference helpers (PRD 059 R1-R4)."""

from __future__ import annotations

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
from issues_lib import IssueBudgetExhausted, IssueCapabilityError, IssueNotFound, IssuesClient  # noqa: E402
from planning_deliver_gate import task_list_for_unit  # noqa: E402
from planning_store import get_backend, resolve_effective_backend, validate_project_key  # noqa: E402

UNIFIED_STATUSES = frozenset({"backlog", "planned", "in-progress", "complete", "unauthorized", "unknown"})

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


def query_unit_status(root: Path, *, unit_id: str | None = None, issue: str | None = None) -> dict[str, Any]:
    resolved_id, issue_ref = resolve_unit_reference(root, unit_id=unit_id, issue=issue)
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
        "nativeStatus": unit.status,
    }
    if issue_ref:
        out["issue"] = issue_ref
    return out


def task_list_for_unit_candidates(root: Path, unit_id: str) -> list[str]:
    from planning_deliver_gate import logical_task_list_candidates

    return logical_task_list_candidates(root, unit_id)


def _normalize_issue_ref(raw: str) -> str:
    return raw.strip().lstrip("#")


def resolve_unit_reference(
    root: Path,
    *,
    unit_id: str | None = None,
    issue: str | None = None,
) -> tuple[str, str | None]:
    if unit_id and issue:
        fail("provide only one of --unit-id or --issue", exit_code=2, halt="disambiguation")
    if issue:
        issue_ref = _normalize_issue_ref(issue)
        record = _lookup_issue_record(root, issue_ref)
        uid = str(record.unit_id or "").strip()
        if not uid:
            fail(f"issue {issue_ref!r} has no sw-unit-id marker", exit_code=2, issue=issue_ref)
        return uid, issue_ref
    if unit_id:
        return unit_id.strip(), None
    fail("unit reference required: --unit-id or --issue", exit_code=2)


def _lookup_issue_record(root: Path, issue_ref: str):
    cfg = load_workflow_config(root)
    effective = resolve_effective_backend(root, cfg)
    if effective.get("effective") != "issue-store":
        fail(
            "--issue requires issue-store effective backend",
            exit_code=2,
            effectiveBackend=effective.get("effective"),
        )
    key_result = validate_project_key(root, cfg)
    if key_result.get("verdict") != "ok":
        fail(key_result.get("message") or "invalid project key", exit_code=2)
    from planning_store import resolve_issues_provider

    provider = str(resolve_issues_provider(cfg).get("provider", "none"))
    client = IssuesClient(root, provider)
    try:
        return client.issue_get(issue_ref)
    except IssueNotFound:
        fail(
            f"issue {issue_ref!r} not found or outside project scope",
            exit_code=2,
            issue=issue_ref,
            remediation="verify issue number belongs to the configured planning project",
        )


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
    if unit_id or issue:
        uid, _issue_ref = resolve_unit_reference(root, unit_id=unit_id, issue=issue)
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
    from planning_store import resolve_issues_provider

    provider = str(resolve_issues_provider(cfg).get("provider", "none"))
    client = IssuesClient(root, provider)
    try:
        matches = client.issue_search(
            project_key=str(key_result["projectKey"]),
            unit_id=unit_id,
        )
    except (IssueCapabilityError, IssueBudgetExhausted, RuntimeError):
        return None
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
