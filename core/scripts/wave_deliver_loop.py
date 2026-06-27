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

from plan_persist import (
    LIFECYCLE_PHASE_PLAN_PENDING,
    LIFECYCLE_PHASE_PLAN_VALIDATED,
    LIFECYCLE_WAVE_VALIDATED,
    get_lifecycle,
    needs_phase_plan_proposal,
    persist_wave_batching_plan,
    set_phase_lifecycle,
    set_wave_lifecycle,
    wave_lifecycle,
    wave_plan_ready,
)
from wave_plan_validate import (
    phase_fallback_canonical_chain,
    read_config_plan_policy,
    validate_wave_plan,
    wave_fallback_canonical_waves,
)


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
from wave_merge import (
    VALID_STATUS_VERDICTS,
    check_status_sha,
    phase_branch_head_optional,
    status_file_for,
)
from wave_state import (
    append_log as state_append_log,
    load_deliver_state,
    resolve_state_path,
    save_deliver_state,
    scoped_paths,
    target_branch_from_state,
)

SCRIPT_DIR = Path(__file__).resolve().parent
PLAN_PATH = Path(".cursor/sw-deliver-plan.json")
BLOCKER_PATH = Path(".cursor/sw-deliver-runs/blockers.json")

MECHANICAL_ACTIONS = frozenset(
    {
        "plan",
        "base-capture",
        "spec-seed",
        "state-init",
        "lock-acquire",
        "orchestrator-provision",
        "provision-phase",
        "collect-all-ready",
        "collect-status",
        "merge-enqueue",
        "merge-run-next",
        "phase-teardown-run",
        "advance-wave",
        "wave-plan-persist",
        "phase-plan-entry",
        "write-blocker-report",
        "all-phases-complete",
        "finalize-completion",
        "suggest-cleanup",
    }
)
AGENT_ACTIONS = frozenset(
    {
        "dispatch-ship",
        "dispatch-batch",
        "remediate",
        "terminal-ship",
        "retrospective",
        "compound-ship",
    }
)
AWAIT_ACTIONS = frozenset({"await-in-flight"})
TERMINAL_ACTIONS = frozenset({"halt-blocked", "complete", "terminal"})

DRIVER_STALE_SECONDS = int(os.environ.get("SW_DRIVER_STALE_SECONDS", "7200"))
DEFAULT_REMEDIATION_MAX = 2
DEFAULT_PHASE_TIMEOUT_MIN = int(os.environ.get("SW_PHASE_TIMEOUT_MINUTES", "240"))
DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN = int(
    os.environ.get("SW_BACKGROUND_TASK_TIMEOUT_MINUTES", "120")
)
MERGED_PHASE_STATUSES = frozenset({"green-merged", "teardown-pending", "teardown-complete"})
DEFAULT_MAX_ITERATIONS = 500
DEFAULT_NO_PROGRESS_THRESHOLD = 3
PROPOSAL_OVERHEAD_ACTIONS = frozenset({"wave-plan-persist", "phase-plan-entry"})
BUDGET_HALT_CAUSES = frozenset(
    {
        "conductor:max-iterations-exceeded",
        "conductor:max-run-minutes-exceeded",
        "conductor:no-progress",
        "conductor:plan-rejection-breaker",
        "plan-rejection-breaker",
    }
)


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def emit(obj: dict[str, Any], exit_code: int = 0) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(exit_code)


def fail(error: str, exit_code: int = 2, **extra: Any) -> None:
    extra.pop("error", None)
    emit({"verdict": "fail", "error": error, **extra}, exit_code)


def fail_payload(data: dict[str, Any], default: str, exit_code: int, **extra: Any) -> None:
    reserved = {"error", *extra.keys()}
    payload = {k: v for k, v in data.items() if k not in reserved}
    fail(data.get("error") or default, exit_code=exit_code, **extra, **payload)


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


