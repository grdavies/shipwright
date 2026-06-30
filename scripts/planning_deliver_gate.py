#!/usr/bin/env python3
"""Unit-level dependency gate, scheduler next, and run-start revalidation (PRD 033 R7-R9, R20, R28)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_graph as pg
import planning_paths as pp

RUN_START_INELIGIBLE = frozenset({"superseded", "cancelled"})
SOFT_ENFORCE_EXIT = 30
GATE_FAIL_EXIT = 20


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = GATE_FAIL_EXIT, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def actor_id() -> str:
    return os.environ.get("SW_RECOVERY_ACTOR") or os.environ.get("USER") or "operator"


def planning_autonomy(root: Path) -> str:
    cfg = pp.load_workflow_config(root)
    raw = (cfg.get("planning") or {}).get("autonomy")
    if raw in ("maintenance-only", "full-conductor"):
        return str(raw)
    return "maintenance-only"


def unit_id_from_task_list(task_path: Path) -> str:
    parent = task_path.parent.name
    if parent.startswith("prd-"):
        return parent
    return f"prd-{parent}"


def task_list_for_unit(root: Path, unit_id: str) -> str | None:
    dirs = pp.load_planning_dirs(root)
    worktree = pp.git_root(root)
    slug = unit_id[4:] if unit_id.startswith("prd-") else unit_id
    candidates = [
        pp.join_rel(dirs.prds, unit_id, f"tasks-{unit_id}.md"),
        pp.join_rel(dirs.prds, slug, f"tasks-{slug}.md"),
        pp.join_rel(dirs.prds, slug, f"tasks-{unit_id}.md"),
        pp.join_rel(dirs.planning, "prd", unit_id, f"tasks-{slug}.md"),
        pp.join_rel(dirs.planning, "prd", unit_id, f"tasks-{unit_id}.md"),
    ]
    for rel in candidates:
        path = worktree / rel
        if path.is_file():
            return rel
    return None


def units_with_derived_status(root: Path) -> tuple[list[pg.GraphUnit], dict[str, pg.GraphUnit]]:
    from inflight_signal import read_tuples
    from planning_reconcile import build_derived_map, git_complete_unit_ids

    units = pg.discover_units(root)
    inflight = read_tuples(root)
    git_complete = git_complete_unit_ids(root, units)
    derived = build_derived_map(units, inflight, git_complete)
    overlaid: list[pg.GraphUnit] = []
    for unit in units:
        status = derived.get(unit.id, unit.status)
        overlaid.append(
            pg.GraphUnit(
                id=unit.id,
                unit_type=unit.unit_type,
                status=status,
                priority=unit.priority,
                depends=unit.depends,
                blocks=unit.blocks,
                supersedes=unit.supersedes,
                extends=unit.extends,
                absorbs=unit.absorbs,
                source_path=unit.source_path,
            )
        )
    by_id = pg.index_units(overlaid)
    return overlaid, by_id


def resolve_unit(root: Path, task_path: Path) -> pg.GraphUnit | None:
    unit_id = unit_id_from_task_list(task_path)
    _, by_id = units_with_derived_status(root)
    return by_id.get(unit_id)


def parse_gate_flags(args: list[str]) -> dict[str, Any]:
    override = "--override" in args
    reason = None
    if "--override-reason" in args:
        i = args.index("--override-reason")
        reason = args[i + 1] if i + 1 < len(args) else None
    confirmed = "--confirmed" in args
    return {"override": override, "override_reason": reason, "confirmed": confirmed}


def log_dependency_override(root: Path, *, unit_id: str, task_list: str, blocking_units: list[str], reason: str) -> None:
    payload = {
        "kind": "dependency-gate",
        "who": actor_id(),
        "when": utc_now(),
        "why": reason,
        "unitId": unit_id,
        "taskList": task_list,
        "blockingUnits": blocking_units,
    }
    proc = subprocess.run(
        ["bash", str(SCRIPT_DIR / "shipwright-state.py"), "override-add", json.dumps(payload)],
        cwd=str(root), text=True, capture_output=True,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "override-add failed", exit_code=20)
    cursor = root / ".cursor"
    if not cursor.is_dir():
        return
    for path in cursor.glob("sw-deliver-state*.json"):
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        log = state.setdefault("dependencyGateOverrides", [])
        if not isinstance(log, list):
            log = []
        log.append(payload)
        state["dependencyGateOverrides"] = log[-50:]
        path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def dependency_gate(root: Path, task_path: Path, *, override: bool = False, override_reason: str | None = None) -> dict[str, Any]:
    unit = resolve_unit(root, task_path)
    unit_id = unit_id_from_task_list(task_path)
    if unit is None:
        return {"verdict": "pass", "action": "dependency-gate", "unitId": unit_id, "note": "unit-not-in-graph"}
    _, by_id = units_with_derived_status(root)
    blocking = pg.unmet_dependencies(unit, by_id)
    if not blocking:
        return {"verdict": "pass", "action": "dependency-gate", "unitId": unit.id}
    if override:
        if not override_reason or not str(override_reason).strip():
            fail("--override requires --override-reason", halt="dependency-gate", blockingUnits=blocking)
        rel = str(task_path)
        try:
            rel = str(task_path.relative_to(pp.git_root(root)))
        except ValueError:
            pass
        log_dependency_override(root, unit_id=unit.id, task_list=rel, blocking_units=blocking, reason=str(override_reason).strip())
        return {"verdict": "pass", "action": "dependency-gate", "unitId": unit.id, "override": True, "blockingUnits": blocking}
    fail("unmet depends prerequisites", halt="dependency-gate", blockingUnits=blocking, unitId=unit.id)


def run_start_revalidate(root: Path, task_path: Path) -> dict[str, Any]:
    unit = resolve_unit(root, task_path)
    unit_id = unit_id_from_task_list(task_path)
    if unit is None:
        return {"verdict": "pass", "action": "run-start-revalidate", "unitId": unit_id, "note": "unit-not-in-graph"}
    if unit.status in RUN_START_INELIGIBLE:
        fail(f"unit {unit.id} is {unit.status} at run-start", halt="run-start-ineligible", unitId=unit.id, status=unit.status)
    _, by_id = units_with_derived_status(root)
    if not pg.is_eligible(unit, by_id):
        fail("unit ineligible at run-start", halt="dependency-gate", unitId=unit.id, blockingUnits=pg.unmet_dependencies(unit, by_id))
    return {"verdict": "pass", "action": "run-start-revalidate", "unitId": unit.id, "status": unit.status}


def soft_enforce_confirm(root: Path, task_path: Path, *, confirmed: bool = False) -> dict[str, Any] | None:
    if planning_autonomy(root) != "maintenance-only":
        return None
    unit = resolve_unit(root, task_path)
    if unit is None:
        return None
    eligible = pg.order_eligible(units_with_derived_status(root)[0])
    if not eligible:
        return None
    top = eligible[0]
    if top == unit.id:
        return None
    if confirmed:
        return {"verdict": "pass", "action": "soft-enforce", "confirmed": True, "selectedUnit": unit.id, "higherPriorityUnit": top}
    emit({
        "verdict": "confirm", "action": "soft-enforce", "posture": "maintenance-only",
        "selectedUnit": unit.id, "higherPriorityUnit": top,
        "message": f"Higher-priority eligible unit {top!r} exists; confirm proceeding with {unit.id!r} or rerun with --confirmed",
    }, exit_code=SOFT_ENFORCE_EXIT)


def cmd_next(root: Path, args: list[str]) -> None:
    flags = parse_gate_flags(args)
    eligible = pg.order_eligible(units_with_derived_status(root)[0])
    if not eligible:
        fail("no eligible planning units", halt="scheduler-empty")
    unit_id = eligible[0]
    task_rel = task_list_for_unit(root, unit_id)
    if not task_rel:
        fail(f"no frozen task list for unit {unit_id}", unitId=unit_id)
    task_path = pp.resolve_contained(root, task_rel)
    content = task_path.read_text(encoding="utf-8")
    if "frozen: true" not in content:
        fail(f"task list not frozen for {unit_id}", taskList=task_rel)
    run_start_revalidate(root, task_path)
    dependency_gate(root, task_path, override=bool(flags["override"]), override_reason=flags["override_reason"])
    emit({"verdict": "pass", "action": "next", "unitId": unit_id, "taskList": task_rel, "eligible": eligible})


def cmd_dependency_gate(root: Path, args: list[str]) -> None:
    if not args:
        fail("usage: dependency-gate <subcommand> --task-list <path> ...")
    sub, rest = args[0], args[1:]
    task_list = None
    if "--task-list" in rest:
        i = rest.index("--task-list")
        task_list = rest[i + 1] if i + 1 < len(rest) else None
    if not task_list:
        fail("--task-list required")
    task_path = pp.resolve_contained(root, task_list)
    flags = parse_gate_flags(rest)
    if sub == "preflight":
        gate_out = dependency_gate(
            root,
            task_path,
            override=bool(flags["override"]),
            override_reason=flags["override_reason"],
        )
        if not gate_out.get("override"):
            soft_enforce_confirm(root, task_path, confirmed=bool(flags["confirmed"]))
        emit({"verdict": "pass", "action": "dependency-gate-preflight", "taskList": task_list})
    elif sub == "run-start":
        run_start_revalidate(root, task_path)
        dependency_gate(root, task_path, override=bool(flags["override"]), override_reason=flags["override_reason"])
        emit({"verdict": "pass", "action": "run-start-revalidate", "taskList": task_list})
    else:
        fail(f"unknown dependency-gate subcommand: {sub}")


def list_dependency_override_drift(root: Path) -> list[dict[str, Any]]:
    drift: list[dict[str, Any]] = []
    cursor = root / ".cursor"
    if cursor.is_dir():
        for path in cursor.glob("sw-deliver-state*.json"):
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            for entry in state.get("dependencyGateOverrides") or []:
                if isinstance(entry, dict):
                    drift.append(entry)
    shipwright = root / ".git" / "shipwright.json"
    if shipwright.is_file():
        try:
            data = json.loads(shipwright.read_text(encoding="utf-8"))
            for entry in data.get("overrides") or []:
                if isinstance(entry, dict) and entry.get("kind") == "dependency-gate":
                    drift.append(entry)
        except (OSError, json.JSONDecodeError):
            pass
    return drift[-20:]


def main(argv: list[str] | None = None) -> None:
    args = list(argv if argv is not None else sys.argv[1:])
    if len(args) < 2:
        fail("usage: planning_deliver_gate.py <repo-root> <command> ...")
    root = Path(args[0]).resolve()
    command, rest = args[1], args[2:]
    if command == "next":
        cmd_next(root, rest)
    elif command == "dependency-gate":
        cmd_dependency_gate(root, rest)
    elif command == "override-drift":
        emit({"verdict": "pass", "drift": list_dependency_override_drift(root)})
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
