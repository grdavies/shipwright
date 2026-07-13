#!/usr/bin/env python3
"""Unit-level dependency gate, scheduler next, and run-start revalidation (PRD 033 R7-R9, R20, R28)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import planning_graph as pg
import planning_park as park
import planning_paths as pp

PRD_064_UNIT_ID = "064-prd-agentic-quality-patterns-and-standards-conformance"
HARD_DELIVER_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "065-prd-turn-independent-ship-loop-and-gate-evidence": (
        PRD_064_UNIT_ID,
    ),
}


def hard_prerequisite_units(unit_id: str) -> tuple[str, ...]:
    return HARD_DELIVER_PREREQUISITES.get(unit_id, ())


def unmet_hard_prerequisites(
    root: Path,
    unit_id: str,
    by_id: dict[str, pg.GraphUnit],
) -> list[str]:
    from planning_reconcile import resolve_git_complete_unit_ids

    blocking: list[str] = []
    git_complete = resolve_git_complete_unit_ids(root, list(by_id.values()))
    for prereq in hard_prerequisite_units(unit_id):
        if prereq in git_complete:
            continue
        dep = by_id.get(prereq)
        if dep and dep.status in pg.SATISFIED_STATUSES:
            continue
        blocking.append(prereq)
    return blocking



RUN_START_INELIGIBLE = frozenset({"superseded", "cancelled"})
SOFT_ENFORCE_EXIT = 30
GATE_FAIL_EXIT = 20
CANONICAL_PRDS_TASK_LIST = re.compile(r"^docs/prds/\d+-[^/]+/tasks-[^/]+\.md$")

HARNESS_FIXTURE_TASK_LIST = re.compile(r"^scripts/test/fixtures/.+/tasks-[^/]+\.md$")


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
    """Derive the PRD-level graph unit id that owns this task list directory (gap-051)."""
    rel = str(task_path).replace("\\", "/")
    marker = ".cursor/planning-materialized/"
    if marker in rel:
        rel = rel.split(marker, 1)[1]
    parent = Path(rel).parent.name
    if parent.startswith("prd-"):
        return parent
    if re.match(r"^\d+-prd-", parent):
        return parent
    match = re.match(r"^(\d+)-(.+)$", parent)
    if match:
        return f"{match.group(1)}-prd-{match.group(2)}"
    return f"prd-{parent}"


def task_list_rel(root: Path, task_path: Path) -> str:
    try:
        return str(task_path.relative_to(pp.git_root(root))).replace("\\", "/")
    except ValueError:
        return str(task_path).replace("\\", "/")


def is_canonical_prds_task_list(task_rel: str) -> bool:
    """True when the task list sits under docs/prds/<n>-<slug>/ (PRD 058 R5)."""
    return bool(CANONICAL_PRDS_TASK_LIST.match(task_rel.replace("\\", "/")))


def is_harness_fixture_task_list(task_rel: str) -> bool:
    """Hermetic harness fixtures under scripts/test/fixtures/ (gap-051 R5 allowlist)."""
    return bool(HARNESS_FIXTURE_TASK_LIST.match(task_rel.replace("\\", "/")))


def allowlist_unit_absent_from_graph(task_path: Path, task_rel: str) -> bool:
    """Documented allowlist for unit-not-in-graph pass (gap-051 R5).

    A task list on the canonical docs/prds/<n>-<slug>/ layout that is not yet
    frozen may legitimately be absent from the planning graph during spec seeding.
    """
    if is_harness_fixture_task_list(task_rel):
        return True
    if not is_canonical_prds_task_list(task_rel):
        return False
    if not task_path.is_file():
        return False
    try:
        content = task_path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "frozen: true" not in content


def handle_unit_not_in_graph(root: Path, task_path: Path, *, action: str) -> dict[str, Any]:
    """Fail closed on unknown layout; allowlist only pre-freeze canonical paths (gap-051 R5)."""
    unit_id = unit_id_from_task_list(task_path)
    rel = task_list_rel(root, task_path)
    if allowlist_unit_absent_from_graph(task_path, rel):
        return {
            "verdict": "pass",
            "action": action,
            "unitId": unit_id,
            "note": "unit-not-in-graph-allowlisted",
            "taskList": rel,
        }
    fail(
        "task list unit not found in planning graph",
        halt="dependency-gate",
        unitId=unit_id,
        taskList=rel,
        cause="unknown-layout-or-unmapped-unit",
    )


def task_list_for_unit(root: Path, unit_id: str) -> str | None:
    worktree = pp.git_root(root)
    candidates = logical_task_list_candidates(root, unit_id)
    for rel in candidates:
        path = worktree / rel
        if path.is_file():
            return rel
    from host_lib import load_workflow_config
    from planning_store import get_backend, resolve_effective_backend

    cfg = load_workflow_config(worktree)
    if resolve_effective_backend(worktree, cfg).get("effective") != "issue-store":
        return None
    backend = get_backend(worktree, cfg)
    for rel in candidates:
        task_unit = Path(rel).stem
        exists = backend.exists(task_unit, rel)
        if exists.verdict == "ok":
            return rel
    return None


TASK_LIST_STORE_UNIT_ID = re.compile(r"^tasks-(\d+)-(.+)$")


def task_list_path_parts(unit_id: str) -> tuple[str, str]:
    """Return (directory_slug, task_filename) for logical task-list paths (gap-114)."""
    uid = unit_id.strip()
    tasks_match = TASK_LIST_STORE_UNIT_ID.match(uid)
    if tasks_match:
        dir_slug = f"{tasks_match.group(1)}-{tasks_match.group(2)}"
        return dir_slug, f"{uid}.md"
    prd_match = re.match(r"^(\d+)-prd-(.+)$", uid)
    if prd_match:
        dir_slug = f"{prd_match.group(1)}-{prd_match.group(2)}"
        return dir_slug, f"tasks-{dir_slug}.md"
    if uid.startswith("prd-"):
        slug = uid[4:]
        return slug, f"tasks-{uid}.md"
    return uid, f"tasks-{uid}.md"


def logical_task_list_candidates(root: Path, unit_id: str) -> list[str]:
    dirs = pp.load_planning_dirs(root)
    dir_slug, task_file = task_list_path_parts(unit_id)
    seen: set[str] = set()
    out: list[str] = []
    rels = [
        pp.join_rel(dirs.prds, dir_slug, task_file),
        pp.join_rel(dirs.prds, unit_id, task_file),
        pp.join_rel(dirs.planning, "prd", unit_id, task_file),
        pp.join_rel(dirs.planning, "prd", dir_slug, task_file),
    ]
    if not TASK_LIST_STORE_UNIT_ID.match(unit_id.strip()):
        rels.insert(2, pp.join_rel(dirs.prds, dir_slug, f"tasks-{unit_id}.md"))
    for rel in rels:
        if rel not in seen:
            seen.add(rel)
            out.append(rel)
    return out


def resolve_task_list_path(root: Path, task_rel: str) -> Path:
    import planning_materialize as pm
    import planning_path_redirect as ppr

    pm.ensure_run_entry_materialized(root, task_rel)
    _resolved_rel, path = ppr.resolve_readable_path(root, task_rel)
    if path is None:
        fail(f"task list not found: {task_rel}")
    return path


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
        [sys.executable, str(SCRIPT_DIR / "shipwright-state.py"), "override-add", json.dumps(payload)],
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
    if unit is None:
        return handle_unit_not_in_graph(root, task_path, action="dependency-gate")
    _, by_id = units_with_derived_status(root)
    blocking = list(pg.unmet_dependencies(unit, by_id))
    hard = unmet_hard_prerequisites(root, unit.id, by_id)
    for prereq in hard:
        if prereq not in blocking:
            blocking.append(prereq)
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
    if unit is None:
        return handle_unit_not_in_graph(root, task_path, action="run-start-revalidate")
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


def unit_runnable_or_skip(root: Path, unit_id: str) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve a runnable frozen task list for a unit or a skip-with-reason record (R16).

    Returns ``(task_rel, None)`` when the unit has a frozen, resolvable task list;
    otherwise ``(None, skip_record)`` naming why the unit is unrunnable so the
    frontier can skip it instead of failing the whole scheduler.
    """
    task_rel = task_list_for_unit(root, unit_id)
    if not task_rel:
        return None, {"unitId": unit_id, "reason": "no-frozen-task-list"}
    try:
        task_path = resolve_task_list_path(root, task_rel)
    except SystemExit:
        return None, {"unitId": unit_id, "reason": "task-list-unresolvable", "taskList": task_rel}
    try:
        content = task_path.read_text(encoding="utf-8")
    except OSError:
        return None, {"unitId": unit_id, "reason": "task-list-unreadable", "taskList": task_rel}
    if "frozen: true" not in content:
        return None, {"unitId": unit_id, "reason": "task-list-not-frozen", "taskList": task_rel}
    return task_rel, None