def background_task_timeout_minutes(root: Path) -> int:
    deliver = load_workflow_config(root).get("deliver") or {}
    watchdog = deliver.get("watchdog") or {}
    raw = watchdog.get("backgroundTaskTimeoutMinutes", DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_BACKGROUND_TASK_TIMEOUT_MIN


def parallel_ceiling(root: Path) -> int:
    worktree = load_workflow_config(root).get("worktree") or {}
    raw = worktree.get("parallelCeiling", 4)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 4


def autonomy_config(root: Path) -> dict[str, Any]:
    deliver = load_workflow_config(root).get("deliver") or {}
    autonomy = deliver.get("autonomy") or {}
    return autonomy if isinstance(autonomy, dict) else {}


def max_iterations(root: Path) -> int:
    raw = autonomy_config(root).get("maxIterations", DEFAULT_MAX_ITERATIONS)
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return DEFAULT_MAX_ITERATIONS


def max_run_minutes(root: Path) -> int | None:
    raw = autonomy_config(root).get("maxRunMinutes")
    if raw is None:
        return None
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return None


def no_progress_threshold(_root: Path) -> int:
    return DEFAULT_NO_PROGRESS_THRESHOLD


def init_budget_counters(state: dict[str, Any]) -> None:
    state.setdefault("runStartedAt", utc_now())
    state.setdefault("driverIterationCount", 0)
    state.setdefault("noProgressStreak", 0)
    state.setdefault(
        "budgetCounters",
        {"proposalOverheadCount": 0, "executionIterationCount": 0},
    )
    state.setdefault("lastProgressKey", None)


def build_state_signature(state: dict[str, Any]) -> str:
    phases = state.get("phases") or {}
    status_map = {
        str(k): (v.get("status") if isinstance(v, dict) else str(v))
        for k, v in phases.items()
    }
    payload = {
        "verdict": state.get("verdict"),
        "nextAction": state.get("nextAction"),
        "currentWave": state.get("currentWave"),
        "phaseStatuses": dict(sorted(status_map.items())),
        "mergeQueueLength": len(state.get("mergeQueue") or []),
        "mergeJournalPresent": state.get("mergeJournal") is not None,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def record_budget_tick(state: dict[str, Any], next_action: str) -> None:
    init_budget_counters(state)
    state["driverIterationCount"] = int(state.get("driverIterationCount", 0)) + 1
    counters = state.setdefault(
        "budgetCounters",
        {"proposalOverheadCount": 0, "executionIterationCount": 0},
    )
    if next_action in PROPOSAL_OVERHEAD_ACTIONS:
        counters["proposalOverheadCount"] = int(counters.get("proposalOverheadCount", 0)) + 1
    else:
        counters["executionIterationCount"] = int(
            counters.get("executionIterationCount", 0)
        ) + 1
        progress_key = json.dumps(
            {"signature": build_state_signature(state), "nextAction": next_action},
            sort_keys=True,
        )
        if progress_key == state.get("lastProgressKey"):
            state["noProgressStreak"] = int(state.get("noProgressStreak", 0)) + 1
        else:
            state["noProgressStreak"] = 0
            state["lastProgressKey"] = progress_key


def plan_rejection_halt_cause(state: dict[str, Any]) -> str | None:
    log = state.get("planRejectionLog")
    if not isinstance(log, dict):
        return None
    halt = log.get("halt")
    if not isinstance(halt, dict):
        return None
    return str(halt.get("cause") or "conductor:plan-rejection-breaker")


def sync_plan_rejection_no_progress(state: dict[str, Any]) -> None:
    """Subscribe 022 planRejectionLog breaker into the no-progress surface (R22)."""
    cause = plan_rejection_halt_cause(state)
    if not cause:
        return
    threshold = DEFAULT_NO_PROGRESS_THRESHOLD
    state["noProgressStreak"] = max(int(state.get("noProgressStreak", 0)), threshold)


def check_budget_halt(root: Path, state: dict[str, Any]) -> str | None:
    init_budget_counters(state)
    sync_plan_rejection_no_progress(state)

    rejection = plan_rejection_halt_cause(state)
    if rejection:
        return rejection

    counters = state.get("budgetCounters") or {}
    execution_count = int(counters.get("executionIterationCount", 0))
    if execution_count >= max_iterations(root):
        return "conductor:max-iterations-exceeded"

    max_mins = max_run_minutes(root)
    if max_mins is not None:
        started = state.get("runStartedAt")
        if isinstance(started, str):
            age = age_seconds(started)
            if age is not None and age > max_mins * 60:
                return "conductor:max-run-minutes-exceeded"

    if int(state.get("noProgressStreak", 0)) >= no_progress_threshold(root):
        return "conductor:no-progress"

    return None


def is_budget_halt(cause: str) -> bool:
    return cause in BUDGET_HALT_CAUSES or cause.startswith("conductor:")


def preserve_merge_queue_on_halt(state: dict[str, Any]) -> None:
    """Clear abandoned merge journal while keeping queue replayable (R22)."""
    journal = state.get("mergeJournal")
    if not isinstance(journal, dict):
        return
    phase_slug = str(journal.get("phase") or "")
    queue = list(state.get("mergeQueue") or [])
    if phase_slug:
        existing = next(
            (entry for entry in queue if entry.get("phaseSlug") == phase_slug),
            None,
        )
        if existing is None:
            queue.insert(
                0,
                {
                    "phaseSlug": phase_slug,
                    "head": journal.get("head"),
                    "recoveredFromJournal": True,
                },
            )
        elif existing.get("head") is None and journal.get("head"):
            existing["head"] = journal.get("head")
    state["mergeQueue"] = queue
    state["mergeJournal"] = None


def clean_consolidated_halt(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    cause: str,
) -> dict[str, Any]:
    from wave_merge import clear_open_journal_if_merged
    from wave_state import append_log as state_append_log, scoped_paths

    state.update(clear_open_journal_if_merged(root, state))
    preserve_merge_queue_on_halt(state)
    state["verdict"] = "blocked"
    state["cause"] = cause
    save_state(root, state)

    target = (state.get("target") or {}).get("branch") or (plan.get("target") or {}).get(
        "branch"
    )
    lock_released = False
    if target:
        lock_path = scoped_paths(root, str(target))["lock"]
        if lock_path.is_file():
            meta: dict[str, Any] = {}
            try:
                raw = lock_path.read_text(encoding="utf-8").strip()
                if raw:
                    meta = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                meta = {}
            lock_path.unlink(missing_ok=True)
            state_append_log(root, {"event": "lock-release", "target": meta.get("target") or target})
            lock_released = True

    path = write_blocker_report(root, state, cause)
    persist_cursor(
        root,
        state,
        "halt-blocked",
        blockerReport=str(path),
        budgetHalt=True,
        lockReleased=lock_released,
    )
    return {
        "executed": "halt-blocked",
        "cause": cause,
        "blockerReport": str(path),
        "budgetHalt": True,
        "lockReleased": lock_released,
        "mergeQueueLength": len(state.get("mergeQueue") or []),
        "mergeJournalPresent": state.get("mergeJournal") is not None,
    }


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


def append_log(root: Path, entry: dict[str, Any], state: dict[str, Any] | None = None) -> None:
    target = target_branch_from_state(state) if state else None
    state_append_log(root, entry, target=target)


def load_plan(root: Path) -> dict[str, Any]:
    path = root / PLAN_PATH
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_state(root: Path, task_list: str | None = None) -> dict[str, Any]:
    return load_deliver_state(root, task_list=task_list)


def save_state(root: Path, state: dict[str, Any]) -> None:
    save_deliver_state(root, state)


def ensure_driver_fields(state: dict[str, Any]) -> None:
    state.setdefault("currentWave", 1)
    state.setdefault("nextAction", "plan")
    state.setdefault("remediationAttempts", {})
    state.setdefault("phaseWorktrees", {})
    state.setdefault("driverHeartbeatAt", utc_now())
    init_budget_counters(state)


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
            if statuses.get(dep) not in MERGED_PHASE_STATUSES:
                return False
    return True


def wave_phase_ids(plan: dict[str, Any], wave_num: int) -> list[str]:
    waves = plan.get("waves") or []
    if wave_num < 1 or wave_num > len(waves):
        return []
    return [str(p) for p in waves[wave_num - 1]]


def all_phases_merged(state: dict[str, Any]) -> bool:
    statuses = phase_status_map(state)
    return bool(statuses) and all(s in MERGED_PHASE_STATUSES for s in statuses.values())


def in_flight_count(statuses: dict[str, str], wave_ids: list[str]) -> int:
    return sum(1 for pid in wave_ids if statuses.get(pid) == "in-flight")


def phase_dispatch_payload(
    plan: dict[str, Any], phase_id: str
) -> dict[str, Any]:
    item = item_for_phase(plan, phase_id) or {}
    return {
        "phaseId": phase_id,
        "phaseSlug": item.get("slug"),
        "branch": item.get("branch"),
    }


def runnable_pending_phases(
    wave_ids: list[str],
    statuses: dict[str, str],
    plan: dict[str, Any],
) -> list[str]:
    ready: list[str] = []
    for pid in sorted(wave_ids):
        if statuses.get(pid) != "pending":
            continue
        if not deps_satisfied(pid, plan, statuses):
            continue
        ready.append(pid)
    return ready


def mark_background_task_blocked(
    state: dict[str, Any], phase_id: str, cause: str
) -> None:
    phases = state.setdefault("phases", {})
    meta = phases.get(phase_id)
    if not isinstance(meta, dict):
        return
    meta["status"] = "blocked"
    meta["cause"] = cause
    meta["updatedAt"] = utc_now()


def check_background_task_failures(
    root: Path, state: dict[str, Any], wave_ids: list[str]
) -> str | None:
    timeout_min = background_task_timeout_minutes(root)
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        if not meta.get("backgroundDispatchedAt"):
            continue
        slug = meta.get("slug", pid)
        status_path = status_file_for(root, slug, None, state)
        if status_path.is_file():
            status = read_json(status_path, absent_ok=False)
            if status.get("verdict") in VALID_STATUS_VERDICTS:
                continue
        started = meta.get("backgroundDispatchedAt") or meta.get("startedAt")
        if isinstance(started, str):
            age = age_seconds(started)
            if age is not None and age > timeout_min * 60:
                mark_background_task_blocked(
                    state,
                    pid,
                    f"background-task-timeout:{pid}",
                )
                save_state(root, state)
                return f"background-task-timeout:{pid}"
    return None


def merge_ready_in_flight_phases(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    wave_ids: list[str],
) -> list[dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", pid)
        status_path = status_file_for(root, slug, None, state)
        if not status_path.is_file():
            continue
        status = read_json(status_path, absent_ok=False)
        if status.get("verdict") != "merge-ready-green":
            continue
        phase_branch = meta.get("branch")
        if phase_branch:
            expected = phase_branch_head_optional(root, state, slug, str(phase_branch))
            if expected:
                ok_sha, _sha_cause = check_status_sha(status, expected)
                if not ok_sha:
                    continue
        ok, _cause = tasks_currency_ok(root, state, plan)
        if not ok:
            continue
        ready.append({"phaseId": pid, "phaseSlug": slug})
    return ready


def in_flight_merge_halt(
    root: Path,
    state: dict[str, Any],
    plan: dict[str, Any],
    wave_ids: list[str],
) -> dict[str, Any] | None:
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", pid)
        status_path = status_file_for(root, slug, None, state)
        if not status_path.is_file():
            continue
        status = read_json(status_path, absent_ok=False)
        if status.get("verdict") != "merge-ready-green":
            continue
        phase_branch = meta.get("branch")
        if phase_branch:
            expected = phase_branch_head_optional(root, state, slug, str(phase_branch))
            if expected:
                ok_sha, sha_cause = check_status_sha(status, expected)
                if not ok_sha:
                    return {
                        "action": "halt-blocked",
                        "cause": sha_cause or "phase-status:stale",
                        "resume": True,
                    }
        ok, cause = tasks_currency_ok(root, state, plan)
        if not ok:
            return {
                "action": "halt-blocked",
                "cause": cause,
                "resume": True,
            }
    return None


def mark_phases_in_flight(
    state: dict[str, Any], phase_ids: list[str], *, background: bool = False
) -> None:
    phases = state.setdefault("phases", {})
    now = utc_now()
    for pid in phase_ids:
        meta = phases.get(pid)
        if not isinstance(meta, dict):
            continue
        meta["status"] = "in-flight"
        meta["startedAt"] = meta.get("startedAt") or now
        if background:
            meta["backgroundDispatchedAt"] = now
        phases[pid] = meta


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


def task_list_from(state: dict[str, Any], plan: dict[str, Any]) -> str | None:
    raw = state.get("source_task_list") or plan.get("source_task_list")
    return str(raw) if raw else None


def trunk_base_persisted(root: Path) -> bool:
    path = root / ".cursor" / "sw-base-state.json"
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    trunk = data.get("trunkBase")
    return isinstance(trunk, dict) and bool(trunk.get("name")) and bool(trunk.get("sha"))


def run_resolve_capture(root: Path) -> tuple[int, dict[str, Any]]:
    script = root / "scripts" / "resolve-base-branch.sh"
    if not script.is_file():
        return 2, {"verdict": "fail", "error": "resolve-base-branch.sh missing"}
    proc = subprocess.run(
        ["bash", str(script), "capture"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {"verdict": "fail", "error": proc.stderr.strip() or proc.stdout.strip()}
    return proc.returncode, data


def canonical_task_list_path(root: Path, raw: str) -> str:
    path = Path(raw)
    if not path.is_absolute():
        path = (root / path).resolve()
    else:
        path = path.resolve()
    try:
        return str(path.relative_to(root.resolve()))
    except ValueError:
        return str(path)


def assert_run_identity(
    root: Path, state: dict[str, Any], task_list: str | None, loop_args: list[str]
) -> None:
    """Refuse a new run when durable state belongs to a different task list (R30, R43)."""
    if not task_list or not state.get("phases"):
        return
    if state.get("verdict") not in (None, "running"):
        return
    existing = state.get("source_task_list")
    if not existing:
        return
    if canonical_task_list_path(root, str(existing)) == canonical_task_list_path(root, task_list):
        return
    if has_flag(loop_args, "--reset"):
        return
    fail(
        "stale run-state from a different source_task_list/prd_number",
        exit_code=20,
        halt="stale-state",
        remediation="bash scripts/wave.sh deliver-loop --reset --task-list <path> or remove scoped .cursor/sw-deliver-state.<slug>.json",
    )


def _target_merge_detected(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_compound.py"), str(root), "completion", "check-merge"],
        cwd=str(root),
        text=True,
        capture_output=True,
    )
    try:
        data = json.loads(proc.stdout or "{}")
        return {
            "merged": bool(data.get("merged")),
            "status": data.get("status"),
            "detail": data.get("detail"),
        }
    except json.JSONDecodeError:
        return {"merged": False, "reason": "check-merge-failed"}


def tasks_currency_ok(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> tuple[bool, str | None]:
    tasks_file = task_list_from(state, plan)
    if not tasks_file:
        return True, None
    state_py = SCRIPT_DIR / "wave_state.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(state_py),
            str(root),
            "ledger",
            "check",
            "--tasks-file",
            tasks_file,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        return True, None
    return False, "tasks-currency-divergence"



def effective_wave_plan(state: dict[str, Any], plan: dict[str, Any]) -> dict[str, Any]:
    """Single source of truth: persisted waveBatchingPlan overlays frozen deliver plan waves."""
    batching = state.get("waveBatchingPlan")
    if isinstance(batching, dict) and batching.get("waves"):
        merged = dict(plan)
        merged["waves"] = batching.get("waves")
        if batching.get("parallelCeiling"):
            merged["parallelCeiling"] = batching.get("parallelCeiling")
        if batching.get("planPolicy"):
            merged["planPolicy"] = batching.get("planPolicy")
        return merged
    return plan


def phase_run_dir_for_slug(root: Path, slug: str) -> Path:
    return root / ".cursor" / "sw-deliver-runs" / slug


def mechanical_phase_plan(
    root: Path, phase_id: str, slug: str, state: dict[str, Any] | None = None
) -> dict[str, Any]:
    recorded_parent = None
    if state:
        batching = state.get("waveBatchingPlan")
        if isinstance(batching, dict):
            recorded_parent = batching
    return phase_fallback_canonical_chain(root, "ship", phase_id, recorded_parent=recorded_parent)


def dispatch_or_phase_plan_entry(
    state: dict[str, Any], plan: dict[str, Any], phase_id: str, *, note: str | None = None
) -> dict[str, Any]:
    item = item_for_phase(plan, phase_id) or {}
    slug = item.get("slug") or phase_id
    if needs_phase_plan_proposal(state, phase_id):
        return {
            "action": "phase-plan-entry",
            "phaseId": phase_id,
            "phaseSlug": slug,
            "resume": True,
        }
    payload = {
        "action": "dispatch-ship",
        "phaseId": phase_id,
        "phaseSlug": slug,
        "resume": True,
    }
    if note:
        payload["note"] = note
    return payload


def compute_next_action(
    root: Path, state: dict[str, Any], plan: dict[str, Any]
) -> dict[str, Any]:
    ensure_driver_fields(state)
    budget_cause = check_budget_halt(root, state)
    if budget_cause:
        return {
            "action": "halt-blocked",
            "cause": budget_cause,
            "budgetHalt": True,
            "resume": True,
        }
    verdict = state.get("verdict", "running")

    if verdict in ("complete", "blocked", "rejected"):
        return {"action": "terminal", "verdict": verdict, "resume": True}

    if not plan:
        return {"action": "plan", "resume": bool(state.get("phases"))}

    if plan.get("mode") != "phase":
        fail("deliver-loop requires phase-mode plan", exit_code=2)

    if not state.get("phases"):
        return {"action": "state-init", "resume": False}

    if not trunk_base_persisted(root) and not state.get("baseCapture"):
        return {"action": "base-capture", "resume": True}

    if (
        not state.get("specSeed")
        and task_list_from(state, plan)
        and not state.get("orchestratorWorktree")
    ):
        return {
            "action": "spec-seed",
            "taskList": task_list_from(state, plan),
            "resume": True,
        }

    target = (plan.get("target") or {}).get("branch") or (state.get("target") or {}).get(
        "branch"
    )
    if not target:
        fail("plan/state missing target branch")

    if all_phases_merged(state):
        completion = state.get("completion") or {}
        compound = state.get("compoundShip") or {}
        if completion.get("status") == "completed-pending-merge":
            merge_info = _target_merge_detected(root, state)
            if merge_info.get("merged"):
                return {
                    "action": "finalize-completion",
                    "cleanupSuggestion": "Run `/sw-cleanup` to prune merged branches and stale worktrees.",
                    "resume": True,
                }
            if compound.get("premergeDone"):
                return {
                    "action": "terminal-ship",
                    "note": "awaiting human merge — completion pending until merged",
                    "resume": True,
                }
        if not compound.get("premergeDone"):
            return {"action": "retrospective", "resume": True}
        return {"action": "terminal-ship", "resume": True}

    effective_plan = effective_wave_plan(state, plan)

    if state.get("orchestratorWorktree") and not wave_plan_ready(state):
        return {"action": "wave-plan-persist", "resume": True}

    if not state.get("orchestratorWorktree"):
        if state.get("nextAction") in (None, "plan", "state-init"):
            return {"action": "lock-acquire", "target": target, "resume": True}
        return {"action": "orchestrator-provision", "target": target, "resume": True}

    statuses = phase_status_map(state)
    wave_num = int(state.get("currentWave") or 1)
    wave_ids = wave_phase_ids(effective_plan, wave_num)

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

    bg_fail = check_background_task_failures(root, state, wave_ids)
    if bg_fail:
        return {
            "action": "halt-blocked",
            "cause": bg_fail,
            "resume": True,
            "watchdog": True,
        }

    merge_halt = in_flight_merge_halt(root, state, plan, wave_ids)
    if merge_halt:
        return merge_halt

    merge_ready = merge_ready_in_flight_phases(root, state, plan, wave_ids)
    if len(merge_ready) > 1:
        return {
            "action": "collect-all-ready",
            "phases": merge_ready,
            "resume": True,
        }
    if len(merge_ready) == 1:
        entry = merge_ready[0]
        return {
            "action": "merge-enqueue",
            "phaseId": entry["phaseId"],
            "phaseSlug": entry["phaseSlug"],
            "resume": True,
        }

    awaiting: list[str] = []
    for pid in sorted(wave_ids):
        meta = (state.get("phases") or {}).get(pid, {})
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", "")
        status_path = status_file_for(root, slug, None, state)
        if status_path.is_file():
            status = read_json(status_path, absent_ok=False)
            if status.get("verdict") == "blocked":
                return {
                    "action": "collect-status",
                    "phaseId": pid,
                    "phaseSlug": slug,
                    "resume": True,
                }
            if status.get("verdict") == "merge-ready-green":
                continue
        if meta.get("backgroundDispatchedAt"):
            awaiting.append(pid)
            continue
        return dispatch_or_phase_plan_entry(
            state,
            plan,
            pid,
            note="awaiting /sw-ship --phase-mode in phase worktree",
        )

    if awaiting:
        return {
            "action": "await-in-flight",
            "phaseIds": awaiting,
            "resume": True,
            "note": "awaiting terminal status.json from background Tasks",
        }

    teardown_pending = [
        pid
        for pid in sorted(wave_ids)
        if statuses.get(pid) == "teardown-pending"
    ]
    if teardown_pending:
        pid = teardown_pending[0]
        meta = (state.get("phases") or {}).get(pid, {})
        return {
            "action": "phase-teardown-run",
            "phaseId": pid,
            "phaseSlug": meta.get("slug") if isinstance(meta, dict) else pid,
            "resume": True,
        }

    ceiling = parallel_ceiling(root)
    slots_used = in_flight_count(statuses, wave_ids)
    slots_free = max(0, ceiling - slots_used)
    runnable = runnable_pending_phases(wave_ids, statuses, plan)
    if runnable and slots_free > 0:
        worktrees = state.get("phaseWorktrees") or {}
        need_provision = [pid for pid in runnable if pid not in worktrees]
        if need_provision:
            pid = need_provision[0]
            item = item_for_phase(plan, pid)
            return {
                "action": "provision-phase",
                "phaseId": pid,
                "phaseSlug": (item or {}).get("slug"),
                "resume": True,
            }
        batch_ids = runnable[:slots_free]
        batch_phases = [phase_dispatch_payload(plan, pid) for pid in batch_ids]
        if len(batch_ids) >= 2:
            return {
                "action": "dispatch-batch",
                "phaseIds": batch_ids,
                "phases": batch_phases,
                "slotCount": len(batch_ids),
                "parallelCeiling": ceiling,
                "resume": True,
                "note": "spawn N background Tasks (run_in_background: true) — one per phase worktree",
            }
        pid = batch_ids[0]
        return dispatch_or_phase_plan_entry(state, plan, pid)

    # Pending runnable phases in current wave (legacy single-phase path)
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
        return dispatch_or_phase_plan_entry(state, plan, pid)

    # Wave complete — advance or wait on blocked upstream elsewhere
    if wave_ids and all(
        statuses.get(pid) in (*MERGED_PHASE_STATUSES, "blocked", "rejected")
        for pid in wave_ids
    ):
        waves = plan.get("waves") or []
        if wave_num < len(waves):
            return {"action": "advance-wave", "fromWave": wave_num, "resume": True}
        if any(statuses.get(pid) == "blocked" for pid in wave_ids):
            return {"action": "halt-blocked", "cause": "wave-has-blocked-phases", "resume": True}

    return {
        "action": "await-in-flight",
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
    append_log(root, {"event": "driver-transition", "nextAction": action, **extra}, state)


def write_blocker_report(root: Path, state: dict[str, Any], cause: str) -> Path:
    from wave_failure import resume_deliver_command

    ec, report_payload = run_wave(root, "report", "blockers")
    report = report_payload.get("report") or {}
    if "resumeCommand" not in report:
        report["resumeCommand"] = resume_deliver_command(state)
    out = {
        "verdict": "halt",
        "cause": cause,
        "generatedAt": utc_now(),
        "report": report,
        "resumeCommand": report.get("resumeCommand"),
        "remediationAttempts": state.get("remediationAttempts") or {},
    }
    path = root / BLOCKER_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, out)
    return path


def run_plan_validate(
    root: Path,
    args: list[str],
) -> tuple[int, dict[str, Any]]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "wave_plan_validate.py"), str(root), "validate", *args],
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
    data["exitCode"] = proc.returncode
    return proc.returncode, data


def reload_state_from_path(state: dict[str, Any], state_path: Path) -> None:
    if not state_path.is_file():
        return
    try:
        state.update(read_json(state_path))
    except (StateCorruptError, json.JSONDecodeError):
        return


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
            fail_payload(data, "plan failed", ec)
        plan = load_plan(root)
        persist_cursor(root, state, "state-init")
        return {"executed": "plan", "plan": plan.get("target")}

    if action == "state-init":
        ec, data = run_wave(root, "state", "init", "--plan", str(PLAN_PATH))
        if ec != 0:
            fail_payload(data, "state init failed", ec)
        state.update(load_state(root))
        ensure_driver_fields(state)
        persist_cursor(root, state, "base-capture")
        return {"executed": "state-init"}

    if action == "base-capture":
        ec, data = run_resolve_capture(root)
        if ec != 0:
            fail_payload(data, "base capture failed", ec)
        state.update(load_state(root))
        trunk = (data.get("trunkBase") or {}) if isinstance(data, dict) else {}
        state["baseCapture"] = {
            "name": trunk.get("name"),
            "sha": trunk.get("sha"),
            "source": trunk.get("source"),
            "disclosure": data.get("disclosure"),
            "skipped": bool(data.get("skipped")),
            "at": utc_now(),
        }
        save_state(root, state)
        persist_cursor(root, state, "spec-seed")
        return {"executed": "base-capture", **data}

    if action == "spec-seed":
        tl = step.get("taskList") or task_list
        if not tl:
            fail("spec-seed requires task list")
        ec, data = run_wave(root, "spec-seed", "--task-list", str(tl))
        if ec != 0:
            fail_payload(data, "spec-seed failed", ec)
        state.update(load_state(root))
        state["specSeed"] = {
            "branch": data.get("branch"),
            "commit": data.get("commit"),
            "skipped": bool(data.get("skipped")),
            "at": utc_now(),
        }
        save_state(root, state)
        persist_cursor(root, state, "lock-acquire")
        return {"executed": "spec-seed", **data}

    if action == "lock-acquire":
        target = step.get("target") or (plan.get("target") or {}).get("branch")
        ec, data = run_wave(root, "lock", "acquire", "--target", str(target), "--nonblock")
        if ec not in (0, 20):
            fail_payload(data, "lock acquire failed", ec)
        if ec == 20:
            fail("orchestrator lock held", exit_code=20, holder=data.get("holder"))
        persist_cursor(root, state, "orchestrator-provision")
        return {"executed": "lock-acquire", "target": target}

    if action == "orchestrator-provision":
        ec, data = run_wave(
            root, "orchestrator", "provision", "--plan", str(PLAN_PATH)
        )
        if ec != 0:
            fail_payload(data, "orchestrator provision failed", ec)
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
            fail_payload(data, "phase provision failed", ec)
        worktrees = state.setdefault("phaseWorktrees", {})
        worktrees[pid] = {
            "name": data.get("name") or data.get("worktreeName"),
            "path": data.get("path") or data.get("worktreePath"),
        }
        persist_cursor(root, state, "dispatch-ship", phaseWorktrees=worktrees)
        return {"executed": "provision-phase", "phaseId": pid, **data}

    if action == "collect-all-ready":
        enqueued: list[str] = []
        for entry in step.get("phases") or []:
            slug = str(entry.get("phaseSlug", ""))
            ec, data = run_wave(root, "merge", "enqueue", "--phase-slug", slug)
            if ec != 0:
                fail_payload(data, "merge enqueue failed", ec)
            enqueued.append(slug)
        persist_cursor(root, state, "merge-run-next")
        return {"executed": "collect-all-ready", "enqueued": enqueued}

    if action == "phase-teardown-run":
        pid = str(step.get("phaseId", ""))
        ec, data = run_wave(
            root,
            "phase-teardown-run",
            "--phase-id",
            pid,
            "--plan",
            str(PLAN_PATH),
        )
        if ec != 0:
            fail_payload(data, "phase teardown failed", ec)
        state.update(load_state(root))
        persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {"executed": "phase-teardown-run", "phaseId": pid, **data}

    if action == "collect-status":
        slug = str(step.get("phaseSlug", ""))
        ec, data = run_wave(root, "status", "collect", "--phase-slug", slug)
        if ec != 0:
            fail_payload(data, "status collect failed", ec)
        state.update(load_state(root))
        persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {"executed": "collect-status", "phaseSlug": slug, **data}

    if action == "merge-enqueue":
        slug = str(step.get("phaseSlug", ""))
        ec, data = run_wave(root, "merge", "enqueue", "--phase-slug", slug)
        if ec != 0:
            fail_payload(data, "merge enqueue failed", ec)
        persist_cursor(root, state, "merge-run-next")
        return {"executed": "merge-enqueue", "phaseSlug": slug}

    if action == "merge-run-next":
        ec, data = run_wave(root, "merge", "run-next")
        if ec not in (0, 10):
            fail_payload(data, "merge run-next failed", ec)
        state.update(load_state(root))
        persist_cursor(root, state, "provision-phase")
        return {"executed": "merge-run-next", **data}

    if action == "advance-wave":
        wave_num = int(state.get("currentWave") or 1) + 1
        persist_cursor(root, state, "provision-phase", currentWave=wave_num)
        return {"executed": "advance-wave", "currentWave": wave_num}

    if action == "all-phases-complete":
        persist_cursor(root, state, "retrospective")
        return {"executed": "all-phases-complete", "next": "retrospective"}

    if action == "finalize-completion":
        ec, data = run_wave(root, "completion", "finalize-if-merged")
        if ec != 0:
            fail_payload(data, "finalize completion failed", ec)
        state.update(load_state(root))
        cleanup_payload: dict[str, Any] | None = None
        try:
            from cleanup_lib import apply_autonomous_cleanup, cleanup_autonomy_mode

            if cleanup_autonomy_mode(root) == "auto":
                cleanup_payload = apply_autonomous_cleanup(root)
        except Exception as exc:
            cleanup_payload = {"verdict": "halt", "error": str(exc)}
        persist_cursor(root, state, "suggest-cleanup")
        result: dict[str, Any] = {
            "executed": "finalize-completion",
            "cleanupSuggestion": data.get("cleanupSuggestion"),
            **data,
        }
        if cleanup_payload is not None:
            result["autonomousCleanup"] = cleanup_payload
        return result

    if action == "suggest-cleanup":
        suggestion = str(step.get("cleanupSuggestion") or "Run `/sw-cleanup` to prune merged branches and stale worktrees.")
        persist_cursor(root, state, "terminal")
        return {"executed": "suggest-cleanup", "cleanupSuggestion": suggestion}


    if action == "wave-plan-persist":
        policy = read_config_plan_policy(root)
        proposal = {"waves": plan.get("waves") or []}
        frozen = {"waves": plan.get("waves") or [], "edges": plan.get("edges") or []}
        state_path = resolve_state_path(root, state_hint=state)
        if policy == "proposed":
            _, result = run_plan_validate(
                root,
                [
                    "--tier",
                    "wave",
                    "--proposal",
                    json.dumps(proposal),
                    "--frozen-plan",
                    json.dumps(frozen),
                    "--record-rejection",
                    "--phase-id",
                    "wave",
                    "--state-path",
                    str(state_path),
                ],
            )
            reload_state_from_path(state, state_path)
            if result.get("verdict") != "pass":
                wave_plan = result.get("fallback") or wave_fallback_canonical_waves(
                    frozen, root, recorded_parent=state.get("waveBatchingPlan")
                )
            else:
                wave_plan = result.get("plan") or wave_fallback_canonical_waves(
                    frozen, root, recorded_parent=state.get("waveBatchingPlan")
                )
        else:
            result = validate_wave_plan(root, proposal, frozen_plan=frozen)
            if result.get("verdict") != "pass":
                wave_plan = result.get("fallback") or wave_fallback_canonical_waves(frozen, root)
            else:
                wave_plan = result.get("plan") or wave_fallback_canonical_waves(frozen, root)
        persist_wave_batching_plan(state, wave_plan, fail)
        set_wave_lifecycle(state, LIFECYCLE_WAVE_VALIDATED)
        save_state(root, state)
        persist_cursor(root, state, "provision-phase")
        return {"executed": "wave-plan-persist", "lifecycle": get_lifecycle(state)}

    if action == "phase-plan-entry":
        pid = str(step.get("phaseId", ""))
        slug = str(step.get("phaseSlug") or pid)
        set_phase_lifecycle(state, pid, LIFECYCLE_PHASE_PLAN_PENDING)
        policy = read_config_plan_policy(root)
        proposal = mechanical_phase_plan(root, pid, slug, state)
        if policy == "proposed":
            state_path = resolve_state_path(root, state_hint=state)
            validate_proposal = {
                "steps": proposal.get("steps") or [],
                "phaseId": pid,
            }
            _, result = run_plan_validate(
                root,
                [
                    "--tier",
                    "phase",
                    "--phase-type",
                    "ship",
                    "--proposal",
                    json.dumps(validate_proposal),
                    "--phase-id",
                    pid,
                    "--record-rejection",
                    "--state-path",
                    str(state_path),
                ],
            )
            reload_state_from_path(state, state_path)
            if result.get("verdict") != "pass":
                phase_plan = result.get("fallback") or phase_fallback_canonical_chain(
                    root,
                    "ship",
                    pid,
                    recorded_parent=state.get("waveBatchingPlan"),
                )
            else:
                phase_plan = result.get("plan") or proposal
        else:
            phase_plan = proposal
        run_dir = phase_run_dir_for_slug(root, slug)
        run_dir.mkdir(parents=True, exist_ok=True)
        from plan_persist import persist_phase_plan, phase_plan_path

        persist_phase_plan(phase_plan_path(run_dir), phase_plan)
        set_phase_lifecycle(state, pid, LIFECYCLE_PHASE_PLAN_VALIDATED)
        save_state(root, state)
        persist_cursor(root, state, compute_next_action(root, state, plan)["action"])
        return {
            "executed": "phase-plan-entry",
            "phaseId": pid,
            "phaseSlug": slug,
            "planPath": str(phase_plan_path(run_dir)),
            "lifecycle": get_lifecycle(state),
        }

    if action == "halt-blocked":
        cause = str(step.get("cause", "blocked"))
        if step.get("budgetHalt") or is_budget_halt(cause):
            return clean_consolidated_halt(root, state, plan, cause)
        if cause.startswith("phase-timeout:"):
            pid = cause.split(":", 1)[1]
            phases = state.setdefault("phases", {})
            meta = phases.get(pid)
            if isinstance(meta, dict) and meta.get("status") == "in-flight":
                meta["status"] = "blocked"
                meta["cause"] = cause
                meta["updatedAt"] = utc_now()
        state["verdict"] = "blocked"
        state["cause"] = cause
        path = write_blocker_report(root, state, cause)
        persist_cursor(root, state, "halt-blocked", blockerReport=str(path))
        return {"executed": "halt-blocked", "cause": cause, "blockerReport": str(path)}

    fail(f"unknown mechanical action: {action}")


def cmd_watchdog_check(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    cause = check_watchdog(root, state)
    timeout_min = phase_timeout_minutes(root)
    in_flight: list[dict[str, Any]] = []
    for pid, meta in (state.get("phases") or {}).items():
        if not isinstance(meta, dict) or meta.get("status") != "in-flight":
            continue
        slug = meta.get("slug", pid)
        status_path = status_file_for(root, slug, None, state)
        in_flight.append(
            {
                "phaseId": pid,
                "phaseSlug": slug,
                "startedAt": meta.get("startedAt"),
                "hasStatusJson": status_path.is_file(),
            }
        )
    if cause:
        emit(
            {
                "verdict": "fail",
                "action": "watchdog-check",
                "cause": cause,
                "phaseTimeoutMinutes": timeout_min,
                "inFlight": in_flight,
                "recommendedCommand": "bash scripts/wave.sh deliver-loop",
            },
            exit_code=20,
        )
    emit(
        {
            "verdict": "pass",
            "action": "watchdog-check",
            "phaseTimeoutMinutes": timeout_min,
            "inFlight": in_flight,
        }
    )


def cmd_deliver_loop(root: Path, args: list[str]) -> None:
    dry_run = has_flag(args, "--dry-run")
    max_steps = int(parse_kv(args, "--max-steps", "12") or "12")
    task_list = parse_kv(args, "--task-list")

    state = load_state(root, task_list)
    plan = load_plan(root)
    resumed = bool(state.get("verdict") == "running" and state.get("phases"))

    assert_run_identity(root, state, task_list, args)

    if task_list and not state.get("source_task_list"):
        state["source_task_list"] = task_list

    if not plan and task_list:
        state.setdefault("verdict", "running")
        ensure_driver_fields(state)
        save_state(root, state)

    steps_taken: list[dict[str, Any]] = []
    for _ in range(max_steps):
        state = load_state(root, task_list)
        plan = load_plan(root)
        if task_list:
            state["source_task_list"] = task_list
        init_budget_counters(state)
        step = compute_next_action(root, state, plan)
        if step["action"] != "halt-blocked":
            record_budget_tick(state, step["action"])
            save_state(root, state)
            budget_cause = check_budget_halt(root, state)
            if budget_cause:
                step = {
                    "action": "halt-blocked",
                    "cause": budget_cause,
                    "budgetHalt": True,
                    "resume": True,
                }
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
            elif step["action"] == "dispatch-batch":
                phase_ids = [str(p) for p in step.get("phaseIds") or []]
                mark_phases_in_flight(state, phase_ids, background=True)
                persist_cursor(
                    root,
                    state,
                    "dispatch-batch",
                    batchPhaseIds=phase_ids,
                )
            elif step["action"] == "dispatch-ship":
                pid = str(step.get("phaseId", ""))
                mark_phases_in_flight(state, [pid], background=True)
                persist_cursor(root, state, "dispatch-ship")
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

        if step["action"] in AWAIT_ACTIONS:
            persist_cursor(root, state, step["action"])
            emit(
                {
                    "verdict": "pass",
                    "action": "deliver-loop",
                    "resumed": resumed,
                    "awaitInFlight": True,
                    "awaitAgent": False,
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
            "next": compute_next_action(root, load_state(root, task_list), load_plan(root)),
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


def cmd_budget_tick(root: Path, args: list[str]) -> None:
    state = load_state(root)
    plan = load_plan(root)
    next_action = parse_kv(args, "--next-action")
    if not next_action:
        next_action = compute_next_action(root, state, plan)["action"]
    record_budget_tick(state, next_action)
    save_state(root, state)
    emit(
        {
            "verdict": "pass",
            "action": "budget-tick",
            "nextAction": next_action,
            "driverIterationCount": state.get("driverIterationCount"),
            "noProgressStreak": state.get("noProgressStreak"),
            "budgetCounters": state.get("budgetCounters"),
        }
    )


def cmd_budget_check(root: Path, _args: list[str]) -> None:
    state = load_state(root)
    cause = check_budget_halt(root, state)
    emit(
        {
            "verdict": "blocked" if cause else "pass",
            "action": "budget-check",
            "budgetHalt": cause,
            "driverIterationCount": state.get("driverIterationCount"),
            "noProgressStreak": state.get("noProgressStreak"),
            "budgetCounters": state.get("budgetCounters"),
            "runStartedAt": state.get("runStartedAt"),
        },
        exit_code=20 if cause else 0,
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
    elif cmd == "budget-tick":
        cmd_budget_tick(root, args)
    elif cmd == "budget-check":
        cmd_budget_check(root, args)
    elif cmd == "compute-next":
        state = load_state(root)
        plan = load_plan(root)
        emit(
            {
                "verdict": "pass",
                "next": compute_next_action(root, state, plan),
            }
        )
    elif cmd == "watchdog":
        if not args or args[0] != "check":
            fail("watchdog subcommand required: check")
        cmd_watchdog_check(root, args[1:])
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
