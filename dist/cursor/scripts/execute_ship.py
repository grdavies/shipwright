#!/usr/bin/env python3
"""Execute-tier ship-chain gate, autonomy selectors, resume, and metrics (PRD 053 R22-R30)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from execute_plan import (
    EXECUTE_PLAN_FILENAME,
    load_execute_config,
    parse_executable_subtasks,
    ref_sort_key,
    resolve_run_dir,
)
from execute_task_status import status_path as execute_status_path
from intra_phase_dispatch import load_workflow_config
from kernel_classification import normalize_step
from wave_deliver import resolve_task_list_path
from wave_json_io import read_json, write_json

TERMINAL_REF_STATUSES = frozenset({"green", "integrated", "skipped"})
BLOCKING_REF_STATUSES = frozenset({"blocked", "failed"})
EXIT_GATE = 20


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def deliver_autonomy_mode(root: Path) -> str:
    deliver = load_workflow_config(root).get("deliver") or {}
    autonomy = deliver.get("autonomy") or {}
    mode = str(autonomy.get("mode") or "autonomous").strip().lower()
    return mode if mode in ("autonomous", "supervised") else "autonomous"


def executable_subtask_count(root: Path, task_list: str, phase_id: str) -> int:
    task_path = resolve_task_list_path(root, task_list)
    content = task_path.read_text(encoding="utf-8")
    return len(parse_executable_subtasks(content, phase_id))


def execute_tier_active(root: Path, task_list: str | None, phase_id: str) -> bool:
    if not task_list:
        return False
    cfg = load_execute_config(root)
    if not cfg.get("enabled", True):
        return False
    return executable_subtask_count(root, task_list, phase_id) >= 2


def load_execute_plan(run_dir: Path) -> dict[str, Any] | None:
    path = run_dir / EXECUTE_PLAN_FILENAME
    if not path.is_file():
        return None
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def per_ref_status(root: Path, ref_id: str) -> dict[str, Any] | None:
    path = execute_status_path(root, ref_id)
    if not path.is_file():
        return None
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def sync_ref_statuses(root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    refs = []
    for ref in plan.get("refs") or []:
        if not isinstance(ref, dict) or not ref.get("id"):
            continue
        entry = dict(ref)
        ref_id = str(entry["id"])
        disk = per_ref_status(root, ref_id)
        if disk:
            verdict = str(disk.get("verdict") or "")
            if verdict in ("pass", "green"):
                entry["status"] = "green"
            elif verdict in BLOCKING_REF_STATUSES or verdict == "blocked":
                entry["status"] = "blocked"
                entry["cause"] = disk.get("cause")
            elif verdict == "skipped":
                entry["status"] = "skipped"
            elif verdict:
                entry["status"] = verdict
        refs.append(entry)
    plan = dict(plan)
    plan["refs"] = refs
    return plan


def ref_terminal_status(ref: dict[str, Any]) -> str:
    return str(ref.get("status") or "pending")


def all_refs_terminal(plan: dict[str, Any]) -> tuple[bool, list[str]]:
    pending: list[str] = []
    for ref in plan.get("refs") or []:
        if not isinstance(ref, dict):
            continue
        ref_id = str(ref.get("id") or "")
        status = ref_terminal_status(ref)
        if status not in TERMINAL_REF_STATUSES:
            pending.append(ref_id)
    return not pending, sorted(pending, key=ref_sort_key)


def ship_verify_gate_ok(root: Path, run_dir: Path, *, task_list: str | None = None, phase_id: str = "") -> dict[str, Any]:
    plan = load_execute_plan(run_dir)
    if plan is None:
        if task_list and phase_id and execute_tier_active(root, task_list, phase_id):
            return {
                "verdict": "blocked",
                "halt": "execute:missing-plan",
                "cause": "execute-plan-missing",
                "pendingRefs": [],
            }
        return {"verdict": "pass", "gate": "execute-tier-inactive"}

    plan = sync_ref_statuses(root, plan)
    ok, pending = all_refs_terminal(plan)
    if ok:
        return {"verdict": "pass", "gate": "execute-refs-terminal", "refCount": len(plan.get("refs") or [])}
    return {
        "verdict": "blocked",
        "halt": "execute:refs-not-terminal",
        "cause": "execute-refs-not-terminal",
        "pendingRefs": pending,
        "runDir": str(run_dir),
    }


def adapt_phase_plan_for_execute_tier(root: Path, plan: dict[str, Any], *, task_list: str | None, phase_id: str) -> dict[str, Any]:
    if not execute_tier_active(root, task_list or "", phase_id):
        return plan
    steps = [normalize_step(str(s)) for s in plan.get("steps") or []]
    adapted = [s for s in steps if s != "sw-execute"]
    out = dict(plan)
    out["steps"] = adapted
    out["executeTier"] = True
    out["executeTierResumeStep"] = "sw-verify"
    return out


def build_execute_step_plan_adaptivity(plan: dict[str, Any]) -> dict[str, Any]:
    refs = [r for r in plan.get("refs") or [] if isinstance(r, dict)]
    batches = plan.get("batches") or []
    parallel_width = max((len(b) for b in batches if isinstance(b, list)), default=1)
    parallelized = sum(1 for b in batches if isinstance(b, list) and len(b) > 1)
    expansions = sum(1 for r in refs if r.get("parentRef") or r.get("synthetic"))
    skipped = sum(1 for r in refs if ref_terminal_status(r) == "skipped")
    return {
        "refsParallelized": parallelized,
        "runtimeExpansions": expansions,
        "skippedRefs": skipped,
        "parallelBatchWidth": parallel_width,
        "refCount": len(refs),
    }


def attach_benefit_metric_to_status(status: dict[str, Any], execute_plan: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(status)
    if not execute_plan:
        return out
    decomposed = dict(out.get("decomposed") or {})
    decomposed["stepPlanAdaptivity"] = {
        **(decomposed.get("stepPlanAdaptivity") or {}),
        **build_execute_step_plan_adaptivity(execute_plan),
    }
    out["benefitMetric"] = {
        **(out.get("benefitMetric") or {}),
        "decomposed": decomposed,
    }
    return out


def supervised_plan_halt_required(root: Path, run_dir: Path) -> bool:
    if deliver_autonomy_mode(root) != "supervised":
        return False
    marker = run_dir / "execute-supervised-confirmed.json"
    return not marker.is_file()


def mark_supervised_plan_confirmed(run_dir: Path) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        run_dir / "execute-supervised-confirmed.json",
        {"confirmedAt": utc_now(), "mode": "supervised"},
    )


def supervised_fail_fast(root: Path, plan: dict[str, Any]) -> dict[str, Any] | None:
    if deliver_autonomy_mode(root) != "supervised":
        return None
    for ref in plan.get("refs") or []:
        if not isinstance(ref, dict):
            continue
        if ref_terminal_status(ref) == "blocked":
            return {
                "verdict": "blocked",
                "halt": "execute:supervised-fail-fast",
                "cause": "execute-supervised-fail-fast",
                "taskRef": ref.get("id"),
                "refCause": ref.get("cause"),
            }
    return None


def journal_integrated_refs(run_dir: Path) -> set[str]:
    path = run_dir / "integrate-journal.json"
    if not path.is_file():
        return set()
    try:
        journal = read_json(path)
    except Exception:
        return set()
    refs: set[str] = set()
    for entry in journal.get("entries") or []:
        if isinstance(entry, dict) and entry.get("verdict") == "pass":
            ref = entry.get("taskRef")
            if ref:
                refs.add(str(ref))
    return refs


def resume_frontier(root: Path, run_dir: Path) -> dict[str, Any]:
    plan = load_execute_plan(run_dir)
    if plan is None:
        fail("missing execute-step-plan.json", exit_code=EXIT_GATE, halt="execute:missing-plan")
    plan = sync_ref_statuses(root, plan)
    integrated = journal_integrated_refs(run_dir)
    deps: dict[str, set[str]] = {}
    for edge in plan.get("edges") or []:
        if not isinstance(edge, dict):
            continue
        src, dst = edge.get("from"), edge.get("to")
        if isinstance(src, str) and isinstance(dst, str):
            deps.setdefault(dst, set()).add(src)

    refs = {str(r.get("id")): r for r in plan.get("refs") or [] if isinstance(r, dict) and r.get("id")}
    done = {rid for rid, ref in refs.items() if ref_terminal_status(ref) in TERMINAL_REF_STATUSES}
    done |= integrated

    ready: list[str] = []
    stale: list[dict[str, str]] = []
    for rid, ref in sorted(refs.items(), key=lambda item: ref_sort_key(item[0])):
        status = ref_terminal_status(ref)
        if status in TERMINAL_REF_STATUSES or rid in integrated:
            continue
        if not deps.get(rid, set()) <= done:
            continue
        ready.append(rid)
        branch = str(ref.get("branch") or "")
        if branch:
            proc = subprocess.run(
                ["git", "-C", str(root), "rev-parse", "--verify", branch],
                capture_output=True,
                text=True,
            )
            if proc.returncode != 0:
                stale.append({"taskRef": rid, "branch": branch, "reason": "missing-branch"})

    return {
        "verdict": "pass",
        "action": "resume-frontier",
        "readyRefs": ready,
        "integratedRefs": sorted(integrated, key=ref_sort_key),
        "terminalRefs": sorted(done, key=ref_sort_key),
        "staleSubBranches": stale,
        "runDir": str(run_dir),
        "planPath": str(run_dir / EXECUTE_PLAN_FILENAME),
    }


def redact_execute_artifact(root: Path, payload: Any) -> str:
    raw = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    script = Path(__file__).resolve().parent / "memory-redact.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=raw,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        fail(proc.stderr.strip() or "memory-redact failed", exit_code=EXIT_GATE, halt="redaction-failed")
    return proc.stdout


def memory_safe_failure_report(root: Path, report: dict[str, Any]) -> dict[str, Any]:
    redacted = redact_execute_artifact(root, report)
    try:
        return json.loads(redacted)
    except json.JSONDecodeError:
        return {"redacted": redacted}


def _parse_kv(args: list[str], flag: str) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else None
    return None


def cmd_gate_check(root: Path, args: list[str]) -> None:
    phase_slug = _parse_kv(args, "--phase-slug") or os.environ.get("SW_PHASE_SLUG", "")
    run_dir_raw = _parse_kv(args, "--run-dir") or os.environ.get("SW_RUN_DIR", "")
    task_list = _parse_kv(args, "--task-list")
    phase_id = _parse_kv(args, "--phase-id") or ""
    run_dir = resolve_run_dir(phase_slug, run_dir_raw or None)
    result = ship_verify_gate_ok(root, run_dir, task_list=task_list, phase_id=phase_id)
    if result.get("verdict") == "blocked":
        emit(result, EXIT_GATE)
    emit(result)


def cmd_adapt_phase_plan(root: Path, args: list[str]) -> None:
    plan_raw = _parse_kv(args, "--plan")
    if not plan_raw:
        fail("--plan required")
    plan_path = Path(plan_raw)
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    task_list = _parse_kv(args, "--task-list") or ""
    phase_id = _parse_kv(args, "--phase-id") or str(plan.get("phaseId") or "")
    adapted = adapt_phase_plan_for_execute_tier(root, plan, task_list=task_list, phase_id=phase_id)
    emit({"verdict": "pass", "action": "adapt-phase-plan", "plan": adapted, "executeTier": bool(adapted.get("executeTier"))})


def cmd_supervised_halt(root: Path, args: list[str]) -> None:
    phase_slug = _parse_kv(args, "--phase-slug") or os.environ.get("SW_PHASE_SLUG", "")
    run_dir = resolve_run_dir(phase_slug, _parse_kv(args, "--run-dir"))
    if not supervised_plan_halt_required(root, run_dir):
        emit({"verdict": "pass", "action": "supervised-halt", "required": False})
    emit(
        {
            "verdict": "blocked",
            "action": "supervised-halt",
            "required": True,
            "halt": "execute:supervised-plan-confirm",
            "cause": "execute-supervised-plan-confirm",
            "note": "Confirm execute DAG before dispatch (R24)",
            "runDir": str(run_dir),
        },
        EXIT_GATE,
    )


def cmd_supervised_confirm(root: Path, args: list[str]) -> None:
    phase_slug = _parse_kv(args, "--phase-slug") or os.environ.get("SW_PHASE_SLUG", "")
    run_dir = resolve_run_dir(phase_slug, _parse_kv(args, "--run-dir"))
    mark_supervised_plan_confirmed(run_dir)
    emit({"verdict": "pass", "action": "supervised-confirm", "runDir": str(run_dir)})


def cmd_resume_frontier(root: Path, args: list[str]) -> None:
    phase_slug = _parse_kv(args, "--phase-slug") or os.environ.get("SW_PHASE_SLUG", "")
    run_dir = resolve_run_dir(phase_slug, _parse_kv(args, "--run-dir"))
    emit(resume_frontier(root, run_dir))


def cmd_step_plan_adaptivity(root: Path, args: list[str]) -> None:
    phase_slug = _parse_kv(args, "--phase-slug") or os.environ.get("SW_PHASE_SLUG", "")
    run_dir = resolve_run_dir(phase_slug, _parse_kv(args, "--run-dir"))
    plan = load_execute_plan(run_dir)
    if plan is None:
        fail("missing execute plan", exit_code=EXIT_GATE)
    emit({"verdict": "pass", "action": "step-plan-adaptivity", "metrics": build_execute_step_plan_adaptivity(plan)})


def cmd_should_use_execute_tier(root: Path, args: list[str]) -> None:
    task_list = _parse_kv(args, "--task-list") or ""
    phase_id = _parse_kv(args, "--phase-id") or ""
    active = execute_tier_active(root, task_list, phase_id)
    count = executable_subtask_count(root, task_list, phase_id) if task_list and phase_id else 0
    emit(
        {
            "verdict": "pass",
            "executeTierActive": active,
            "executableSubtasks": count,
            "enabled": load_execute_config(root).get("enabled", True),
        }
    )


def main() -> None:
    if len(sys.argv) < 3:
        fail(
            "usage: execute_ship.py <root> "
            "<gate-check|adapt-phase-plan|supervised-halt|supervised-confirm|resume-frontier|"
            "step-plan-adaptivity|should-use-execute-tier> [args...]"
        )
    root = Path(sys.argv[1])
    cmd = sys.argv[2]
    args = sys.argv[3:]
    handlers = {
        "gate-check": cmd_gate_check,
        "adapt-phase-plan": cmd_adapt_phase_plan,
        "supervised-halt": cmd_supervised_halt,
        "supervised-confirm": cmd_supervised_confirm,
        "resume-frontier": cmd_resume_frontier,
        "step-plan-adaptivity": cmd_step_plan_adaptivity,
        "should-use-execute-tier": cmd_should_use_execute_tier,
    }
    handler = handlers.get(cmd)
    if not handler:
        fail(f"unknown command: {cmd}")
    handler(root, args)


if __name__ == "__main__":
    main()
