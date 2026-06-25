#!/usr/bin/env python3
"""Durable deliver-loop driver for phase-mode /sw-deliver (PRD 007 R1–R12, R46)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from wave_json_io import StateCorruptError, read_json, write_json

SCRIPT_DIR = Path(__file__).resolve().parent
PLAN_PATH = Path(".cursor/sw-deliver-plan.json")
STATE_PATH = Path(".cursor/sw-deliver-state.json")
BLOCKER_PATH = Path(".cursor/sw-deliver-runs/blockers.json")
LOG_PATH = Path(".cursor/sw-deliver-runs/run.log")

MECHANICAL_ACTIONS = frozenset(
    {
        "plan",
        "state-init",
        "lock-acquire",
        "orchestrator-provision",
        "provision-phase",
        "collect-status",
        "merge-enqueue",
        "merge-run-next",
        "advance-wave",
        "write-blocker-report",
        "all-phases-complete",
    }
)
AGENT_ACTIONS = frozenset({"dispatch-ship", "remediate", "terminal-ship"})
TERMINAL_ACTIONS = frozenset({"halt-blocked", "complete", "terminal"})

DRIVER_STALE_SECONDS = int(os.environ.get("SW_DRIVER_STALE_SECONDS", "7200"))
DEFAULT_REMEDIATION_MAX = 2
DEFAULT_PHASE_TIMEOUT_MIN = int(os.environ.get("SW_PHASE_TIMEOUT_MINUTES", "240"))


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def parse_kv(args: list[str], flag: str, default: str | None = None) -> str | None:
    if flag in args:
        i = args.index(flag)
        return args[i + 1] if i + 1 < len(args) else default
    return default


def has_flag(args: list[str], flag: str) -> bool:
    return flag in args


def load_workflow_config(root: Path) -> dict[str, Any]:
    for rel in (".cursor/workflow.config.json", "workflow.config.json"):
        path = root / rel
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return data if isinstance(data, dict) else {}
            except json.JSONDecodeError:
                return {}
    return {}


def remediation_max(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    remediation = deliver.get("remediation") or {}
    raw = remediation.get("maxAttempts", DEFAULT_REMEDIATION_MAX)
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_REMEDIATION_MAX


def phase_timeout_minutes(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    watchdog = deliver.get("watchdog") or {}
    raw = watchdog.get("phaseTimeoutMinutes", DEFAULT_PHASE_TIMEOUT_MIN)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_PHASE_TIMEOUT_MIN


def parse_ts(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def age_seconds(ts: str) -> float | None:
    dt = parse_ts(ts)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def append_log(root: Path, entry: dict[str, Any]) -> None:
    path = root / LOG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps({**entry, "at": utc_now()}, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
    os.chmod(path, 0o600)


def load_plan(root: Path) -> dict[str, Any]:
    path = root / PLAN_PATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(root: Path) -> dict[str, Any]:
    path = root / STATE_PATH
    try:
        return read_json(path)
    except StateCorruptError as exc:
        fail(str(exc), exit_code=20, halt="blocked", cause="state:corrupt")


def save_state(root: Path, state: dict[str, Any]) -> None:
    state["updatedAt"] = utc_now()
    write_json(root / STATE_PATH, state)


def ensure_driver_fields(state: dict[str, Any]) -> None:
    state.setdefault("currentWave", 1)
    state.setdefault("nextAction", "plan")
    state.setdefault("remediationAttempts", {})
    state.setdefault("phaseWorktrees", {})
    state.setdefault("driverHeartbeatAt", utc_now())


def phase_status_map(state: dict[str, Any]) -> dict[str, str]:
    phases = state.get("phases") or {}
    return {
        str(k): (v.get("status", "pending") if isinstance(v, dict) else str(v))
        for k, v in phases.items()
    }


def deps_satisfied(phase_id: str, plan: dict[str, Any], statuses: dict[str, str]) -> bool:
    for edge in plan.get("edges") or []:
        if str(edge.get("to")) == phase_id:
            dep = str(edge.get("from", ""))
            if statuses.get(dep) != "green-merged":
                return False
    return True


def wave_phase_ids(plan: dict[str, Any], wave_num: int) -> list[str]:
    waves = plan.get("waves") or []
    if wave_num < 1 or wave_num > len(waves):
        return []
    return [str(p) for p in waves[wave_num - 1]]


def all_phases_merged(state: dict[str, Any]) -> bool:
    statuses = phase_status_map(state)
    return bool(statuses) and all(s == "green-merged" for s in statuses.values())


def check_watchdog(root: Path, state: dict[str, Any]) -> str | None:
    hb = state.get("driverHeartbeatAt")
    if isinstance(hb, str):
        age = age_seconds(hb)
        if age is not None and age > DRIVER_STALE_SECONDS:
            return "driver-heartbeat-stale"
    timeout_min = phase_timeout_minutes(root)
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict):
            continue
        if meta.get("status") != "in-flight":
            continue
        started = meta.get("startedAt") or meta.get("updatedAt")
        if isinstance(started, str):
            age = age_seconds(started)
            if age is not None and age > timeout_min * 60:
                return f"phase-timeout:{pid}"
    return None


def item_for_phase(plan: dict[str, Any], phase_id: str) -> dict[str, Any] | None:
    for item in plan.get("items") or []:
        if str(item.get("id")) == phase_id:
            return item
    return None


def compute_next_action(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    ensure_driver_fields(state)
    verdict = state.get("verdict", "running")

    if verdict in ("complete", "blocked", "rejected"):
        return {"action": "terminal", "verdict": verdict, "resume": True}

    if not plan:
        return {"action": "plan", "resume": bool(state.get("phases"))}

    if plan.get("mode") != "phase":
        fail("deliver-loop requires phase-mode plan", exit_code=2)

    if not state.get("phases"):
        return {"action": "state-init", "resume": False}

    target = (plan.get("target") or {}).get("branch") or (state.get("target") or {}).get(
        "branch"
    )
    if not target:
        fail("plan/state missing target branch")

    if not state.get("orchestratorWorktree"):
        if state.get("nextAction") in (None, "plan", "state-init"):
            return {"action": "lock-acquire", "target": target, "resume": True}
        return {"action": "orchestrator-provision", "target": target, "resume": True}

    if all_phases_merged(state):
        return {"action": "all-phases-complete", "resume": True}

    statuses = phase_status_map(state)
    wave_num = int(state.get("currentWave") or 1)
    wave_ids = wave_phase_ids(plan, wave_num)

    # Blocked phases awaiting remediation or halt (before watchdog — explicit blockers win)
    for pid in wave_ids:
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict):
            continue
        if meta.get("status") == "blocked":
            attempts = state.get("remediationAttempts") or {}
            count = int(attempts.get(pid, 0))
            max_attempts = remediation_max(root)
            if count < max_attempts:
                return {
                    "action": "remediate",
                    "phaseId": pid,
                    "phaseSlug": meta.get("slug"),
                    "attempt": count + 1,
                    "maxAttempts": max_attempts,
                    "resume": True,
                }
            return {
                "action": "halt-blocked",
                "phaseId": pid,
                "phaseSlug": meta.get("slug"),
                "cause": "remediation-budget-exhausted",
                "resume": True,
            }

    watchdog = check_watchdog(root, state)
    if watchdog:
        return {
            "action": "halt-blocked",
            "cause": watchdog,
            "resume": True,
            "watchdog": True,
        }

    # In-flight: collect durable status
    for pid in wave_ids:
        meta = (state.get("phases") or {}).get(pid, {})
        if isinstance(meta, dict) and meta.get("status") == "in-flight":
            slug = meta.get("slug", "")
            status_path = root / ".cursor/sw-deliver-runs" / slug / "status.json"
            if status_path.is_file():
                status = read_json(status_path, absent_ok=False)
                if status.get("verdict") == "merge-ready-green":
                    return {
                        "action": "merge-enqueue",
                        "phaseId": pid,
                        "phaseSlug": slug,
                        "resume": True,
                    }
                if status.get("verdict") == "blocked":
                    return {
                        "action": "collect-status",
                        "phaseId": pid,
                        "phaseSlug": slug,
                        "resume": True,
                    }
            return {
                "action": "dispatch-ship",
                "phaseId": pid,
                "phaseSlug": slug,
                "resume": True,
                "note": "awaiting /sw-ship --phase-mode in phase worktree",
            }

    # Pending runnable phases in current wave
    for pid in wave_ids:
        if statuses.get(pid) != "pending":
            continue
        if not deps_satisfied(pid, plan, statuses):
            continue
        worktrees = state.get("phaseWorktrees") or {}
        if pid not in worktrees:
            item = item_for_phase(plan, pid)
            return {
                "action": "provision-phase",
                "phaseId": pid,
                "phaseSlug": (item or {}).get("slug"),
                "resume": True,
            }
        item = item_for_phase(plan, pid)
        return {
            "action": "dispatch-ship",
            "phaseId": pid,
            "phaseSlug": (item or {}).get("slug"),
            "resume": True,
        }

    # Wave complete — advance or wait on blocked upstream elsewhere
    if wave_ids and all(
        statuses.get(pid) in ("green-merged", "blocked", "rejected") for pid in wave_ids
    ):
        waves = plan.get("waves") or []
        if wave_num < len(waves):
            return {"action": "advance-wave", "fromWave": wave_num, "resume": True}
        if any(statuses.get(pid) == "blocked" for pid in wave_ids):
            return {"action": "halt-blocked", "cause": "wave-has-blocked-phases", "resume": True}

    return {
        "action": "dispatch-ship",
        "resume": True,
        "note": "waiting for upstream phases or merge queue",
    }


def run_wave(root: Path, *args: str) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        ["bash", str(root / "scripts/wave.sh"), *args],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    data: dict[str, Any] = {}
    if proc.stdout.strip():
        try:
            parsed = json.loads(proc.stdout)
            if isinstance(parsed, dict):
                data = parsed
        except json.JSONDecodeError:
            data = {"raw": proc.stdout.strip()}
    if proc.stderr.strip():
        data.setdefault("stderr", proc.stderr.strip())
    data["exitCode"] = proc.returncode
    return proc.returncode, data


def persist_cursor(root: Path, state: dict[str, Any], action: str, **extra: Any) -> None:
    state["nextAction"] = action
    state["driverHeartbeatAt"] = utc_now()
    for key, val in extra.items():
        state[key] = val
    save_state(root, state)
    append_log(root, {"event": "driver-transition", "nextAction": action, **extra})


def write_blocker_report(root: Path, state: dict[str, Any], cause: str) -> Path:
    ec, report_payload = run_wave(root, "report", "blockers")
    report = report_payload.get("report") or {}
    out = {
        "verdict": "halt",
        "cause": cause,
        "generatedAt": utc_now(),
        "report": report,
        "remediationAttempts": state.get("remediationAttempts") or {},
    }
    path = root / BLOCKER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, out)
    return path


def execute_mechanical(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    step: dict[str, Any],
    *,
    loop_args: list[str] | None = None,
) -> dict[str, Any]:
    action = step["action"]
    task_list = state.get("source_task_list") or plan.get("source_task_list")
    loop_args = loop_args or []

    if action == "plan":
        if not task_list:
            fail("deliver-loop requires --task-list on first run or state.source_task_list")
        plan_args = ["plan", "--task-list", str(task_list)]
        if has_flag(loop_args, "--skip-base-check"):
            plan_args.append("--skip-base-check")
        ec, data = run_wave(root, *plan_args)
        if ec != 0:
            fail(data.get("error") or "plan failed", exit_code=ec, **data)
        plan = load_plan(root)
        persist_cursor(root, state, "state-init")
        return {"executed": "plan", "plan": plan.get("target")}

    if action == "state-init":
        ec, data = run_wave(root, "state", "init", "--plan", str(PLAN_PATH))
        if ec != 0:
            fail(data.get("error") or "state init failed", exit_code=ec, **data)
        state.update(load_state(root))
        ensure_driver_fields(state)
        persist_cursor(root, state, "lock-acquire")
        return {"executed": "state-init"}

    if action == "lock-acquire":
        target = step.get("target") or (plan.get("target") or {}).get("branch")
        ec, data = run_wave(root, "lock", "acquire", "--target", str(target), "--nonblock")
        if ec not in (0, 20):
            fail(data.get("error") or "lock acquire failed", exit_code=ec, **data)
        if ec == 20:
            fail("orchestrator lock held", exit_code=20, holder=data.get("holder"))
        persist_cursor(root, state, "orchestrator-provision")
        return {"executed": "lock-acquire", "target": target}

    if action == "orchestrator-provision":
        ec, data = run_wave(
            root, "orchestrator", "provision", "--plan", str(PLAN_PATH)
        )
        if ec != 0:
            fail(data.get("error") or "orchestrator provision failed", exit_code=ec, **data)
        state.update(load_state(root))
        persist_cursor(root, state, "provision-phase")
        return {"executed": "orchestrator-provision"}

    if action == "provision-phase":
        pid = str(step.get("phaseId", ""))
        ec, data = run_wave(
            root,
            "phase",
            "provision",
            "--phase-id",
            pid,
            "--plan",
            str(PLAN_PATH),
        )
        if ec != 0:
            fail(data.get("error") or "phase provision failed", exit_code=ec, **data)
        worktrees = state.setdefault("phaseWorktrees", {})
        worktrees[pid] = {
            "name": data.get("name") or data.get("worktreeName"),
            "path": data.get("path") or data.get("worktreePath"),
        }
        phases = state.setdefault("phases", {})
        if pid in phases and isinstance(phases[pid], dict):
            phases[pid]["status"] = "in-flight"
            phases[pid]["startedAt"] = utc_now()
        persist_cursor(root, state, "dispatch-ship", phaseWorktrees=worktrees)
        return {"executed": "provision-phase", "phaseId": pid, **data}

    if action == "collect-status":
        slug = str(step.get("phaseSlug", ""))
        ec, data = run_wave(root, "status", "collect", "--phase-slug", slug)
        if ec != 0:
            fail(data.get("error") or "status collect failed", exit_code=ec, **data)
        state.update(load_state(root))
        persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {"executed": "collect-status", "phaseSlug": slug, **data}

    if action == "merge-enqueue":
        slug = str(step.get("phaseSlug", ""))
        ec, data = run_wave(root, "merge", "enqueue", "--phase-slug", slug)
        if ec != 0:
            fail(data.get("error") or "merge enqueue failed", exit_code=ec, **data)
        persist_cursor(root, state, "merge-run-next")
        return {"executed": "merge-enqueue", "phaseSlug": slug}

    if action == "merge-run-next":
        ec, data = run_wave(root, "merge", "run-next")
        if ec not in (0, 10):
            fail(data.get("error") or "merge run-next failed", exit_code=ec, **data)
        state.update(load_state(root))
        persist_cursor(root, state, "provision-phase")
        return {"executed": "merge-run-next", **data}

    if action == "advance-wave":
        wave_num = int(state.get("currentWave") or 1) + 1
        persist_cursor(root, state, "provision-phase", currentWave=wave_num)
        return {"executed": "advance-wave", "currentWave": wave_num}

    if action == "all-phases-complete":
        persist_cursor(root, state, "terminal-ship")
        return {"executed": "all-phases-complete", "next": "terminal-ship"}

    if action == "halt-blocked":
        cause = str(step.get("cause", "blocked"))
        state["verdict"] = "blocked"
        state["cause"] = cause
        path = write_blocker_report(root, state, cause)
        persist_cursor(root, state, "halt-blocked", blockerReport=str(path))
        return {"executed": "halt-blocked", "cause": cause, "blockerReport": str(path)}

    fail(f"unknown mechanical action: {action}")


def cmd_deliver_loop(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    max_steps = int(parse_kv(args, "--max-steps", "12") or "12")
    task_list = parse_kv(args, "--task-list")

    state = load_state(root)
    plan = load_plan(root)
    resumed = bool(state.get("verdict") == "running" and state.get("phases"))

    if task_list and not state.get("source_task_list"):
        state["source_task_list"] = task_list

    if not plan and task_list:
        state.setdefault("verdict", "running")
        ensure_driver_fields(state)
        save_state(root, state)

    steps_taken: list[dict[str, Any]] = []
    for _ in range(max_steps):
        state = load_state(root)
        plan = load_plan(root)
        if task_list:
            state["source_task_list"] = task_list
        step = compute_next_action(root, state, plan)
        step["resumed"] = resumed

        if dry_run:
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "dry_run": True,
                    "resumed": resumed,
                    "next": step,
                }
            )

        if step["action"] in AGENT_ACTIONS | TERMINAL_ACTIONS:
            if step["action"] == "terminal":
                emit(
                    {
                        "verdict": "pass",
                        "action": "deliver-loop",
                        "resumed": resumed,
                        "terminal": True,
                        "runVerdict": step.get("verdict"),
                        "nextAction": state.get("nextAction"),
                    }
                )
            if step["action"] == "remediate":
                attempts = state.setdefault("remediationAttempts", {})
                pid = str(step.get("phaseId", ""))
                attempts[pid] = int(step.get("attempt", 1))
                persist_cursor(root, state, "remediate")
            elif step["action"] == "halt-blocked":
                execute_mechanical(root, state, plan, step, loop_args=args)
                emit(
                    {
                        "verdict": "blocked",
                        "action": "deliver-loop",
                        "resumed": resumed,
                        "halt": True,
                        "cause": step.get("cause"),
                        "blockerReport": str(root / BLOCKER_PATH),
                        "nextAction": "halt-blocked",
                    },
                    20,
                )
            else:
                persist_cursor(root, state, step["action"])
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitAgent": step["action"] in AGENT_ACTIONS,
                    "next": step,
                    "stepsTaken": steps_taken,
                }
            )

        if step["action"] not in MECHANICAL_ACTIONS:
            fail(f"unhandled action: {step['action']}", step=step)

        result = execute_mechanical(root, state, plan, step, loop_args=args)
        steps_taken.append(result)
        resumed = True

    emit(
        {
            "verdict": "pass",
            "action": "deliver-loop",
            "resumed": resumed,
            "note": f"step budget ({max_steps}) reached",
            "stepsTaken": steps_taken,
            "next": compute_next_action(root, load_state(root), load_plan(root)),
        }
    )


def cmd_remediation_default(root: Path, _args: list[str]) -> None:
    emit(
        {
            "verdict": "pass",
            "maxAttempts": remediation_max(root),
            "default": DEFAULT_REMEDIATION_MAX,
        }
    )


def main() -> None:
    if len(sys.argv) < 2:
        fail("usage: wave_deliver_loop.py <root> deliver-loop [--task-list PATH] [--dry-run]")
    root = Path(sys.argv[1])
    cmd = sys.argv[2] if len(sys.argv) > 2 else "deliver-loop"
    args = sys.argv[3:]

    if cmd == "deliver-loop":
        cmd_deliver_loop(root, args)
    elif cmd == "remediation-default":
        cmd_remediation_default(root, args)
    elif cmd == "compute-next":
        state = load_state(root)
        plan = load_plan(root)
        emit(
            {
                "verdict": "pass",
                "next": compute_next_action(root, state, plan),
            }
        )
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
