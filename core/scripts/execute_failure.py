#!/usr/bin/env python3
"""Execute-tier failure handling — blast-radius and remediation (PRD 053 R18, R20, R21)."""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execute_plan import EXECUTE_PLAN_FILENAME, ref_sort_key, resolve_run_dir
from execute_task_status import status_path as execute_status_path
from intra_phase_dispatch import load_workflow_config
from wave_json_io import read_json, write_json

EXIT_BLOCKED = 20


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def remediation_max_attempts(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    remediation = deliver.get("remediation") or {}
    try:
        return max(0, int(remediation.get("maxAttempts", 2)))
    except (TypeError, ValueError):
        return 2


def load_execute_plan(run_dir: Path) -> dict[str, Any]:
    path = run_dir / EXECUTE_PLAN_FILENAME
    if not path.is_file():
        fail(f"missing execute plan: {path}", exit_code=EXIT_BLOCKED, cause="failure:missing-plan")
    return read_json(path, absent_ok=False)


def persist_execute_plan(run_dir: Path, plan: dict[str, Any]) -> None:
    write_json(run_dir / EXECUTE_PLAN_FILENAME, plan)


def plan_edges(plan: dict[str, Any]) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for edge in plan.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src, dst = edge.get("from"), edge.get("to")
        if isinstance(src, str) and isinstance(dst, str):
            edges.append({"from": src, "to": dst, "kind": str(edge.get("kind") or "")})
    return edges


def transitive_dependent_refs(ref_id: str, edges: list[dict[str, str]]) -> list[str]:
    graph: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        graph[edge["from"]].append(edge["to"])
    seen: set[str] = set()
    queue: deque[str] = deque(graph.get(ref_id, []))
    while queue:
        node = queue.popleft()
        if node in seen:
            continue
        seen.add(node)
        queue.extend(graph.get(node, []))
    return sorted(seen, key=ref_sort_key)


def ref_map(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for ref in plan.get("refs") or []:
        if isinstance(ref, dict) and ref.get("id"):
            out[str(ref["id"])] = ref
    return out


def write_execute_status(root: Path, task_ref: str, payload: dict[str, Any]) -> Path:
    path = execute_status_path(root, task_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {**payload, "taskRef": task_ref, "writtenAt": utc_now()}
    write_json(path, data)
    return path


def integrate_ready_refs(root: Path, run_dir: Path, plan: dict[str, Any], phase_slug: str) -> list[str]:
    """Integrate green refs before blast-radius blocking (R20 partial-batch semantics)."""
    integrated: list[str] = []
    refs = ref_map(plan)
    for ref_id, ref in refs.items():
        status = str(ref.get("status") or "pending")
        if status not in {"green", "complete"}:
            continue
        journal_path = run_dir / "integrate-journal.json"
        already = False
        if journal_path.is_file():
            journal = read_json(journal_path, absent_ok=True)
            for entry in journal.get("entries") or []:
                if isinstance(entry, dict) and str(entry.get("taskRef")) == ref_id and entry.get("verdict") == "pass":
                    already = True
                    break
        if already:
            continue
        import subprocess

        proc = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "execute_integrate.py"),
                str(root),
                "integrate",
                "--task-ref",
                ref_id,
                "--phase-slug",
                phase_slug,
                "--run-dir",
                str(run_dir),
            ],
            cwd=str(root),
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            integrated.append(ref_id)
    return integrated


def cmd_blast_radius_apply(root: Path, args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
    plan = load_execute_plan(run_dir)
    task_ref = args.task_ref
    refs = ref_map(plan)
    if task_ref not in refs:
        fail(f"task ref not in execute plan: {task_ref}", exit_code=EXIT_BLOCKED, cause="failure:unknown-ref")

    integrated = integrate_ready_refs(root, run_dir, plan, args.phase_slug) if args.integrate_ready else []
    plan = load_execute_plan(run_dir)
    refs = ref_map(plan)
    cause = args.cause or "execute:blocked"
    upstream = task_ref
    blocked: list[dict[str, str]] = []

    refs[task_ref]["status"] = "blocked"
    refs[task_ref]["cause"] = cause
    blocked.append({"taskRef": task_ref, "cause": cause})
    write_execute_status(
        root,
        task_ref,
        {"verdict": "blocked", "cause": cause, "phaseSlug": args.phase_slug},
    )

    for dep_ref in transitive_dependent_refs(task_ref, plan_edges(plan)):
        if dep_ref not in refs:
            continue
        if refs[dep_ref].get("status") in {"green", "integrated", "skipped"}:
            continue
        dep_cause = f"blast-radius:upstream-blocked:{upstream}"
        refs[dep_ref]["status"] = "blocked"
        refs[dep_ref]["cause"] = dep_cause
        blocked.append({"taskRef": dep_ref, "cause": dep_cause})
        write_execute_status(
            root,
            dep_ref,
            {"verdict": "blocked", "cause": dep_cause, "phaseSlug": args.phase_slug},
        )

    plan["refs"] = list(refs.values())
    persist_execute_plan(run_dir, plan)
    from execute_ship import memory_safe_failure_report
    safe_report = memory_safe_failure_report(root, {
        "taskRef": task_ref,
        "phaseSlug": args.phase_slug,
        "blockedRefs": blocked,
        "integratedBeforeBlock": integrated,
    })
    emit(
        {
            "verdict": "pass",
            "action": "blast-radius-apply",
            "memorySafeReport": safe_report,
            "taskRef": task_ref,
            "phaseSlug": args.phase_slug,
            "blockedRefs": blocked,
            "integratedBeforeBlock": integrated,
            "runDir": str(run_dir),
        }
    )
    return 0


def cmd_blast_radius_dependents(root: Path, args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
    plan = load_execute_plan(run_dir)
    task_ref = args.task_ref
    deps = transitive_dependent_refs(task_ref, plan_edges(plan))
    emit(
        {
            "verdict": "pass",
            "action": "blast-radius-dependents",
            "taskRef": task_ref,
            "phaseSlug": args.phase_slug,
            "dependentRefs": deps,
        }
    )
    return 0


def cmd_remediation_route(root: Path, args: argparse.Namespace) -> int:
    run_dir = resolve_run_dir(args.phase_slug, args.run_dir)
    plan = load_execute_plan(run_dir)
    task_ref = args.task_ref
    refs = ref_map(plan)
    if task_ref not in refs:
        fail(f"task ref not in execute plan: {task_ref}", exit_code=EXIT_BLOCKED, cause="failure:unknown-ref")

    ref = refs[task_ref]
    attempts = int(ref.get("remediationAttempts") or 0) + 1
    ref["remediationAttempts"] = attempts
    max_attempts = remediation_max_attempts(root)
    plan["refs"] = list(refs.values())
    persist_execute_plan(run_dir, plan)

    if attempts > max_attempts:
        fail(
            "remediation budget exhausted",
            exit_code=EXIT_BLOCKED,
            cause="execute:remediation-exhausted",
            taskRef=task_ref,
            remediationAttempts=attempts,
            maxAttempts=max_attempts,
        )

    branch = str(ref.get("branch") or "")
    route = {
        "command": "/sw-stabilize",
        "scope": "phase-branch",
        "note": f"scoped remediation for execute ref {task_ref}",
    }
    if str(ref.get("cause") or "").startswith("integrate:conflict"):
        route = {
            "command": "/sw-stabilize",
            "scope": "phase-branch",
            "note": "integration conflict remediation",
        }

    emit(
        {
            "verdict": "pass",
            "action": "remediation-route",
            "taskRef": task_ref,
            "phaseSlug": args.phase_slug,
            "remediationAttempts": attempts,
            "maxAttempts": max_attempts,
            "branch": branch,
            "route": route,
        }
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Execute-tier failure handling (PRD 053)")
    sub = parser.add_subparsers(dest="command", required=True)

    apply = sub.add_parser("blast-radius")
    apply_sub = apply.add_subparsers(dest="blast_cmd", required=True)
    apply_cmd = apply_sub.add_parser("apply")
    apply_cmd.add_argument("--task-ref", required=True)
    apply_cmd.add_argument("--phase-slug", required=True)
    apply_cmd.add_argument("--run-dir", default="")
    apply_cmd.add_argument("--cause", default="")
    apply_cmd.add_argument("--integrate-ready", action="store_true")
    deps_cmd = apply_sub.add_parser("dependents")
    deps_cmd.add_argument("--task-ref", required=True)
    deps_cmd.add_argument("--phase-slug", required=True)
    deps_cmd.add_argument("--run-dir", default="")

    route = sub.add_parser("remediation")
    route_sub = route.add_subparsers(dest="remediation_cmd", required=True)
    route_cmd = route_sub.add_parser("route")
    route_cmd.add_argument("--task-ref", required=True)
    route_cmd.add_argument("--phase-slug", required=True)
    route_cmd.add_argument("--run-dir", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        fail("usage: execute_failure.py <root> <command> [args]")
    root = Path(argv[0])
    args = build_parser().parse_args(argv[1:])
    if args.command == "blast-radius":
        if args.blast_cmd == "apply":
            return cmd_blast_radius_apply(root, args)
        if args.blast_cmd == "dependents":
            return cmd_blast_radius_dependents(root, args)
    if args.command == "remediation" and args.remediation_cmd == "route":
        return cmd_remediation_route(root, args)
    fail(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
