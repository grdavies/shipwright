#!/usr/bin/env python3
"""Issue-label-driven planning scheduler for /sw-deliver next (PRD 046 R25, D24)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_graph as pg  # noqa: E402
import planning_index_gen as pig  # noqa: E402
import planning_park as park  # noqa: E402
import planning_paths as pp  # noqa: E402
from host_lib import load_workflow_config  # noqa: E402
from issues_lib import IssuesClient, use_fixture_mode  # noqa: E402
from planning_canonical import GAP_LABEL_RESOLVED  # noqa: E402
from planning_discover import (  # noqa: E402
    filter_units_by_source,
    resolve_discover_source,
    resolve_source_scope,
)
from planning_query_cache import get_entry, invalidate_all, revalidate_live_metadata, resolve_ttl  # noqa: E402
from planning_request_budget import RequestBudgetLedger  # noqa: E402
from planning_store import validate_project_key  # noqa: E402

_TIER_LABEL = re.compile(r"^sw:tier:(?P<tier>[A-Za-z]+)$")
_PRIORITY_LABEL = re.compile(r"^sw:priority:(?P<priority>-?\d+)$")
_FROZEN_LABELS = frozenset({"sw:frozen", "sw:freeze-incomplete"})
_TERMINAL_LABELS = frozenset({"sw:gap-resolved", "resolved"})


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 20, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def index_incomplete(root: Path) -> tuple[bool, str]:
    state = pig.read_generation_state(root)
    if state.get("indexIncomplete"):
        return True, str(state.get("indexIncompleteReason", "index-incomplete"))
    return False, ""




def priority_from_labels(labels: list[str], default: int = 0) -> int:
    for label in labels:
        m = _PRIORITY_LABEL.match(label)
        if m:
            return int(m.group("priority"))
    return default


def tier_rank(labels: list[str]) -> int:
    order = {"critical": 4, "high": 3, "medium": 2, "low": 1}
    for label in labels:
        m = _TIER_LABEL.match(label)
        if m:
            return order.get(m.group("tier").lower(), 0)
    return 0


def unit_labels_from_issue_path(body_path: str, client: IssuesClient) -> list[str]:
    if not body_path.startswith("issue:"):
        return []
    issue_id = body_path.split(":", 1)[1]
    try:
        record = client.issue_get(issue_id)
    except Exception:
        return []
    return list(record.labels)


def is_schedulable(unit: pg.GraphUnit, labels: list[str]) -> bool:
    """Frontier eligibility for a unit given its provider-native labels.

    Drops frozen/terminal units and units carrying the ``sw:parked`` label so
    parked legacy units (e.g. ``003-prd-pr-agent-review-provider``) fall out of
    the issue-store frontier (R16, D4).
    """
    label_set = set(labels)
    if label_set & _FROZEN_LABELS:
        return False
    if park.is_parked_label(label_set):
        return False
    if unit.status in {"complete", "resolved", "cancelled", "superseded"}:
        return False
    return True


def runnable_task_list(root: Path, unit_id: str) -> str | None:
    from planning_deliver_gate import task_list_for_unit

    return task_list_for_unit(root, unit_id)


def schedule_next(
    root: Path,
    *,
    force_refresh: bool = False,
    source_scope: list[str] | None = None,
) -> dict[str, Any]:
    incomplete, reason = index_incomplete(root)
    if incomplete:
        fail(reason or "index-incomplete", exit_code=20, indexIncomplete=True)

    worktree = pp.git_root(root)
    parked = park.load_parked(root)
    # PRD 057 R12 -- an explicit `--source` override wins for this invocation;
    # otherwise fall back to the committed/env scope (empty = every source).
    scope = source_scope if source_scope is not None else resolve_source_scope(root)
    if resolve_discover_source(root) != "issue":
        units = filter_units_by_source(pg.discover_units(root), scope)
        graph_eligible = pg.order_eligible(units)
        eligible: list[str] = []
        skipped: list[dict[str, Any]] = []
        for unit_id in graph_eligible:
            park_entry = parked.get(unit_id)
            if park_entry:
                skipped.append(park.parked_skip_record(unit_id, park_entry))
                continue
            task_list = runnable_task_list(root, unit_id)
            if not task_list:
                skipped.append({"unitId": unit_id, "reason": "no-frozen-task-list"})
                continue
            eligible.append(unit_id)
        if not eligible and skipped:
            # Frontier non-empty but fully parked/unrunnable → explicit halt (R28).
            emit(
                park.scheduler_exhausted_payload(source="file", eligible=graph_eligible, skipped=skipped),
                park.SCHEDULER_EXHAUSTED_EXIT,
            )
        nxt = eligible[0] if eligible else None
        payload: dict[str, Any] = {"verdict": "pass", "action": "schedule-next", "source": "file", "next": nxt, "eligible": eligible}
        if scope:
            payload["sourceScope"] = scope
        if skipped:
            payload["skipped"] = skipped
        if nxt:
            task_list = runnable_task_list(root, nxt)
            if task_list:
                payload["taskList"] = task_list
        return payload

    cfg = load_workflow_config(worktree)
    key_result = validate_project_key(worktree, cfg)
    if key_result.get("verdict") != "ok":
        fail("invalid project key for issue-store scheduler")
    project_key = str(key_result["projectKey"])
    store = (cfg.get("planning") or {}).get("store") or {}
    provider = str(store.get("issuesProvider", "none"))
    client = IssuesClient(worktree, provider)
    ledger = RequestBudgetLedger.from_config(root, provider)
    ledger.charge("scheduler-revalidate", critical=True)

    if not force_refresh:
        entry = get_entry(root, project_key=project_key, ttl_seconds=resolve_ttl(root, provider))
        if entry and not revalidate_live_metadata(root, client, entry):
            invalidate_all(root)

    units = filter_units_by_source(pg.discover_units(root), scope)
    by_id = pg.index_units(units)
    scored: list[tuple[int, int, str]] = []
    skipped = []
    graph_eligible_ids: list[str] = []
    for unit in by_id.values():
        if not pg.is_eligible(unit, by_id):
            continue
        graph_eligible_ids.append(unit.id)
        labels = unit_labels_from_issue_path(unit.source_path, client)
        park_entry = parked.get(unit.id)
        if park_entry or park.is_parked_label(labels):
            skipped.append({
                "unitId": unit.id,
                "reason": "parked",
                "parkReason": (park_entry or {}).get("reason") if park_entry else "sw:parked",
                "parkedBy": (park_entry or {}).get("actor") if park_entry else None,
            })
            continue
        if not is_schedulable(unit, labels):
            continue
        if not runnable_task_list(root, unit.id):
            skipped.append({"unitId": unit.id, "reason": "no-frozen-task-list"})
            continue
        scored.append((tier_rank(labels), unit.priority + priority_from_labels(labels), unit.id))
    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    eligible = [row[2] for row in scored]
    if not eligible and skipped:
        # Frontier non-empty but fully parked/unrunnable → explicit halt (R28).
        emit(
            {
                **park.scheduler_exhausted_payload(source="issue", eligible=graph_eligible_ids, skipped=skipped),
                "ledger": ledger.snapshot(),
            },
            park.SCHEDULER_EXHAUSTED_EXIT,
        )
    nxt = eligible[0] if eligible else None
    payload = {"verdict": "pass", "action": "schedule-next", "source": "issue", "next": nxt, "eligible": eligible, "ledger": ledger.snapshot()}
    if scope:
        payload["sourceScope"] = scope
    if skipped:
        payload["skipped"] = skipped
    if nxt:
        task_list = runnable_task_list(root, nxt)
        if task_list:
            payload["taskList"] = task_list
    return payload


def cmd_next(root: Path, args: list[str]) -> None:
    source_scope = None
    if "--source" in args:
        idx = args.index("--source")
        raw = args[idx + 1] if idx + 1 < len(args) else ""
        source_scope = [s.strip() for s in raw.split(",") if s.strip()]
    emit(schedule_next(root, force_refresh="--force-refresh" in args, source_scope=source_scope))


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_scheduler.py <repo-root> next")
    root = Path(args[0]).resolve()
    if args[1] == "next":
        cmd_next(root, args[2:])
    else:
        fail(f"unknown command: {args[1]}")


if __name__ == "__main__":
    main()