def scan_frontier(root: Path, eligible: list[str], parked: dict[str, Any]) -> tuple[str | None, str | None, list[dict[str, Any]]]:
    """Skip parked/unrunnable units with reasons; return first runnable + skips (R16/R28)."""
    skipped: list[dict[str, Any]] = []
    for unit_id in eligible:
        park_entry = parked.get(unit_id)
        if park_entry:
            skipped.append(park.parked_skip_record(unit_id, park_entry))
            continue
        task_rel, skip = unit_runnable_or_skip(root, unit_id)
        if skip is not None:
            skipped.append(skip)
            continue
        return unit_id, task_rel, skipped
    return None, None, skipped


def cmd_next(root: Path, args: list[str]) -> None:
    flags = parse_gate_flags(args)
    eligible = pg.order_eligible(units_with_derived_status(root)[0])
    if not eligible:
        fail("no eligible planning units", halt="scheduler-empty")
    parked = park.load_parked(root)
    unit_id, task_rel, skipped = scan_frontier(root, eligible, parked)
    if unit_id is None or task_rel is None:
        # Distinct scheduler-exhausted halt (R28): the frontier is non-empty but
        # every eligible unit is parked or unrunnable — never a silent empty pass.
        emit(
            park.scheduler_exhausted_payload(source="file", eligible=eligible, skipped=skipped),
            park.SCHEDULER_EXHAUSTED_EXIT,
        )
    task_path = resolve_task_list_path(root, task_rel)
    run_start_revalidate(root, task_path)
    dependency_gate(root, task_path, override=bool(flags["override"]), override_reason=flags["override_reason"])
    payload = {"verdict": "pass", "action": "next", "unitId": unit_id, "taskList": task_rel, "eligible": eligible}
    if skipped:
        payload["skipped"] = skipped
    emit(payload)


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
    task_path = resolve_task_list_path(root, task_list)
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
